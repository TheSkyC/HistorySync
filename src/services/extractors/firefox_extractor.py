# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef
from src.services.extractors.base_extractor import BaseExtractor
from src.utils.logger import get_logger

log = get_logger("extractor.firefox")

# Firefox timestamp: PRTime (microseconds), divide by 1e6 to convert to Unix seconds
_FIREFOX_PRTIME_FACTOR = 1_000_000


def unix_to_firefox_time(unix_sec: int) -> int:
    return unix_sec * _FIREFOX_PRTIME_FACTOR


class FirefoxExtractor(BaseExtractor):
    """
    Firefox history extractor (places.sqlite).

    Extra fields extracted (via JOIN with moz_historyvisits):
      - typed_count      moz_places.typed flag (0/1, indicating if it was ever manually typed)
      - first_visit_time First visit time (MIN(moz_historyvisits.visit_date))
      - transition_type  visit_type of the last visit (1=LINK, 2=TYPED, 3=BOOKMARK, etc.)
      - visit_duration   Always None for Firefox (not tracked)
    """

    def __init__(self, defn: BrowserDef):
        super().__init__(defn)

    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        where_clauses = [
            "p.last_visit_date IS NOT NULL",
            "p.hidden = 0",
            "p.url IS NOT NULL",
        ]
        params: list = []

        if since_unix_time > 0:
            where_clauses.append("p.last_visit_date > ?")
            params.append(unix_to_firefox_time(since_unix_time))

        # Full query: moz_places joined with moz_historyvisits for extra fields.
        # Correlated subquery for last visit_type is faster than GROUP BY on visits
        # for typical Firefox history databases.
        sql = f"""
            SELECT
                p.url,
                p.title,
                p.last_visit_date,
                p.visit_count,
                p.description,
                p.typed,
                MIN(v.visit_date)  AS first_visit_date,
                (
                    SELECT v2.visit_type
                    FROM moz_historyvisits v2
                    WHERE v2.place_id = p.id
                    ORDER BY v2.visit_date DESC
                    LIMIT 1
                )                  AS last_visit_type
            FROM moz_places p
            LEFT JOIN moz_historyvisits v ON v.place_id = p.id
            WHERE {" AND ".join(where_clauses)}
            GROUP BY p.id
        """

        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning(
                "[%s] Firefox full query failed (%s) — retrying with basic query",
                self.display_name,
                exc,
            )
            rows = self._basic_query(conn, where_clauses, params)

        records: list[HistoryRecord] = []
        for row in rows:
            url = row["url"] or "" if hasattr(row, "keys") else row[0] or "" if row else ""

            if not url:
                continue

            if hasattr(row, "keys"):
                title = row["title"] or ""
                last_visit_date = row["last_visit_date"]
                visit_count = row["visit_count"] or 1
                description = row["description"] or ""
                typed_flag = row["typed"]
                first_visit_date = row["first_visit_date"]
                last_visit_type = row["last_visit_type"]
            else:
                title = (row[1] or "") if len(row) > 1 else ""
                last_visit_date = row[2] if len(row) > 2 else 0
                visit_count = (row[3] or 1) if len(row) > 3 else 1
                description = (row[4] or "") if len(row) > 4 else ""
                typed_flag = row[5] if len(row) > 5 else None
                first_visit_date = row[6] if len(row) > 6 else None
                last_visit_type = row[7] if len(row) > 7 else None

            if not last_visit_date:
                continue

            visit_time_unix = int(last_visit_date) // _FIREFOX_PRTIME_FACTOR

            # first_visit_time: convert from Firefox PRTime (µs) to Unix seconds
            first_unix: int | None = None
            if first_visit_date:
                first_unix = int(first_visit_date) // _FIREFOX_PRTIME_FACTOR

            # typed_count: Firefox only stores a 0/1 flag, not a cumulative count.
            # We preserve it as an integer so the field remains consistent with
            # the Chromium typed_count (which is also an integer, just higher).
            typed_count: int | None = int(typed_flag) if typed_flag is not None else None

            records.append(
                HistoryRecord(
                    url=url,
                    title=title,
                    visit_time=visit_time_unix,
                    visit_count=visit_count,
                    browser_type=self.browser_type,
                    profile_name=profile_name,
                    metadata=description,
                    typed_count=typed_count,
                    first_visit_time=first_unix,
                    transition_type=last_visit_type,  # Firefox visit_type (1-based)
                    visit_duration=None,  # Firefox does not expose this
                )
            )

        log.info(
            "[%s] Extracted %d records from profile '%s'",
            self.display_name,
            len(records),
            profile_name,
        )
        return records

    def _basic_query(
        self,
        conn: sqlite3.Connection,
        where_clauses: list[str],
        params: list,
    ) -> list:
        """
        Fallback: query only moz_places without the moz_historyvisits JOIN.
        Used on very old Firefox profile schemas where the join may fail.
        """
        # Rebuild WHERE without table alias (basic query uses no alias)
        plain_clauses = [c.replace("p.", "") for c in where_clauses]
        sql = f"""
            SELECT
                url,
                title,
                last_visit_date,
                visit_count,
                description,
                typed,
                NULL AS first_visit_date,
                NULL AS last_visit_type
            FROM moz_places
            WHERE {" AND ".join(plain_clauses)}
        """
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc2:
            log.warning("[%s] Firefox basic fallback also failed: %s", self.display_name, exc2)
            return []
