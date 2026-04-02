# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import sqlite3

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef, make_custom_chromium_def
from src.services.extractors.base_extractor import BaseExtractor
from src.utils.logger import get_logger

log = get_logger("extractor.chromium")

# Chromium timestamp: Microseconds since 1601-01-01 00:00:00 UTC.
_CHROMIUM_EPOCH_DELTA_US = 11_644_473_600 * 1_000_000

# Filter internal browser URLs (do not record in user history)
_FILTERED_SCHEMES = (
    "chrome://",
    "edge://",
    "brave://",
    "about:",
    "chrome-extension://",
    "data:",
)

# Transition type core mask (low 8 bits)
_TRANSITION_MASK = 0xFF


# ── Timestamp Utilities ───────────────────────────────────────


def chromium_time_to_unix(chromium_us: int) -> int:
    """Converts a Chromium WebKit microsecond timestamp to a 10-digit Unix second timestamp."""
    if chromium_us <= 0:
        return 0
    return max(0, (chromium_us - _CHROMIUM_EPOCH_DELTA_US) // 1_000_000)


def unix_to_chromium_time(unix_sec: int) -> int:
    """Converts a 10-digit Unix second timestamp to a Chromium WebKit microsecond timestamp."""
    if unix_sec <= 0:
        return 0
    return unix_sec * 1_000_000 + _CHROMIUM_EPOCH_DELTA_US


def _is_internal_url(url: str) -> bool:
    return url.startswith(_FILTERED_SCHEMES)


# ── ChromiumExtractor ─────────────────────────────────────────


class ChromiumExtractor(BaseExtractor):
    """
    Generic history extractor for Chromium-based browsers.

    Path-driven by BrowserDef, supports all Chromium engine browsers
    (Chrome, Edge, Brave, and custom paths).

    Use factory methods to create instances:
        extractor = ChromiumExtractor.from_def(defn)
        custom    = ChromiumExtractor.for_custom_path("myBrowser", "My Browser", db_path)
    """

    def __init__(self, defn: BrowserDef, custom_db_path: Path | None = None):
        super().__init__(defn, custom_db_path)

    @classmethod
    def for_custom_path(
        cls,
        browser_type: str,
        display_name: str,
        db_path: Path,
    ) -> ChromiumExtractor:
        """
        Creates an extractor for a Chromium browser with a manually specified path.

        Args:
            browser_type: Custom browser identifier.
            display_name: UI display name.
            db_path:      Direct path to the History database file.
        """
        defn = make_custom_chromium_def(browser_type, display_name, db_path.parent)
        return cls(defn, custom_db_path=db_path)

    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        """
        Extracts records from the Chromium History database.

        Incremental mode: Converts since_unix_time back to Chromium microseconds
        and reads only new records via WHERE last_visit_time > ?.

        Extra fields extracted (via JOIN with visits table):
          - typed_count      Number of times the URL was manually typed (urls.typed_count)
          - first_visit_time First visit time (MIN(visits.visit_time))
          - transition_type  Transition type of the last visit, low 8 bits (visits.transition & 0xFF)
          - visit_duration   Duration of the last visit in seconds (visits.visit_duration / 1e6)
        """
        where_clauses = [
            "u.url IS NOT NULL",
            "u.last_visit_time > 0",
        ]
        params: list = []

        if since_unix_time > 0:
            chromium_since = unix_to_chromium_time(since_unix_time)
            where_clauses.append("u.last_visit_time > ?")
            params.append(chromium_since)

        # Full query: urls joined with visits for aggregated extra fields.
        # Correlated subqueries for last transition + last duration are
        # faster than a GROUP BY on the huge visits table for typical history DBs.
        sql = f"""
            SELECT
                u.url,
                u.title,
                u.last_visit_time,
                u.visit_count,
                u.typed_count,
                MIN(v.visit_time)                       AS first_visit_time_cr,
                (
                    SELECT v2.transition & {_TRANSITION_MASK}
                    FROM visits v2
                    WHERE v2.url = u.id
                    ORDER BY v2.visit_time DESC
                    LIMIT 1
                )                                       AS last_transition,
                (
                    SELECT v3.visit_duration / 1000000.0
                    FROM visits v3
                    WHERE v3.url = u.id
                    ORDER BY v3.visit_time DESC
                    LIMIT 1
                )                                       AS last_visit_duration
            FROM urls u
            LEFT JOIN visits v ON v.url = u.id
            WHERE {" AND ".join(where_clauses)}
            GROUP BY u.id
        """

        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning(
                "[%s] Chromium full query failed (%s) — retrying with basic query",
                self.display_name,
                exc,
            )
            rows = self._basic_query(conn, where_clauses, params)

        records: list[HistoryRecord] = []
        for row in rows:
            url: str = row["url"] if hasattr(row, "keys") else row[0]
            url = url or ""
            if not url or _is_internal_url(url):
                continue

            if hasattr(row, "keys"):
                title = row["title"] or ""
                last_visit = row["last_visit_time"]
                visit_count = row["visit_count"] or 1
                typed_count = row["typed_count"]
                first_cr = row["first_visit_time_cr"]
                last_transition = row["last_transition"]
                last_duration = row["last_visit_duration"]
            else:
                title = (row[1] or "") if len(row) > 1 else ""
                last_visit = row[2] if len(row) > 2 else 0
                visit_count = (row[3] or 1) if len(row) > 3 else 1
                typed_count = row[4] if len(row) > 4 else None
                first_cr = row[5] if len(row) > 5 else None
                last_transition = row[6] if len(row) > 6 else None
                last_duration = row[7] if len(row) > 7 else None

            first_unix: int | None = chromium_time_to_unix(first_cr) if first_cr else None

            records.append(
                HistoryRecord(
                    url=url,
                    title=title,
                    visit_time=chromium_time_to_unix(last_visit),
                    visit_count=visit_count,
                    browser_type=self.browser_type,
                    profile_name=profile_name,
                    metadata="",
                    typed_count=typed_count,
                    first_visit_time=first_unix,
                    transition_type=last_transition,
                    visit_duration=last_duration,
                )
            )

        log.info("[%s] Extracted %d records from profile '%s'", self.display_name, len(records), profile_name)
        return records

    def _basic_query(
        self,
        conn: sqlite3.Connection,
        where_clauses: list[str],
        params: list,
    ) -> list:
        """Fallback: query only urls table without the visits JOIN (older schema)."""
        sql = f"""
            SELECT
                u.url,
                u.title,
                u.last_visit_time,
                u.visit_count,
                u.typed_count,
                NULL AS first_visit_time_cr,
                NULL AS last_transition,
                NULL AS last_visit_duration
            FROM urls u
            WHERE {" AND ".join(where_clauses)}
        """
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc2:
            log.warning("[%s] Chromium basic fallback also failed: %s", self.display_name, exc2)
            return []
