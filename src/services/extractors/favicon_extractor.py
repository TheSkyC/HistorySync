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


# ── Raw Data Structures ───────────────────────────────────────


@dataclass
class _RawEntry:
    """Raw row read from the browser database, normalized immediately after extraction."""

    domain: str  # Extracted registered domain (empty string means invalid and should be discarded)
    data: bytes  # Normalized icon data as bytes
    data_type: str  # Detected format type
    width: int  # Uniformly 0 for SVG


# ── Utilities ─────────────────────────────────────────────────


def extract_domain(url: str) -> str:
    """
    Extracts the registered domain from a URL to use as a cache key.
    Only processes http/https; returns an empty string for other schemes.
    Strips the 'www.' prefix to merge icons from the same site.
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


def extract_root_domain(domain: str) -> str:
    """
    Extracts the root domain (registered domain) from a full domain for favicon fallback lookup.
    Example: tieba.baidu.com -> baidu.com, www.zhihu.com -> zhihu.com.
    Uses a simple 'last two segments' strategy, with special handling for common
    second-level ccTLDs (e.g., co.uk, com.cn) to take three segments.
    """
    if not domain:
        return ""
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    _SECOND_LEVEL_TLDS = {
        "com",
        "net",
        "org",
        "edu",
        "gov",
        "co",
        "ac",
        "or",
        "ne",
    }
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_TLDS and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _normalize_data(raw: bytes | str | memoryview | None) -> bytes:
    """
    Unifies BLOB values returned by SQLite into bytes.
    Firefox stores SVG text in BLOB columns, which Python's sqlite3 returns as str.
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
    Detects icon format via magic bytes or text signatures.
    SVG detection is prioritized because Firefox stores SVGs as TEXT.
    """
    if not data:
        return "unknown"

    # SVG: Check if the first 300 bytes contain XML/SVG tags
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
    Collapses multiple raw records for the same domain into a single optimal record.
    Priority: SVG (lossless scaling) > high-resolution bitmap > low-resolution bitmap.
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


# ── Base Class ────────────────────────────────────────────────


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
        """Extracts icons for all profiles of this browser, returning a deduplicated list of FaviconRecords."""
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

    # ── Subclass Implementation ───────────────────────────────

    @abstractmethod
    def _extract_entries(self, conn: sqlite3.Connection) -> list[_RawEntry]:
        """Extracts raw entries from an opened in-memory snapshot connection. The connection is read-only."""


# ── Chromium Favicon Extractor ────────────────────────────────


class ChromiumFaviconExtractor(BaseFaviconExtractor):
    """
    Suitable for Chromium-based browsers like Chrome / Edge / Brave.
    Icon database: <Profile Dir>/Favicons (no extension)

    Table relations:
        icon_mapping (page_url → icon_id)
          → favicon_bitmaps (icon_id, image_data BLOB, width)
    Chromium uniformly converts icons to PNG, so image_data is always binary.

    override_dir: If provided, replaces the BrowserDef's User Data directory
    to support custom paths via ExtractorConfig.custom_paths.
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
            # Replace the original path with the override directory, creating a new BrowserDef
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


# ── Firefox Favicon Extractor ─────────────────────────────────


class FirefoxFaviconExtractor(BaseFaviconExtractor):
    """
    Suitable for Mozilla Firefox.
    Icon database: <Profile Dir>/favicons.sqlite

    Table relations:
        moz_pages_w_icons (page_url → id)
          → moz_icons_to_pages (page_id → icon_id)
          → moz_icons (id, data BLOB|TEXT, width)

    Special handling:
        - Firefox sometimes stores SVGs as TEXT in BLOB columns.
          Python's sqlite3 returns this as str, which _normalize_data() handles.
        - width=65535 is Firefox's convention for SVGs, normalized to 0.
        - icon_url starting with fake-favicon-uri: are placeholders, but the data field remains valid.
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
            # width=65535 is Firefox's marker for SVG, normalized to 0
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
