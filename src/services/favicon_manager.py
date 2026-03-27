# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRect, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from src.models.app_config import AppConfig
from src.services.extractors.favicon_extractor import (
    BaseFaviconExtractor,
    extract_domain,
    extract_root_domain,
)
from src.services.favicon_cache import FaviconCache, FaviconRecord
from src.services.favicon_extractor_manager import FaviconExtractorManager
from src.utils.constants import FAVICON_EXTRACTOR_TIMEOUT_SEC
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.history_record import HistoryRecord

log = get_logger("favicon_manager")

_LRU_MAX_SIZE = 600
_LETTER_PALETTE = [
    "#4285F4",
    "#EA4335",
    "#34A853",
    "#FBBC04",
    "#7C4DFF",
    "#FF6D00",
    "#00BCD4",
    "#8BC34A",
    "#FF6B6B",
    "#4ECDC4",
    "#45B7D1",
    "#C678DD",
]


class _LRUPixmapCache:
    """基于 OrderedDict 的简单 LRU 缓存，key = (domain, size)。"""

    def __init__(self, max_size: int = _LRU_MAX_SIZE):
        self._cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._max = max_size

    def get(self, key: tuple[str, int]) -> QPixmap | None:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: tuple[str, int], pixmap: QPixmap) -> None:
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def invalidate_domain(self, domain: str) -> None:
        keys = [k for k in self._cache if k[0] == domain]
        for k in keys:
            del self._cache[k]

    def invalidate_domains(self, domains: set[str]) -> None:
        keys = [k for k in self._cache if k[0] in domains]
        for k in keys:
            del self._cache[k]


# ── 后台 Worker ───────────────────────────────────────────────


class FaviconWorker(QObject):
    """
    在后台 QThread 中并发提取各浏览器图标并写入 FaviconCache。
    """

    # 发送已更新的 domain 集合，供主线程精确失效 LRU 缓存
    finished = Signal(object)  # set[str] of updated domains

    def __init__(
        self,
        extractors: list[BaseFaviconExtractor],
        cache: FaviconCache,
    ):
        super().__init__()
        self._extractors = extractors
        self._cache = cache
        self._cancelled = False

    def cancel(self) -> None:
        """请求取消（尽力而为）。"""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        available = [e for e in self._extractors if e.is_available()]
        updated_domains: set[str] = set()

        if not available:
            log.info("FaviconWorker: no available extractors, done")
            if not self._cancelled:
                self.finished.emit(updated_domains)
            return

        n_workers = min(4, len(available))
        log.info(
            "FaviconWorker: starting %d extractor(s) with %d worker thread(s)",
            len(available),
            n_workers,
        )

        def _extract_one(
            extractor: BaseFaviconExtractor,
        ) -> tuple[str, list[FaviconRecord]]:
            return extractor.browser_type, extractor.extract()

        with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="hs-fav") as pool:
            future_to_ext = {pool.submit(_extract_one, ext): ext for ext in available}

            for future in as_completed(future_to_ext):
                if self._cancelled:
                    log.info("FaviconWorker: cancelled, aborting remaining tasks")
                    break
                ext = future_to_ext[future]
                try:
                    bt, records = future.result(timeout=FAVICON_EXTRACTOR_TIMEOUT_SEC)
                    if records:
                        self._cache.upsert_many(records)
                        updated_domains.update(r.domain for r in records)
                        log.info("[%s] FaviconWorker: %d domains written to cache", bt, len(records))
                except TimeoutError:
                    log.warning(
                        "[%s] favicon extraction timed out after %ds, skipping",
                        ext.browser_type,
                        FAVICON_EXTRACTOR_TIMEOUT_SEC,
                    )
                except Exception as exc:
                    log.error(
                        "[%s] favicon extraction error: %s",
                        ext.browser_type,
                        exc,
                        exc_info=True,
                    )

        if self._cancelled:
            log.info("FaviconWorker: cancelled, skipping finished signal")
            return

        try:
            self._cache.prune_stale()
        except Exception as exc:
            log.warning("FaviconCache prune failed: %s", exc)

        log.info("FaviconWorker done: %d domains updated", len(updated_domains))
        self.finished.emit(updated_domains)


# ── FaviconManager ────────────────────────────────────────────


class FaviconManager(QObject):
    """
    图标系统主控制器（在主线程中运行）。

    用法：
        favicon_manager.schedule_extraction()       # 触发后台提取（非阻塞）
        pixmap = favicon_manager.get_pixmap(url)    # 获取图标（同步，非阻塞）
        favicon_manager.prefetch_pixmaps(records)   # 批量预热 LRU

    信号：
        favicons_updated(domains: set[str])
            后台提取完成后发出，携带本次更新的 domain 集合。
    """

    favicons_updated = Signal(object)  # set[str] — updated domains

    def __init__(self, config: AppConfig, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config

        db_path = config.get_favicon_db_path()
        self._cache = FaviconCache(db_path)
        self._lru = _LRUPixmapCache()
        self._svg_renderer_cache: dict[bytes, object] = {}

        # 持有 FaviconExtractorManager 注册表，而非裸 list
        self._ext_manager = FaviconExtractorManager(
            disabled_browsers=config.extractor.disabled_browsers,
            custom_paths=config.extractor.custom_paths,
        )

        self._thread: QThread | None = None
        self._worker: FaviconWorker | None = None
        self._is_running = False

    # ── 后台提取调度 ──────────────────────────────────────────

    def schedule_extraction(
        self,
        target_browsers: list[str] | None = None,
    ) -> None:
        """
        在后台 QThread 中异步提取浏览器图标并写入缓存。
        若上一次提取还未结束，本次调用会被静默忽略（避免并发写入缓存）。

        Parameters
        ----------
        target_browsers:
            限定本次只提取指定浏览器的图标。传入 None（默认）表示提取
            所有已注册且可用的浏览器图标。
        """
        if self._is_running:
            log.debug("FaviconManager: extraction already running, skipping")
            return

        extractors = self._ext_manager.get_available(target_browsers)
        if not extractors:
            log.info(
                "FaviconManager: no available extractors%s, skipping",
                f" for {target_browsers}" if target_browsers is not None else "",
            )
            return

        self._is_running = True
        thread = QThread()
        worker = FaviconWorker(extractors, self._cache)
        self._worker = worker
        self._thread = thread
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        # DirectConnection：确保槽在信号发出时立即执行，避免 deleteLater 后访问已销毁对象
        worker.finished.connect(self._on_worker_finished, Qt.DirectConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        thread.start()
        log.info("FaviconManager: extraction started")

    def shutdown(self, timeout_ms: int = 10000) -> None:
        """
        优雅关闭：取消正在运行的提取任务，等待线程退出。
        应在 QApplication.quit() 之前调用。
        """
        if self._thread is None or not self._thread.isRunning():
            return
        if self._worker is not None:
            self._worker.cancel()
        log.info("FaviconManager: waiting for worker thread (timeout=%dms)...", timeout_ms)
        if not self._thread.wait(timeout_ms):
            log.warning("FaviconManager: worker thread did not finish in time, forcing quit")
            self._thread.quit()
            self._thread.wait(2000)

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    @Slot(object)
    def _on_worker_finished(self, updated_domains: set) -> None:
        self._is_running = False
        if updated_domains:
            extra: set[str] = set()
            for key in list(self._lru._cache):
                cached_domain = key[0]
                root = extract_root_domain(cached_domain)
                if root != cached_domain and root in updated_domains:
                    extra.add(cached_domain)
            self._lru.invalidate_domains(updated_domains | extra)
            self.favicons_updated.emit(updated_domains)

    # ── 配置热更新 ────────────────────────────────────────────

    def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._ext_manager.update_config(
            disabled_browsers=config.extractor.disabled_browsers,
            custom_paths=config.extractor.custom_paths,
        )
        log.info(
            "FaviconManager: config updated via FaviconExtractorManager, %d extractors registered",
            len(self._ext_manager.get_all_registered()),
        )

    # ── 主线程 QPixmap 获取 ───────────────────────────────────

    def get_pixmap(self, url: str, size: int = 16) -> QPixmap:
        """
        返回 URL 对应域名的图标 QPixmap。
        必须从主线程调用。

        查找链路：
          内存 LRU → FaviconCache (SQLite 持久连接) → 字母占位图
        """
        domain = extract_domain(url)
        cache_key = (domain or url, size)

        pixmap = self._lru.get(cache_key)
        if pixmap is not None:
            return pixmap

        if domain:
            record = self._cache.get(domain)
            if record:
                pixmap = self._render_record(record, size)
                if pixmap and not pixmap.isNull():
                    self._lru.put(cache_key, pixmap)
                    return pixmap

            # 子域名未命中时，尝试根域名回退（如 tieba.baidu.com -> baidu.com）
            root = extract_root_domain(domain)
            if root and root != domain:
                root_key = (root, size)
                pixmap = self._lru.get(root_key)
                if pixmap is None:
                    root_record = self._cache.get(root)
                    if root_record:
                        pixmap = self._render_record(root_record, size)
                        if pixmap and not pixmap.isNull():
                            self._lru.put(root_key, pixmap)
                if pixmap and not pixmap.isNull():
                    self._lru.put(cache_key, pixmap)
                    return pixmap

        letter = (domain[0] if domain else (url[0] if url else "?")).upper()
        pixmap = self._letter_pixmap(letter, size, seed=domain or url)
        self._lru.put(cache_key, pixmap)
        return pixmap

    def prefetch_pixmaps(self, records: list[HistoryRecord], size: int = 16) -> None:
        """
        为一批历史记录批量预热 LRU 图标缓存。必须从主线程调用。
        将多次单独 SQLite get() 合并为一次 get_many()，
        避免 Qt 在 data(DecorationRole) 中逐行触发 SQLite 连接。
        """
        domain_to_url: dict[str, str] = {}
        true_domains: set[str] = set()

        for rec in records:
            domain = extract_domain(rec.url)
            key = domain or rec.url
            if self._lru.get((key, size)) is None:
                domain_to_url[key] = rec.url
                if domain:
                    true_domains.add(domain)

        if not domain_to_url:
            return

        # 同时查询所有涉及的根域名，供回退使用
        root_domains: set[str] = set()
        for d in true_domains:
            root = extract_root_domain(d)
            if root and root != d:
                root_domains.add(root)

        all_lookup = true_domains | root_domains
        db_records = self._cache.get_many(all_lookup) if all_lookup else {}

        for domain_or_url, _url in domain_to_url.items():
            cache_key = (domain_or_url, size)
            if self._lru.get(cache_key) is not None:
                continue

            db_rec = db_records.get(domain_or_url)
            if db_rec:
                pixmap = self._render_record(db_rec, size)
                if pixmap and not pixmap.isNull():
                    self._lru.put(cache_key, pixmap)
                    continue

            # 子域名未命中，尝试根域名
            root = extract_root_domain(domain_or_url)
            if root and root != domain_or_url:
                root_rec = db_records.get(root)
                if root_rec:
                    pixmap = self._render_record(root_rec, size)
                    if pixmap and not pixmap.isNull():
                        self._lru.put(cache_key, pixmap)
                        continue

            letter = (domain_or_url[0] if domain_or_url else "?").upper()
            pixmap = self._letter_pixmap(letter, size, seed=domain_or_url)
            self._lru.put(cache_key, pixmap)

    def get_favicon_count(self) -> int:
        """返回缓存中已有图标的域名数量（用于统计显示）。"""
        return self._cache.get_total_count()

    # ── 渲染工具 ──────────────────────────────────

    def _render_record(self, record: FaviconRecord, size: int) -> QPixmap:
        try:
            if record.data_type == "svg":
                return self._svg_to_pixmap(record.data, size)
            return self._blob_to_pixmap(record.data, size)
        except Exception as exc:
            log.warning("FaviconManager: render failed for '%s': %s", record.domain, exc)
            return QPixmap()

    def _svg_to_pixmap(self, svg_data: bytes, size: int) -> QPixmap:
        try:
            import hashlib as _hashlib

            from PySide6.QtCore import QByteArray
            from PySide6.QtSvg import QSvgRenderer

            svg_key = _hashlib.sha256(svg_data).digest()
            renderer = self._svg_renderer_cache.get(svg_key)
            if renderer is None:
                renderer = QSvgRenderer(QByteArray(svg_data))
                if not renderer.isValid():
                    return QPixmap()
                self._svg_renderer_cache[svg_key] = renderer

            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            renderer.render(painter)
            painter.end()
            return pixmap
        except ImportError:
            log.warning("PySide6.QtSvg not available; SVG favicon cannot be rendered")
            return QPixmap()

    def _blob_to_pixmap(self, data: bytes, size: int) -> QPixmap:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return QPixmap()
        if pixmap.width() != size or pixmap.height() != size:
            pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pixmap

    def _letter_pixmap(self, letter: str, size: int, seed: str = "") -> QPixmap:
        """
        生成以单个字母为内容的彩色圆角方块 QPixmap，作为图标缺失时的占位符。
        通过 seed（域名）的哈希值从调色板中确定性地选取颜色，同域名颜色稳定。
        """
        idx = int(hashlib.md5(seed.encode()).hexdigest()[:4], 16) % len(_LETTER_PALETTE)
        bg_color = QColor(_LETTER_PALETTE[idx])

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)
        radius = max(2, size // 5)
        painter.drawRoundedRect(0, 0, size, size, radius, radius)

        painter.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(max(8, int(size * 0.55)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, letter)
        painter.end()

        return pixmap
