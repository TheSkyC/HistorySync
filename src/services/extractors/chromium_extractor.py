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

# Chromium 时间戳：从 1601-01-01 00:00:00 UTC 起的微秒数
_CHROMIUM_EPOCH_DELTA_US = 11_644_473_600 * 1_000_000

# 过滤浏览器内部 URL（不记入用户历史）
_FILTERED_SCHEMES = (
    "chrome://",
    "edge://",
    "brave://",
    "about:",
    "chrome-extension://",
    "data:",
)


# ── 时间戳工具 ────────────────────────────────────────────────


def chromium_time_to_unix(chromium_us: int) -> int:
    """将 Chromium WebKit 微秒时间戳转换为 10 位 Unix 秒时间戳。"""
    if chromium_us <= 0:
        return 0
    return max(0, (chromium_us - _CHROMIUM_EPOCH_DELTA_US) // 1_000_000)


def unix_to_chromium_time(unix_sec: int) -> int:
    """将 10 位 Unix 秒时间戳转换为 Chromium WebKit 微秒时间戳。"""
    if unix_sec <= 0:
        return 0
    return unix_sec * 1_000_000 + _CHROMIUM_EPOCH_DELTA_US


def _is_internal_url(url: str) -> bool:
    return url.startswith(_FILTERED_SCHEMES)


# ── ChromiumExtractor ─────────────────────────────────────────


class ChromiumExtractor(BaseExtractor):
    """
    Chromium 通用历史记录提取器。

    由 BrowserDef 驱动路径，支持所有 Chromium 内核浏览器
    （Chrome、Edge、Brave 以及用户自定义路径的浏览器）。

    使用工厂函数创建实例：
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
        为用户手动指定路径的 Chromium 浏览器创建提取器。

        Args:
            browser_type: 自定义浏览器标识符。
            display_name: UI 展示名。
            db_path:      直接指向 History 数据库文件的路径。
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
        从 Chromium History 数据库提取记录。

        增量模式：将 since_unix_time 转换回 Chromium 微秒时间戳，
        通过 WHERE last_visit_time > ? 只读取新记录。
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

        sql = f"""
            SELECT
                u.url,
                u.title,
                u.last_visit_time,
                u.visit_count
            FROM urls u
            WHERE {" AND ".join(where_clauses)}
        """
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("[%s] Chromium DB query failed: %s", self.display_name, exc)
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
                    visit_time=chromium_time_to_unix(row["last_visit_time"]),
                    visit_count=row["visit_count"] or 1,
                    browser_type=self.browser_type,
                    profile_name=profile_name,
                    metadata="",
                )
            )
        return records
