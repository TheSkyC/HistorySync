# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
import sqlite3
import time
from typing import TYPE_CHECKING

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef, make_custom_chromium_def
from src.services.extractors.base_extractor import open_db_snapshot
from src.services.extractors.chromium_extractor import (
    ChromiumExtractor,
    chromium_time_to_unix,
)
from src.services.extractors.firefox_extractor import FirefoxExtractor
from src.services.extractors.safari_extractor import SafariExtractor
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.services.local_db import LocalDatabase

log = get_logger("db_importer")


# ── Enum: Database Types ──────────────────────────────────────────


class DbType(Enum):
    CHROMIUM = auto()  # Chromium-based browsers (Chrome, Edge, Brave, etc.)
    FIREFOX = auto()  # Firefox / LibreWolf, etc.
    SAFARI = auto()  # Safari History.db
    HISTORYSYNC = auto()  # HistorySync's own history.db
    WEBASSIST = auto()  # Edge WebAssistDatabase (navigation_history table)
    UNKNOWN = auto()  # Unrecognized format


# Chromium browser browser_type identifier -> display name mapping
# Used for UI dropdown options
CHROMIUM_BROWSER_OPTIONS: list[tuple[str, str]] = [
    ("chrome", "Google Chrome"),
    ("edge", "Microsoft Edge"),
    ("brave", "Brave"),
    ("chromium", "Chromium"),
    ("opera", "Opera"),
    ("vivaldi", "Vivaldi"),
    ("arc", "Arc"),
    ("imported", "Unknown Chromium Browser"),
]

FIREFOX_BROWSER_OPTIONS: list[tuple[str, str]] = [
    ("firefox", "Firefox"),
    ("librewolf", "LibreWolf"),
    ("floorp", "Floorp"),
    ("waterfox", "Waterfox"),
    ("imported_fx", "Unknown Firefox Browser"),
]


# ── Data Classes: Preview & Results ───────────────────────────────────────


@dataclass
class SampleRecord:
    """Simplified record for UI preview."""

    url: str
    title: str
    visit_time: int  # Unix seconds timestamp
    visit_count: int


@dataclass
class ImportPreview:
    """Preview metadata for import, used for UI display."""

    db_type: DbType
    total_records: int
    min_visit_time: int  # Unix seconds, 0 means unknown
    max_visit_time: int  # Unix seconds, 0 means unknown
    sample_records: list[SampleRecord] = field(default_factory=list)
    error: str = ""  # Non-empty indicates preview failure

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class ImportResult:
    """Result of the import operation."""

    inserted: int = 0
    skipped: int = 0
    total: int = 0
    elapsed_sec: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# ── Core Service Class ───────────────────────────────────────────────


class DatabaseImporter:
    """
    Standalone database importer.

    Usage (call from QThread outside UI thread):
        importer = DatabaseImporter(local_db)
        db_type = importer.detect_db_type(path)
        preview = importer.preview_import(path, db_type)
        result  = importer.run_import(path, db_type, browser_type, profile_name)
    """

    SAMPLE_SIZE = 5  # Number of sample records to display in preview

    def __init__(self, local_db: LocalDatabase):
        self._local_db = local_db

    # ── 1. Type Detection ───────────────────────────────────────────

    def detect_db_type(self, path: Path) -> DbType:
        """
        Auto-detect database type by querying SQLite table structure.
        Does not depend on filename, making it robust against user-renamed files.

        Priority:
          Firefox > Safari > HistorySync > Chromium > UNKNOWN
        (Chromium's urls table is the most generic, hence placed last)
        """
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            tables: set[str] = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

            # Further verify HistorySync characteristic columns
            has_browser_type_col = False
            if "history" in tables:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(history)")}
                has_browser_type_col = "browser_type" in cols
            conn.close()
        except sqlite3.DatabaseError as exc:
            log.warning("detect_db_type: cannot open %s: %s", path, exc)
            return DbType.UNKNOWN
        except Exception as exc:
            log.warning("detect_db_type: unexpected error for %s: %s", path, exc)
            return DbType.UNKNOWN

        # Firefox: moz_places is the unique characteristic
        if "moz_places" in tables:
            return DbType.FIREFOX

        # Safari: history_visits + history_items tables
        if "history_visits" in tables and "history_items" in tables:
            return DbType.SAFARI

        # HistorySync: history table with browser_type column
        if "history" in tables and has_browser_type_col:
            return DbType.HISTORYSYNC

        # Edge WebAssistDatabase: navigation_history table
        if "navigation_history" in tables:
            return DbType.WEBASSIST

        # Chromium: urls table
        if "urls" in tables:
            return DbType.CHROMIUM

        return DbType.UNKNOWN

    # ── 2. Preview ───────────────────────────────────────────────

    def preview_import(
        self,
        path: Path,
        db_type: DbType,
        browser_type: str = "imported",
        profile_name: str = "imported",
    ) -> ImportPreview:
        """
        Read target database metadata for UI display.
        Does not modify the local database.
        """
        if db_type == DbType.UNKNOWN:
            return ImportPreview(
                db_type=db_type,
                total_records=0,
                min_visit_time=0,
                max_visit_time=0,
                error="Unknown database format. Cannot preview.",
            )

        try:
            with open_db_snapshot(path, str(path.name)) as conn:
                if db_type == DbType.CHROMIUM:
                    return self._preview_chromium(conn, db_type)
                if db_type == DbType.FIREFOX:
                    return self._preview_firefox(conn, db_type)
                if db_type == DbType.SAFARI:
                    return self._preview_safari(conn, db_type)
                if db_type == DbType.HISTORYSYNC:
                    return self._preview_historysync(conn, db_type)
                if db_type == DbType.WEBASSIST:
                    return self._preview_webassist(conn, db_type)
                return ImportPreview(
                    db_type=db_type,
                    total_records=0,
                    min_visit_time=0,
                    max_visit_time=0,
                    error="Unsupported database type.",
                )
        except Exception as exc:
            log.warning("preview_import failed for %s: %s", path, exc)
            return ImportPreview(
                db_type=db_type,
                total_records=0,
                min_visit_time=0,
                max_visit_time=0,
                error=str(exc),
            )

    def _preview_chromium(self, conn: sqlite3.Connection, db_type: DbType) -> ImportPreview:
        row = conn.execute(
            "SELECT COUNT(*), MIN(last_visit_time), MAX(last_visit_time) FROM urls "
            "WHERE last_visit_time > 0 AND url IS NOT NULL"
        ).fetchone()
        total = row[0] or 0
        min_t = chromium_time_to_unix(row[1] or 0)
        max_t = chromium_time_to_unix(row[2] or 0)

        samples_raw = conn.execute(
            "SELECT url, title, last_visit_time, visit_count FROM urls "
            "WHERE last_visit_time > 0 ORDER BY last_visit_time DESC LIMIT ?",
            (self.SAMPLE_SIZE,),
        ).fetchall()
        samples = [
            SampleRecord(
                url=r[0] or "",
                title=r[1] or "",
                visit_time=chromium_time_to_unix(r[2] or 0),
                visit_count=r[3] or 1,
            )
            for r in samples_raw
        ]
        return ImportPreview(
            db_type=db_type,
            total_records=total,
            min_visit_time=min_t,
            max_visit_time=max_t,
            sample_records=samples,
        )

    def _preview_firefox(self, conn: sqlite3.Connection, db_type: DbType) -> ImportPreview:
        _FACTOR = 1_000_000
        row = conn.execute(
            "SELECT COUNT(*), MIN(last_visit_date), MAX(last_visit_date) FROM moz_places "
            "WHERE last_visit_date IS NOT NULL AND hidden = 0 AND url IS NOT NULL"
        ).fetchone()
        total = row[0] or 0
        min_t = int((row[1] or 0) // _FACTOR)
        max_t = int((row[2] or 0) // _FACTOR)

        samples_raw = conn.execute(
            "SELECT url, title, last_visit_date, visit_count FROM moz_places "
            "WHERE last_visit_date IS NOT NULL AND hidden = 0 "
            "ORDER BY last_visit_date DESC LIMIT ?",
            (self.SAMPLE_SIZE,),
        ).fetchall()
        samples = [
            SampleRecord(
                url=r[0] or "",
                title=r[1] or "",
                visit_time=int((r[2] or 0) // _FACTOR),
                visit_count=r[3] or 1,
            )
            for r in samples_raw
        ]
        return ImportPreview(
            db_type=db_type,
            total_records=total,
            min_visit_time=min_t,
            max_visit_time=max_t,
            sample_records=samples,
        )

    def _preview_safari(self, conn: sqlite3.Connection, db_type: DbType) -> ImportPreview:
        _EPOCH = 978307200
        try:
            row = conn.execute(
                "SELECT COUNT(*), MIN(hv.visit_time), MAX(hv.visit_time) "
                "FROM history_visits hv "
                "JOIN history_items hi ON hv.history_item = hi.id "
                "WHERE hv.visit_time IS NOT NULL"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            return ImportPreview(
                db_type=db_type,
                total_records=0,
                min_visit_time=0,
                max_visit_time=0,
                error=str(exc),
            )
        total = row[0] or 0
        min_t = int((row[1] or 0) + _EPOCH)
        max_t = int((row[2] or 0) + _EPOCH)

        samples_raw = conn.execute(
            "SELECT hi.url, hv.title, hv.visit_time FROM history_visits hv "
            "JOIN history_items hi ON hv.history_item = hi.id "
            "WHERE hv.visit_time IS NOT NULL "
            "ORDER BY hv.visit_time DESC LIMIT ?",
            (self.SAMPLE_SIZE,),
        ).fetchall()
        samples = [
            SampleRecord(
                url=r[0] or "",
                title=r[1] or "",
                visit_time=int((r[2] or 0) + _EPOCH),
                visit_count=1,
            )
            for r in samples_raw
        ]
        return ImportPreview(
            db_type=db_type,
            total_records=total,
            min_visit_time=min_t,
            max_visit_time=max_t,
            sample_records=samples,
        )

    def _preview_webassist(self, conn: sqlite3.Connection, db_type: DbType) -> ImportPreview:
        """Edge WebAssistDatabase — navigation_history table, timestamps are direct Unix seconds."""
        try:
            row = conn.execute(
                "SELECT COUNT(*), MIN(last_visited_time), MAX(last_visited_time) "
                "FROM navigation_history WHERE last_visited_time > 0 AND url IS NOT NULL"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            return ImportPreview(
                db_type=db_type,
                total_records=0,
                min_visit_time=0,
                max_visit_time=0,
                error=str(exc),
            )
        total = row[0] or 0
        min_t = row[1] or 0
        max_t = row[2] or 0

        samples_raw = conn.execute(
            "SELECT url, title, last_visited_time, num_visits FROM navigation_history "
            "WHERE last_visited_time > 0 ORDER BY last_visited_time DESC LIMIT ?",
            (self.SAMPLE_SIZE,),
        ).fetchall()
        samples = [
            SampleRecord(
                url=r[0] or "",
                title=r[1] or "",
                visit_time=r[2] or 0,
                visit_count=r[3] or 1,
            )
            for r in samples_raw
        ]
        return ImportPreview(
            db_type=db_type,
            total_records=total,
            min_visit_time=min_t,
            max_visit_time=max_t,
            sample_records=samples,
        )

    def _preview_historysync(self, conn: sqlite3.Connection, db_type: DbType) -> ImportPreview:
        row = conn.execute("SELECT COUNT(*), MIN(visit_time), MAX(visit_time) FROM history").fetchone()
        total = row[0] or 0
        min_t = row[1] or 0
        max_t = row[2] or 0

        samples_raw = conn.execute(
            "SELECT url, title, visit_time, visit_count FROM history ORDER BY visit_time DESC LIMIT ?",
            (self.SAMPLE_SIZE,),
        ).fetchall()
        samples = [
            SampleRecord(
                url=r[0] or "",
                title=r[1] or "",
                visit_time=r[2] or 0,
                visit_count=r[3] or 1,
            )
            for r in samples_raw
        ]
        return ImportPreview(
            db_type=db_type,
            total_records=total,
            min_visit_time=min_t,
            max_visit_time=max_t,
            sample_records=samples,
        )

    # ── 3. Execute Import ───────────────────────────────────────────

    def run_import(
        self,
        path: Path,
        db_type: DbType,
        browser_type: str,
        profile_name: str,
        progress_callback=None,  # Optional[Callable[[int, int], None]]
    ) -> ImportResult:
        """
        Execute the actual import operation.

        Args:
            path:              Source database file path
            db_type:           Detected database type
            browser_type:      browser_type identifier to use when writing records
            profile_name:      profile_name to use when writing records
            progress_callback: Optional progress callback (current: int, total: int)

        Returns:
            ImportResult containing inserted/skipped/total/elapsed metrics
        """
        if db_type == DbType.UNKNOWN:
            return ImportResult(error="Unknown database type, cannot import.")

        t0 = time.monotonic()
        log.info(
            "[Importer] Starting import: path=%s type=%s browser=%s profile=%s",
            path,
            db_type,
            browser_type,
            profile_name,
        )

        try:
            records = self._extract_records(path, db_type, browser_type, profile_name)
        except Exception as exc:
            log.error("[Importer] Extraction failed: %s", exc, exc_info=True)
            return ImportResult(error=f"Extraction failed: {exc}")

        total = len(records)
        if total == 0:
            return ImportResult(total=0, elapsed_sec=time.monotonic() - t0)

        if progress_callback:
            progress_callback(0, total)

        try:
            inserted = self._local_db.upsert_records(records)
        except Exception as exc:
            log.error("[Importer] DB write failed: %s", exc, exc_info=True)
            return ImportResult(error=f"Database write failed: {exc}")

        skipped = total - inserted
        elapsed = time.monotonic() - t0

        # Update backup_stats to record a manual import entry
        try:
            self._local_db.update_backup_stats(browser_type, profile_name, inserted)
        except Exception as exc:
            log.warning("[Importer] Failed to update backup_stats: %s", exc)

        log.info(
            "[Importer] Done: inserted=%d skipped=%d total=%d elapsed=%.2fs",
            inserted,
            skipped,
            total,
            elapsed,
        )

        if progress_callback:
            progress_callback(total, total)

        return ImportResult(
            inserted=inserted,
            skipped=skipped,
            total=total,
            elapsed_sec=elapsed,
        )

    def _extract_records(
        self,
        path: Path,
        db_type: DbType,
        browser_type: str,
        profile_name: str,
    ) -> list[HistoryRecord]:
        """Dispatch to the corresponding extractor based on database type, reusing existing logic."""
        if db_type == DbType.CHROMIUM:
            return self._extract_chromium(path, browser_type, profile_name)
        if db_type == DbType.FIREFOX:
            return self._extract_firefox(path, browser_type, profile_name)
        if db_type == DbType.SAFARI:
            return self._extract_safari(path, profile_name)
        if db_type == DbType.HISTORYSYNC:
            return self._extract_historysync(path, browser_type, profile_name)
        if db_type == DbType.WEBASSIST:
            return self._extract_webassist(path, browser_type, profile_name)
        return []

    def _extract_chromium(self, path: Path, browser_type: str, profile_name: str) -> list[HistoryRecord]:
        defn = make_custom_chromium_def(browser_type, browser_type, path.parent)
        extractor = ChromiumExtractor(defn, custom_db_path=path)
        # _safe_extract takes a snapshot internally, so we call it directly here
        return extractor._safe_extract(profile_name, path, since_unix_time=0)

    def _extract_firefox(self, path: Path, browser_type: str, profile_name: str) -> list[HistoryRecord]:
        defn = BrowserDef(
            browser_type=browser_type,
            display_name=browser_type,
            engine="firefox",
            _data_dirs=(path.parent,),
        )
        extractor = FirefoxExtractor(defn)
        return extractor._safe_extract(profile_name, path, since_unix_time=0)

    def _extract_safari(self, path: Path, profile_name: str) -> list[HistoryRecord]:
        defn = BrowserDef(
            browser_type="safari",
            display_name="Safari",
            engine="safari",
            _data_dirs=(path.parent,),
        )
        extractor = SafariExtractor(defn)
        return extractor._safe_extract(profile_name, path, since_unix_time=0)

    def _extract_webassist(self, path: Path, browser_type: str, profile_name: str) -> list[HistoryRecord]:
        """
        Extract records from the navigation_history table of Edge WebAssistDatabase.

        Field Mapping:
          url               -> HistoryRecord.url
          title             -> HistoryRecord.title
          last_visited_time -> HistoryRecord.visit_time (already in Unix seconds)
          num_visits        -> HistoryRecord.visit_count
          metadata          -> HistoryRecord.metadata (search terms/snippets, may be empty)
          locale            -> Appended to metadata (e.g., "zh-cn")
          page_profile      -> Appended to metadata
        """
        from src.models.app_config import DEFAULT_FILTERED_URL_PREFIXES

        records: list[HistoryRecord] = []
        try:
            with open_db_snapshot(path, "WebAssistDatabase") as conn:
                rows = conn.execute(
                    "SELECT url, title, last_visited_time, num_visits, "
                    "metadata, locale, page_profile "
                    "FROM navigation_history "
                    "WHERE last_visited_time > 0 AND url IS NOT NULL"
                ).fetchall()
        except Exception as exc:
            log.error("[Importer] WebAssist extraction failed: %s", exc, exc_info=True)
            raise

        for row in rows:
            url: str = row[0] or ""
            if not url or url.startswith(tuple(DEFAULT_FILTERED_URL_PREFIXES)):
                continue

            # Combine metadata: original metadata + locale + profile
            meta_parts = []
            if row[4]:
                meta_parts.append(row[4])
            if row[5]:
                meta_parts.append(f"locale:{row[5]}")
            if row[6]:
                meta_parts.append(f"profile:{row[6]}")
            metadata = " ".join(meta_parts)

            records.append(
                HistoryRecord(
                    url=url,
                    title=row[1] or "",
                    visit_time=int(row[2]),
                    visit_count=int(row[3]) if row[3] else 1,
                    browser_type=browser_type,
                    profile_name=profile_name,
                    metadata=metadata,
                )
            )

        log.info("[Importer] WebAssist extracted %d records from %s", len(records), path.name)
        return records

    def _extract_historysync(
        self,
        path: Path,
        target_browser_type: str,
        target_profile_name: str,
    ) -> list[HistoryRecord]:
        """
        Import from HistorySync's own history.db.
        If target_browser_type or target_profile_name is empty, retain original values (direct merge).
        """
        records: list[HistoryRecord] = []
        try:
            with open_db_snapshot(path, "HistorySync-import") as conn:
                # Try to read new fields; fall back to base columns for older backup DBs
                try:
                    rows = conn.execute(
                        "SELECT url, title, visit_time, visit_count, browser_type, profile_name, metadata, "
                        "typed_count, first_visit_time, transition_type, visit_duration FROM history"
                    ).fetchall()
                    has_new_fields = True
                except sqlite3.OperationalError:
                    rows = conn.execute(
                        "SELECT url, title, visit_time, visit_count, browser_type, profile_name, metadata FROM history"
                    ).fetchall()
                    has_new_fields = False
            for row in rows:
                bt = target_browser_type if target_browser_type else (row[4] or "imported")
                pn = target_profile_name if target_profile_name else (row[5] or "imported")
                records.append(
                    HistoryRecord(
                        url=row[0] or "",
                        title=row[1] or "",
                        visit_time=row[2] or 0,
                        visit_count=row[3] or 1,
                        browser_type=bt,
                        profile_name=pn,
                        metadata=row[6] or "",
                        typed_count=row[7] if has_new_fields else None,
                        first_visit_time=row[8] if has_new_fields else None,
                        transition_type=row[9] if has_new_fields else None,
                        visit_duration=row[10] if has_new_fields else None,
                    )
                )
        except Exception as exc:
            log.error("[Importer] HistorySync extraction failed: %s", exc, exc_info=True)
            raise
        return records

    # ── Utility Methods ───────────────────────────────────────────────

    @staticmethod
    def guess_profile_name(path: Path) -> str:
        """
        Infer profile_name from the file path.

        Rules:
          - If the parent directory is a known Chromium profile name (Default, Profile N), use it directly.
          - If the parent directory contains the "profile" keyword, use it.
          - Otherwise, return an empty string to prompt manual user input.
        """
        parent_name = path.parent.name

        # Standard Chromium profile directory names
        if parent_name.lower() in ("default", "guest profile"):
            return parent_name
        if parent_name.lower().startswith("profile "):
            return parent_name

        # Firefox standard profile directories (e.g., default-release, default-esr)
        if "default" in parent_name.lower():
            return parent_name

        return ""

    @staticmethod
    def guess_browser_type_from_path(path: Path) -> str:
        """
        Guess browser_type based on directory name keywords in the file path.
        This serves as a pre-selection suggestion and can be overridden by the user.
        """
        path_lower = str(path).lower()
        mapping = {
            "chrome": "chrome",
            "google/chrome": "chrome",
            "edge": "edge",
            "microsoft edge": "edge",
            "brave-browser-nightly": "brave_nightly",
            "brave-browser-beta": "brave_beta",
            "brave-browser-dev": "brave_dev",
            "brave": "brave",
            "chromium": "chromium",
            "opera": "opera",
            "vivaldi": "vivaldi",
            "arc": "arc",
            "firefox": "firefox",
            "librewolf": "librewolf",
            "floorp": "floorp",
            "waterfox": "waterfox",
        }
        for keyword, bt in mapping.items():
            if keyword in path_lower:
                return bt
        return ""
