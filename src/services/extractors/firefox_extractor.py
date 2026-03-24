# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef
from src.services.extractors.base_extractor import BaseExtractor
from src.utils.logger import get_logger

log = get_logger("extractor.firefox")

# Firefox 时间戳：PRTime（微秒），需除以 1e6 转为 Unix 秒
_FIREFOX_PRTIME_FACTOR = 1_000_000

# 过滤浏览器内部 scheme
_FILTERED_SCHEMES = ("about:", "place:", "moz-extension://", "data:")


def unix_to_firefox_time(unix_sec: int) -> int:
    return unix_sec * _FIREFOX_PRTIME_FACTOR


def _is_internal_url(url: str) -> bool:
    return url.startswith(_FILTERED_SCHEMES)


class FirefoxExtractor(BaseExtractor):
    def __init__(self, defn: BrowserDef):
        super().__init__(defn)

    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        where_clauses = [
            "last_visit_date IS NOT NULL",
            "hidden = 0",
            "url IS NOT NULL",
        ]
        params: list = []

        if since_unix_time > 0:
            where_clauses.append("last_visit_date > ?")
            params.append(unix_to_firefox_time(since_unix_time))

        sql = f"""
            SELECT
                url,
                title,
                last_visit_date,
                visit_count,
                description
            FROM moz_places
            WHERE {" AND ".join(where_clauses)}
        """
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("[%s] Firefox DB query failed: %s", self.display_name, exc)
            return []

        records: list[HistoryRecord] = []
        for row in rows:
            url: str = row["url"] or ""
            if not url or _is_internal_url(url):
                continue
            records.append(
                HistoryRecord(
                    url=url,
                    title=row["title"] or "",
                    visit_time=int(row["last_visit_date"]) // _FIREFOX_PRTIME_FACTOR,
                    visit_count=row["visit_count"] or 1,
                    browser_type=self.browser_type,
                    profile_name=profile_name,
                    metadata=row["description"] or "",
                )
            )
        return records
