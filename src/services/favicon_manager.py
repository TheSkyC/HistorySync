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
from src.utils.constants import FAVICON_EXTRACTOR_TIMEOUT_SEC, FAVICON_LETTER_PALETTE
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.history_record import HistoryRecord
    from src.services.local_db import LocalDatabase

log = get_logger("favicon_manager")

_LRU_MAX_SIZE = 600
_LETTER_PALETTE = FAVICON_LETTER_PALETTE


class _LRUPixmapCache:
    """Simple LRU cache based on OrderedDict, key = (domain, size)."""

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


# ── Background Worker ─────────────────────────────────────────


class FaviconWorker(QObject):
    """
    Concurrently extracts browser favicons in a background QThread
    and writes them to FaviconCache.
    """

    # Emits a set of updated domains for the main thread to precisely invalidate the LRU cache
    finished = Signal(object)  # set[str] of updated domains

    def __init__(
        self,
        extractors: list[BaseFaviconExtractor],
        cache: FaviconCache,
        since_ts: int = 0,
        known_domains: set[str] | None = None,
    ):
        super().__init__()
        self._extractors = extractors
        self._cache = cache
        self._since_ts = since_ts
        self._known_domains = known_domains
        self._cancelled = False

    def cancel(self) -> None:
        """Requests cancellation (best-effort)."""
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
            "FaviconWorker: starting %d extractor(s) with %d worker thread(s) (since_ts=%d, domain_filter=%s)",
            len(available),
            n_workers,
            self._since_ts,
            f"{len(self._known_domains)} domains" if self._known_domains is not None else "disabled",
        )

        def _extract_one(
            extractor: BaseFaviconExtractor,
        ) -> tuple[str, list[FaviconRecord]]:
            return extractor.browser_type, extractor.extract(
                since_ts=self._since_ts,
                known_domains=self._known_domains,
            )

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
    Main controller for the favicon system (runs in the main thread).

    Usage::

        favicon_manager.schedule_extraction()       # Trigger background extraction (non-blocking)
        pixmap = favicon_manager.get_pixmap(url)    # Get icon (synchronous, non-blocking)
        favicon_manager.prefetch_pixmaps(records)   # Batch prefetch LRU

    Signals:
        favicons_updated(domains: set[str])
            Emitted when background extraction completes, carrying the set of
            updated domains.
    """

    favicons_updated = Signal(object)  # set[str] — updated domains

    def __init__(self, config: AppConfig, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config

        db_path = config.get_favicon_db_path()
        self._cache = FaviconCache(db_path)
        self._lru = _LRUPixmapCache()
        self._svg_renderer_cache: dict[bytes, object] = {}  # bounded, see _svg_to_pixmap
        self._svg_renderer_cache_max = 200
        # Cache for letter-placeholder pixmaps: keyed by (letter, size, palette_index).
        # Letter pixmaps are purely deterministic (no external state), so they can be
        # kept indefinitely — the keyspace is tiny (26 letters × ~2 sizes × palette).
        self._letter_pixmap_cache: dict[tuple, QPixmap] = {}

        # Raw (pre-scale) pixmap cache — avoids calling QPixmap.loadFromData() more
        # than once per favicon domain even when the same favicon is requested at
        # multiple sizes (e.g. 16 px in the table and 14 px in the scroll bubble).
        # Keyed by domain string; bounded to _RAW_PIXMAP_CACHE_MAX entries via FIFO
        # eviction (insertions are rare so OrderedDict overhead is unnecessary).
        self._raw_pixmap_cache: dict[str, QPixmap] = {}
        self._RAW_PIXMAP_CACHE_MAX = 1200  # matches roughly 2 × LRU max (600)

        # Holds the FaviconExtractorManager registry instead of a bare list
        self._ext_manager = FaviconExtractorManager(
            disabled_browsers=config.extractor.disabled_browsers,
            custom_paths=config.extractor.custom_paths,
        )

        self._local_db: LocalDatabase | None = None

        self._thread: QThread | None = None
        self._worker: FaviconWorker | None = None
        self._is_running = False

    @property
    def favicon_cache(self) -> FaviconCache:
        """Expose the underlying FaviconCache for direct domain lookups (e.g. overlay)."""
        return self._cache

    def set_local_db(self, local_db: LocalDatabase) -> None:
        """
        Provides a reference to the history database.

        Once set, :meth:`schedule_extraction` will query the database for the
        set of known domains and pass it to the worker, limiting extraction to
        only those domains.  Safe to call at any time; takes effect on the next
        :meth:`schedule_extraction` call.
        """
        self._local_db = local_db

    # ── Background Extraction Scheduling ──────────────────────

    def schedule_extraction(
        self,
        target_browsers: list[str] | None = None,
    ) -> None:
        """
        Asynchronously extracts browser favicons in a background QThread and
        writes them to the cache.  If the previous extraction is still running,
        this call is silently ignored to prevent concurrent writes.

        Before spawning the worker this method computes two optimisation
        parameters on the **main thread** (both reads are fast index scans):

        * **since_ts** — the most recent ``updated_at`` timestamp in the
          favicon cache.  Passed to each extractor so only browser DB entries
          newer than this point are fetched.  ``0`` on an empty cache triggers
          a full extraction.

        * **known_domains** — the full set of host names present in the history
          database (requires :meth:`set_local_db` to have been called).  The
          extractor discards icons whose domain is not in this set.  ``None``
          when no database is available (disables the filter).

        Parameters
        ----------
        target_browsers:
            Limits extraction to the specified browsers.  ``None`` (default)
            means all registered and available browsers.
        """
        if self._is_running or (self._thread is not None and self._thread.isRunning()):
            log.debug("FaviconManager: extraction already running or previous thread not yet cleaned up, skipping")
            return

        extractors = self._ext_manager.get_available(target_browsers)
        if not extractors:
            log.info(
                "FaviconManager: no available extractors%s, skipping",
                f" for {target_browsers}" if target_browsers is not None else "",
            )
            return

        # ── Compute optimisation parameters (main thread, fast reads) ────
        since_ts: int = 0
        known_domains: set[str] | None = None
        try:
            since_ts = self._cache.get_last_updated_ts()
        except Exception as exc:
            log.warning("FaviconManager: could not read last_updated_ts, using 0: %s", exc)

        if self._local_db is not None:
            try:
                known_domains = self._local_db.get_all_known_domains()
                log.debug(
                    "FaviconManager: domain filter loaded — %d known domains (since_ts=%d)",
                    len(known_domains),
                    since_ts,
                )
            except Exception as exc:
                log.warning("FaviconManager: could not load known domains, filter disabled: %s", exc)
                known_domains = None

        self._is_running = True
        thread = QThread()
        worker = FaviconWorker(extractors, self._cache, since_ts=since_ts, known_domains=known_domains)
        self._worker = worker
        self._thread = thread
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)  # QueuedConnection (default): slot runs safely in main thread
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        thread.start()
        log.info(
            "FaviconManager: extraction started (since_ts=%d, domain_filter=%s)",
            since_ts,
            f"{len(known_domains)} domains" if known_domains is not None else "disabled",
        )

    def shutdown(self, timeout_ms: int = 10000) -> None:
        """
        Graceful shutdown: cancels running extraction tasks and waits for the thread to exit.
        Should be called before QApplication.quit().
        """
        if self._thread is None or not self._thread.isRunning():
            self._cache.close()
            return
        if self._worker is not None:
            self._worker.cancel()
        self._thread.quit()
        log.info("FaviconManager: waiting for worker thread (timeout=%dms)...", timeout_ms)
        if not self._thread.wait(timeout_ms):
            log.warning("FaviconManager: worker thread did not finish in time, forcing quit")
            self._thread.quit()
            self._thread.wait(2000)
        self._cache.close()

    @Slot()
    def _on_thread_finished(self) -> None:
        if self.sender() is not self._thread:
            return
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

    # ── Configuration Hot Reload ──────────────────────────────

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

    # ── Main Thread QPixmap Retrieval ─────────────────────────

    def get_pixmap(self, url: str, size: int = 16, domain: str | None = None) -> QPixmap:
        """
        Returns the QPixmap icon for the given URL's domain.
        Must be called from the main thread.

        Pass *domain* when the caller has already computed it (e.g. from
        HistoryRecord.domain) to skip the extract_domain(url) call entirely.

        Lookup chain:
          In-memory LRU -> FaviconCache (Persistent SQLite connection) -> Letter placeholder
        """
        if domain is None:
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

            # If subdomain misses, attempt fallback to root domain (e.g., tieba.baidu.com -> baidu.com)
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
        Batch prefetches LRU icon cache for a list of history records.
        Must be called from the main thread.
        Combines multiple individual SQLite get() calls into a single get_many(),
        avoiding triggering SQLite connections row-by-row in data(DecorationRole).
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

        # Query all involved root domains simultaneously for fallback use
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

            # Subdomain miss, attempt root domain
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
        """Returns the number of domains with cached icons (used for statistics display)."""
        return self._cache.get_total_count()

    # ── Rendering Utilities ───────────────────────────────────

    def _render_record(self, record: FaviconRecord, size: int) -> QPixmap:
        try:
            if record.data_type == "svg":
                return self._svg_to_pixmap(record.data, size)
            return self._blob_to_pixmap(record.data, size, cache_key=record.domain)
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
                if len(self._svg_renderer_cache) >= self._svg_renderer_cache_max:
                    self._svg_renderer_cache.pop(next(iter(self._svg_renderer_cache)))
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

    def _blob_to_pixmap(self, data: bytes, size: int, cache_key: str = "") -> QPixmap:
        """Decode *data* into a QPixmap scaled to *size* × *size*."""
        # Look up already-decoded raw pixmap
        raw: QPixmap | None = self._raw_pixmap_cache.get(cache_key) if cache_key else None

        if raw is None:
            raw = QPixmap()
            if not raw.loadFromData(data):
                return QPixmap()
            if cache_key:
                # FIFO eviction: if over limit, remove an arbitrary entry cheaply
                if len(self._raw_pixmap_cache) >= self._RAW_PIXMAP_CACHE_MAX:
                    self._raw_pixmap_cache.pop(next(iter(self._raw_pixmap_cache)))
                self._raw_pixmap_cache[cache_key] = raw

        if raw.width() == size and raw.height() == size:
            return raw
        return raw.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _letter_pixmap(self, letter: str, size: int, seed: str = "") -> QPixmap:
        """
        Generates a colored rounded square QPixmap containing a single letter as a placeholder
        for missing icons. The color is deterministically chosen from a palette based on the
        hash of the seed (domain), ensuring consistent colors for the same domain.

        Results are cached in _letter_pixmap_cache by (letter, size, palette_index) so that
        the md5 hash + full QPainter path is only executed once per unique combination.
        """
        idx = int(hashlib.md5(seed.encode()).hexdigest()[:4], 16) % len(_LETTER_PALETTE)
        cache_key = (letter, size, idx)
        cached = self._letter_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached

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

        self._letter_pixmap_cache[cache_key] = pixmap
        return pixmap
