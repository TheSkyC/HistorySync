# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlparse

from src.services.browser_defs import BrowserDef
from src.services.extractors.base_extractor import open_db_snapshot
from src.services.favicon_cache import FaviconRecord
from src.utils.logger import get_logger

log = get_logger("favicon_extractor")


# ── 原始数据结构 ──────────────────────────────────────────────


@dataclass
class _RawEntry:
    """从浏览器数据库读取的原始行，提取后立即归一化。"""

    domain: str  # 已提取好的注册域名（空字符串表示无效，应丢弃）
    data: bytes  # 已归一化为 bytes 的图标数据
    data_type: str  # 已检测好的格式类型
    width: int  # SVG 统一为 0


# ── 工具函数 ──────────────────────────────────────────────────


def extract_domain(url: str) -> str:
    """
    从 URL 中提取可用作缓存键的注册域名。
    只处理 http/https，其他 scheme 返回空串。
    剥除 www. 前缀以合并同站图标。
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ""
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _normalize_data(raw: bytes | str | memoryview | None) -> bytes:
    """
    将 SQLite 返回的 BLOB 值统一转为 bytes。
    Firefox 将 SVG 文本存入 BLOB 列，Python sqlite3 会以 str 返回。
    """
    if raw is None:
        return b""
    if isinstance(raw, memoryview):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return raw


def _detect_data_type(data: bytes) -> str:
    """
    通过魔数字节或文本特征检测图标格式。
    SVG 检测放在最前面，因为 Firefox 以 TEXT 存储 SVG。
    """
    if not data:
        return "unknown"

    # SVG：检查前 300 字节是否包含 XML/SVG 标记
    try:
        snippet = data[:300].decode("utf-8", errors="replace").lstrip()
        if snippet.startswith("<svg") or snippet.startswith("<?xml"):
            return "svg"
    except Exception:
        pass

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "unknown"


def _select_best_per_domain(entries: list[_RawEntry]) -> list[FaviconRecord]:
    """
    将同一 domain 的多条原始记录折叠为一条最优记录。
    优先级：SVG（无损缩放）> 高分辨率位图 > 低分辨率位图。
    """
    by_domain: dict[str, list[_RawEntry]] = defaultdict(list)
    for e in entries:
        if e.domain and e.data and e.data_type != "unknown":
            by_domain[e.domain].append(e)

    def _score(e: _RawEntry) -> int:
        return 1_000_000 if e.data_type == "svg" else e.width

    now = int(time.time())
    return [
        FaviconRecord(
            domain=domain,
            data=max(ents, key=_score).data,
            data_type=max(ents, key=_score).data_type,
            width=max(ents, key=_score).width,
            updated_at=now,
        )
        for domain, ents in by_domain.items()
    ]


# ── 基类 ──────────────────────────────────────────────────────


class BaseFaviconExtractor(ABC):
    def __init__(self, defn: BrowserDef):
        self._defn = defn

    @property
    def browser_type(self) -> str:
        return self._defn.browser_type

    @property
    def display_name(self) -> str:
        return self._defn.display_name

    def is_available(self) -> bool:
        return self._defn.is_favicon_available()

    def extract(self) -> list[FaviconRecord]:
        """提取该浏览器全部 Profile 的图标，返回去重后的 FaviconRecord 列表。"""
        all_entries: list[_RawEntry] = []

        for profile_name, favicon_db in self._defn.iter_favicon_db_paths():
            if not favicon_db.exists():
                continue
            log.info("[%s] Extracting favicons from profile '%s'", self.browser_type, profile_name)
            try:
                with open_db_snapshot(favicon_db, self.display_name) as conn:
                    entries = self._extract_entries(conn)
                    all_entries.extend(entries)
                    log.info(
                        "[%s] '%s' → %d raw entries",
                        self.browser_type,
                        profile_name,
                        len(entries),
                    )
            except RuntimeError:
                log.warning(
                    "[%s] Could not open favicon DB: %s",
                    self.browser_type,
                    favicon_db,
                )
            except Exception as exc:
                log.warning(
                    "[%s] Extraction failed for '%s': %s",
                    self.browser_type,
                    profile_name,
                    exc,
                )

        records = _select_best_per_domain(all_entries)
        log.info("[%s] Total: %d unique domains", self.browser_type, len(records))
        return records

    # ── 子类实现 ──────────────────────────────────────────────

    @abstractmethod
    def _extract_entries(self, conn: sqlite3.Connection) -> list[_RawEntry]:
        """从已打开的内存快照连接中提取原始条目。连接为只读，无需手动关闭。"""


# ── Chromium 图标提取器 ───────────────────────────────────────


class ChromiumFaviconExtractor(BaseFaviconExtractor):
    """
    适用于 Chrome / Edge / Brave 等 Chromium 系浏览器。
    图标数据库：<Profile Dir>/Favicons（无扩展名）

    表关系：
        icon_mapping (page_url → icon_id)
          → favicon_bitmaps (icon_id, image_data BLOB, width)
    Chromium 统一将图标转存为 PNG，image_data 始终为二进制。

    override_dir：若提供，则使用该目录替换 BrowserDef 的 User Data 目录，
    用于支持 ExtractorConfig.custom_paths 自定义路径。
    """

    _SQL = """
        SELECT
            im.page_url,
            fb.image_data,
            fb.width
        FROM (
            SELECT icon_id, MIN(page_url) AS page_url
            FROM icon_mapping
            GROUP BY icon_id
        ) im
        JOIN favicon_bitmaps fb ON im.icon_id = fb.icon_id
        WHERE fb.image_data IS NOT NULL
          AND length(fb.image_data) > 0
    """

    def __init__(self, defn: BrowserDef, override_dir: Path | None = None):
        if override_dir is not None:
            # 用覆盖目录替换原有路径，创建新的 BrowserDef
            from src.services.browser_defs import BrowserDef as _BrowserDef

            defn = _BrowserDef(
                browser_type=defn.browser_type,
                display_name=defn.display_name,
                engine=defn.engine,
                _data_dirs=(override_dir,),
            )
        super().__init__(defn)

    def _extract_entries(self, conn: sqlite3.Connection) -> list[_RawEntry]:
        entries: list[_RawEntry] = []
        for row in conn.execute(self._SQL):
            domain = extract_domain(row["page_url"])
            if not domain:
                continue
            data = _normalize_data(row["image_data"])
            if not data:
                continue
            dtype = _detect_data_type(data)
            if dtype == "unknown":
                continue
            entries.append(
                _RawEntry(
                    domain=domain,
                    data=data,
                    data_type=dtype,
                    width=row["width"] or 0,
                )
            )
        return entries


# ── Firefox 图标提取器 ────────────────────────────────────────


class FirefoxFaviconExtractor(BaseFaviconExtractor):
    """
    适用于 Mozilla Firefox。
    图标数据库：<Profile Dir>/favicons.sqlite

    表关系：
        moz_pages_w_icons (page_url → id)
          → moz_icons_to_pages (page_id → icon_id)
          → moz_icons (id, data BLOB|TEXT, width)

    特殊处理：
        - Firefox 有时将 SVG 以 TEXT 类型存入 BLOB 列，
          Python sqlite3 读取时返回 str，_normalize_data() 统一处理。
        - width=65535 是 Firefox 标记 SVG 的约定值，归一化为 0。
        - icon_url 以 fake-favicon-uri: 开头的条目是占位符，data 字段仍有效。
    """

    _SQL = """
        SELECT
            mp.page_url,
            mi.data,
            mi.width
        FROM moz_pages_w_icons mp
        JOIN moz_icons_to_pages mitp ON mp.id = mitp.page_id
        JOIN moz_icons mi ON mitp.icon_id = mi.id
        WHERE mi.data IS NOT NULL
          AND length(mi.data) > 0
    """

    def __init__(self, defn: BrowserDef):
        super().__init__(defn)

    def _extract_entries(self, conn: sqlite3.Connection) -> list[_RawEntry]:
        entries: list[_RawEntry] = []
        for row in conn.execute(self._SQL):
            domain = extract_domain(row["page_url"])
            if not domain:
                continue
            data = _normalize_data(row["data"])
            if not data:
                continue
            dtype = _detect_data_type(data)
            if dtype == "unknown":
                continue
            # width=65535 是 Firefox SVG 的标记值，归一化为 0
            raw_width = row["width"] or 0
            width = 0 if raw_width == 65535 else raw_width
            entries.append(
                _RawEntry(
                    domain=domain,
                    data=data,
                    data_type=dtype,
                    width=width,
                )
            )
        return entries
