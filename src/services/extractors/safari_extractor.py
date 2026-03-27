# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

from src.models.history_record import HistoryRecord
from src.services.extractors.base_extractor import BaseExtractor
from src.utils.logger import get_logger

log = get_logger("extractor.safari")

# CoreData epoch: seconds between Unix 1970-01-01 and Apple 2001-01-01
_COREDATA_EPOCH = 978307200


class SafariExtractor(BaseExtractor):
    """
    Safari History.db extractor (macOS only).
    Safari stores history in ~/Library/Safari/History.db.
    Table layout: history_visits JOIN history_items.
    visit_time is a CoreData timestamp (seconds since 2001-01-01).
    """

    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        # Convert since_unix_time back to CoreData timestamp for the WHERE clause
        since_cd = since_unix_time - _COREDATA_EPOCH if since_unix_time > _COREDATA_EPOCH else 0

        try:
            rows = conn.execute(
                """
                SELECT
                    hi.url,
                    hv.title,
                    MAX(hv.visit_time)  AS last_visit_time,
                    MIN(hv.visit_time)  AS first_visit_time_cd,
                    COUNT(*)            AS visit_count
                FROM history_visits hv
                JOIN history_items hi ON hv.history_item = hi.id
                WHERE hv.visit_time IS NOT NULL
                  AND hv.visit_time > ?
                GROUP BY hi.url
                ORDER BY last_visit_time DESC
                LIMIT 100000
                """,
                (since_cd,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("[Safari] Query failed: %s", exc)
            return []

        records: list[HistoryRecord] = []
        for row in rows:
            url = row["url"] or ""
            if not url or url.startswith("about:"):
                continue
            cd_ts = row["last_visit_time"] or 0
            unix_ts = int(cd_ts + _COREDATA_EPOCH)

            first_cd = row["first_visit_time_cd"]
            first_unix: int | None = int(first_cd + _COREDATA_EPOCH) if first_cd else None

            records.append(
                HistoryRecord(
                    url=url,
                    title=row["title"] or "",
                    visit_time=unix_ts,
                    visit_count=row["visit_count"] or 1,
                    browser_type="safari",
                    profile_name=profile_name,
                    metadata="",
                    typed_count=None,  # Safari does not expose this
                    first_visit_time=first_unix,
                    transition_type=None,  # Safari does not expose detailed transition
                    visit_duration=None,  # Safari does not expose this
                )
            )

        log.info("[Safari] Extracted %d records from profile '%s'", len(records), profile_name)
        return records
