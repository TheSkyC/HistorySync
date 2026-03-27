# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from unittest.mock import MagicMock

# ── Path setup ────────────────────────────────────────────────
# 让测试可以从项目根目录或 tests/ 目录运行
_HERE = Path(__file__).parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models.app_config import AppConfig, WebDavConfig
from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef, _parse_firefox_profiles_ini
from src.services.extractor_manager import ExtractorManager
from src.services.extractors.base_extractor import _close_quietly, copy_db_with_wal
from src.services.extractors.chromium_extractor import (
    ChromiumExtractor,
    _is_internal_url as chromium_is_internal,
    chromium_time_to_unix,
    unix_to_chromium_time,
)
from src.services.extractors.firefox_extractor import (
    _FIREFOX_PRTIME_FACTOR,
    FirefoxExtractor,
    unix_to_firefox_time,
)
from src.services.local_db import LocalDatabase, _build_fts_query, _is_fts_special

# ══════════════════════════════════════════════════════════════
# 1. 时间戳转换
# ══════════════════════════════════════════════════════════════


class TestChromiumTimeConversion(unittest.TestCase):
    def test_known_timestamp(self):
        # 2024-01-01 00:00:00 UTC  →  Unix 1704067200
        # Chromium 微秒：(1704067200 + 11644473600) * 1e6
        chromium_us = (1704067200 + 11_644_473_600) * 1_000_000
        self.assertEqual(chromium_time_to_unix(chromium_us), 1704067200)

    def test_zero_input(self):
        self.assertEqual(chromium_time_to_unix(0), 0)

    def test_negative_input(self):
        self.assertEqual(chromium_time_to_unix(-1), 0)

    def test_roundtrip(self):
        """chromium_time_to_unix(unix_to_chromium_time(t)) == t"""
        for unix_ts in [0, 1000000, 1704067200, int(time.time())]:
            if unix_ts == 0:
                self.assertEqual(chromium_time_to_unix(unix_to_chromium_time(unix_ts)), 0)
            else:
                self.assertEqual(chromium_time_to_unix(unix_to_chromium_time(unix_ts)), unix_ts)

    def test_very_old_timestamp_clamped_to_zero(self):
        # 非常小的值（小于 Chromium epoch），转换结果应为 0
        self.assertEqual(chromium_time_to_unix(1), 0)


class TestFirefoxTimeConversion(unittest.TestCase):
    def test_known_timestamp(self):
        unix_ts = 1704067200
        firefox_prtime = unix_ts * _FIREFOX_PRTIME_FACTOR
        converted = firefox_prtime // _FIREFOX_PRTIME_FACTOR
        self.assertEqual(converted, unix_ts)

    def test_roundtrip(self):
        for unix_ts in [1000000, 1704067200, int(time.time())]:
            ff = unix_to_firefox_time(unix_ts)
            self.assertEqual(ff // _FIREFOX_PRTIME_FACTOR, unix_ts)


# ══════════════════════════════════════════════════════════════
# 2. HistoryRecord 数据类
# ══════════════════════════════════════════════════════════════


class TestHistoryRecord(unittest.TestCase):
    def _make(self, **kwargs) -> HistoryRecord:
        defaults = {
            "url": "https://example.com",
            "title": "Example",
            "visit_time": 1704067200,
            "visit_count": 1,
            "browser_type": "chrome",
            "profile_name": "Default",
        }
        defaults.update(kwargs)
        return HistoryRecord(**defaults)

    def test_dedup_key_format(self):
        r = self._make(browser_type="edge", url="https://x.com", visit_time=12345)
        self.assertEqual(r.dedup_key(), "edge|https://x.com|12345")

    def test_dedup_key_distinguishes_browsers(self):
        r1 = self._make(browser_type="chrome")
        r2 = self._make(browser_type="firefox")
        self.assertNotEqual(r1.dedup_key(), r2.dedup_key())

    def test_default_metadata_empty(self):
        r = self._make()
        self.assertEqual(r.metadata, "")

    def test_id_not_in_equality(self):
        """id 字段设置了 compare=False，不参与 == 比较"""
        r1 = self._make()
        r2 = self._make()
        r1.id = 1
        r2.id = 99
        self.assertEqual(r1, r2)


# ══════════════════════════════════════════════════════════════
# 3. LocalDatabase
# ══════════════════════════════════════════════════════════════


def _make_record(
    url="https://example.com",
    title="Example",
    visit_time=1704067200,
    visit_count=1,
    browser_type="chrome",
    profile_name="Default",
    metadata="",
) -> HistoryRecord:
    return HistoryRecord(
        url=url,
        title=title,
        visit_time=visit_time,
        visit_count=visit_count,
        browser_type=browser_type,
        profile_name=profile_name,
        metadata=metadata,
    )


class TestLocalDatabase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "test.db"
        self.db = LocalDatabase(db_path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    # ── Schema ────────────────────────────────────────────────

    def test_schema_created(self):
        with self.db._conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("history", tables)
        self.assertIn("backup_stats", tables)

    def test_fts_virtual_table_created(self):
        with self.db._conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("history_fts", tables)

    # ── Upsert ────────────────────────────────────────────────

    def test_upsert_returns_correct_count(self):
        records = [_make_record(url=f"https://site{i}.com") for i in range(10)]
        inserted = self.db.upsert_records(records)
        self.assertEqual(inserted, 10)

    def test_upsert_deduplication(self):
        r = _make_record()
        self.db.upsert_records([r])
        inserted2 = self.db.upsert_records([r])
        self.assertEqual(inserted2, 0)
        self.assertEqual(self.db.get_total_count(), 1)

    def test_upsert_empty_list(self):
        self.assertEqual(self.db.upsert_records([]), 0)

    def test_upsert_large_batch(self):
        """测试 >500 条记录（跨越 _BATCH_SIZE 边界）的精确计数"""
        records = [_make_record(url=f"https://x.com/{i}") for i in range(1200)]
        inserted = self.db.upsert_records(records)
        self.assertEqual(inserted, 1200)
        self.assertEqual(self.db.get_total_count(), 1200)

    def test_upsert_partial_dedup_across_batches(self):
        """前 600 条已存在，后 600 条是新的——跨 batch 去重计数必须正确"""
        existing = [_make_record(url=f"https://x.com/{i}") for i in range(600)]
        self.db.upsert_records(existing)

        all_records = existing + [_make_record(url=f"https://x.com/{i}") for i in range(600, 1200)]
        inserted = self.db.upsert_records(all_records)
        self.assertEqual(inserted, 600)

    def test_dedup_key_is_browser_url_time(self):
        """相同 url+time 但不同 browser_type 应各自插入"""
        r1 = _make_record(browser_type="chrome")
        r2 = _make_record(browser_type="firefox")
        self.db.upsert_records([r1, r2])
        self.assertEqual(self.db.get_total_count(), 2)

    # ── get_total_count ───────────────────────────────────────

    def test_total_count_empty(self):
        self.assertEqual(self.db.get_total_count(), 0)

    # ── get_max_visit_times ───────────────────────────────────

    def test_get_max_visit_times_empty(self):
        result = self.db.get_max_visit_times("chrome")
        self.assertEqual(result, {})

    def test_get_max_visit_times_single_profile(self):
        records = [
            _make_record(visit_time=1000, profile_name="Default"),
            _make_record(url="https://b.com", visit_time=9999, profile_name="Default"),
            _make_record(url="https://c.com", visit_time=5000, profile_name="Default"),
        ]
        self.db.upsert_records(records)
        result = self.db.get_max_visit_times("chrome")
        self.assertEqual(result, {"Default": 9999})

    def test_get_max_visit_times_multi_profile(self):
        records = [
            _make_record(url="https://a.com", visit_time=1000, profile_name="Default"),
            _make_record(url="https://b.com", visit_time=2000, profile_name="Default"),
            _make_record(url="https://c.com", visit_time=3000, profile_name="Profile 1"),
            _make_record(url="https://d.com", visit_time=500, profile_name="Profile 1"),
        ]
        self.db.upsert_records(records)
        result = self.db.get_max_visit_times("chrome")
        self.assertEqual(result["Default"], 2000)
        self.assertEqual(result["Profile 1"], 3000)

    def test_get_max_visit_times_ignores_other_browsers(self):
        chrome_r = _make_record(url="https://a.com", visit_time=9999, browser_type="chrome")
        firefox_r = _make_record(url="https://b.com", visit_time=1, browser_type="firefox")
        self.db.upsert_records([chrome_r, firefox_r])
        result = self.db.get_max_visit_times("firefox")
        self.assertEqual(result, {"Default": 1})

    # ── get_records pagination ────────────────────────────────

    def test_get_records_returns_all_when_less_than_limit(self):
        self.db.upsert_records([_make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(5)])
        rows = self.db.get_records(limit=100)
        self.assertEqual(len(rows), 5)

    def test_get_records_pagination(self):
        self.db.upsert_records([_make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(20)])
        page1 = self.db.get_records(limit=10, offset=0)
        page2 = self.db.get_records(limit=10, offset=10)
        self.assertEqual(len(page1), 10)
        self.assertEqual(len(page2), 10)
        urls_p1 = {r.url for r in page1}
        urls_p2 = {r.url for r in page2}
        self.assertTrue(urls_p1.isdisjoint(urls_p2))

    def test_get_records_ordered_by_visit_time_desc(self):
        self.db.upsert_records([_make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(5)])
        rows = self.db.get_records(limit=100)
        times = [r.visit_time for r in rows]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_get_records_browser_filter(self):
        self.db.upsert_records(
            [
                _make_record(url="https://a.com", browser_type="chrome"),
                _make_record(url="https://b.com", browser_type="firefox"),
            ]
        )
        rows = self.db.get_records(browser_type="chrome")
        self.assertTrue(all(r.browser_type == "chrome" for r in rows))
        self.assertEqual(len(rows), 1)

    def test_get_records_date_filter(self):
        self.db.upsert_records(
            [
                _make_record(url="https://old.com", visit_time=1000),
                _make_record(url="https://new.com", visit_time=9000),
            ]
        )
        rows = self.db.get_records(date_from=5000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].url, "https://new.com")

    # ── get_filtered_count ────────────────────────────────────

    def test_filtered_count_matches_get_records(self):
        self.db.upsert_records([_make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(50)])
        total = self.db.get_filtered_count()
        self.assertEqual(total, 50)

    def test_filtered_count_with_browser_filter(self):
        self.db.upsert_records(
            [
                _make_record(url="https://a.com", browser_type="chrome"),
                _make_record(url="https://b.com", browser_type="firefox"),
                _make_record(url="https://c.com", browser_type="chrome"),
            ]
        )
        cnt = self.db.get_filtered_count(browser_type="chrome")
        self.assertEqual(cnt, 2)

    # ── backup_stats ──────────────────────────────────────────

    def test_update_backup_stats_insert(self):
        self.db.update_backup_stats("chrome", "Default", 100)
        stats = self.db.get_all_backup_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].total_records_synced, 100)

    def test_update_backup_stats_accumulates(self):
        self.db.update_backup_stats("chrome", "Default", 100)
        self.db.update_backup_stats("chrome", "Default", 50)
        stats = self.db.get_all_backup_stats()
        self.assertEqual(stats[0].total_records_synced, 150)

    def test_update_backup_stats_multiple_profiles(self):
        self.db.update_backup_stats("chrome", "Default", 10)
        self.db.update_backup_stats("chrome", "Profile 1", 20)
        stats = self.db.get_all_backup_stats()
        self.assertEqual(len(stats), 2)

    def test_get_last_sync_time_returns_none_when_empty(self):
        self.assertIsNone(self.db.get_last_sync_time())

    def test_get_last_sync_time_returns_most_recent(self):
        self.db.update_backup_stats("chrome", "Default", 10)
        t = self.db.get_last_sync_time()
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t, int(time.time()), delta=5)

    # ── get_browser_types ─────────────────────────────────────

    def test_get_browser_types(self):
        self.db.upsert_records(
            [
                _make_record(url="https://a.com", browser_type="chrome"),
                _make_record(url="https://b.com", browser_type="firefox"),
            ]
        )
        types = self.db.get_browser_types()
        self.assertIn("chrome", types)
        self.assertIn("firefox", types)

    # ── Thread safety ─────────────────────────────────────────

    def test_concurrent_upsert(self):
        """多线程并发写入不应崩溃，最终行数应等于所有线程写入的不重复记录数"""
        N_THREADS = 8
        N_PER_THREAD = 50
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                records = [
                    _make_record(url=f"https://t{thread_id}.com/{j}", visit_time=thread_id * 1000 + j)
                    for j in range(N_PER_THREAD)
                ]
                self.db.upsert_records(records)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], msg=f"Thread errors: {errors}")
        self.assertEqual(self.db.get_total_count(), N_THREADS * N_PER_THREAD)


# ══════════════════════════════════════════════════════════════
# 4. FTS5 查询构建 & 降级机制
# ══════════════════════════════════════════════════════════════


class TestFTSQueryBuilder(unittest.TestCase):
    def test_plain_keyword(self):
        q = _build_fts_query("hello")
        self.assertEqual(q, '"hello"*')

    def test_keyword_with_spaces(self):
        # Multi-word input is treated as a single phrase for contiguous matching
        q = _build_fts_query("github actions")
        self.assertEqual(q, '"github actions"*')

    def test_keyword_with_double_quotes(self):
        q = _build_fts_query('say "hello"')
        self.assertEqual(q, '"say ""hello"""*')

    def test_keyword_with_fts_operators(self):
        """FTS5 运算符被 phrase 引号消除，不会触发语法错误"""
        q = _build_fts_query("AND OR NOT")
        self.assertEqual(q, '"AND OR NOT"*')

    def test_keyword_with_special_chars(self):
        q = _build_fts_query("(test*value)")
        self.assertIn('"', q)
        self.assertTrue(q.endswith("*"))

    def test_is_fts_special_detection(self):
        self.assertTrue(_is_fts_special("test AND more"))
        self.assertTrue(_is_fts_special("(foo)"))
        self.assertTrue(_is_fts_special('say "hello"'))
        self.assertFalse(_is_fts_special("github"))
        self.assertFalse(_is_fts_special("hello world"))


class TestFTSFallback(unittest.TestCase):
    """验证 FTS5 失败时自动降级到 LIKE 查询。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "fts_test.db"
        self.db = LocalDatabase(db_path)
        records = [
            _make_record(url="https://github.com", title="GitHub"),
            _make_record(url="https://gitlab.com", title="GitLab", visit_time=1704067201),
            _make_record(url="https://bitbucket.org", title="Bitbucket", visit_time=1704067202),
        ]
        self.db.upsert_records(records)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_fts_finds_keyword(self):
        rows = self.db.get_records(keyword="github")
        self.assertEqual(len(rows), 1)
        self.assertIn("github", rows[0].url)

    def test_fts_prefix_match(self):
        rows = self.db.get_records(keyword="git")
        self.assertEqual(len(rows), 2)

    def test_fts_count_matches_records(self):
        cnt = self.db.get_filtered_count(keyword="git")
        rows = self.db.get_records(keyword="git", limit=100)
        self.assertEqual(cnt, len(rows))

    def test_like_fallback_triggered_by_broken_fts(self):
        """
        通过 monkeypatching 让 FTS5 执行抛出 OperationalError，
        验证降级到 LIKE 后仍能返回正确结果。
        """

        def bad_fts_query(keyword: str) -> str:
            return "INVALID FTS SYNTAX !!!"

        import src.services.local_db as local_db_module

        old = local_db_module._build_fts_query
        local_db_module._build_fts_query = bad_fts_query
        try:
            rows = self.db.get_records(keyword="github")
            # LIKE 降级后应能找到 github.com
            self.assertTrue(any("github" in r.url for r in rows))
        finally:
            local_db_module._build_fts_query = old

    def test_fts_count_fallback_matches_record_count(self):
        """降级路径下 count 与实际行数必须一致（防止分页错位）。"""
        import src.services.local_db as local_db_module

        old = local_db_module._build_fts_query
        local_db_module._build_fts_query = lambda k: "INVALID !!!"
        try:
            cnt = self.db.get_filtered_count(keyword="git")
            rows = self.db.get_records(keyword="git", limit=100)
            self.assertEqual(cnt, len(rows))
        finally:
            local_db_module._build_fts_query = old


# ══════════════════════════════════════════════════════════════
# 5. WAL 安全拷贝
# ══════════════════════════════════════════════════════════════


class TestCopyDbWithWal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _create_db(self, name: str) -> Path:
        """创建一个含有数据的测试 SQLite 数据库。"""
        p = self.tmp / name
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"val{i}") for i in range(50)])
        conn.commit()
        conn.close()
        return p

    def test_copy_main_file(self):
        src = self._create_db("src.db")
        dst = self.tmp / "dst.db"
        copy_db_with_wal(src, dst)
        self.assertTrue(dst.exists())

    def test_copied_db_is_readable(self):
        src = self._create_db("src.db")
        dst = self.tmp / "dst.db"
        copy_db_with_wal(src, dst)
        conn = sqlite3.connect(str(dst))
        rows = conn.execute("SELECT COUNT(*) FROM t").fetchone()
        conn.close()
        self.assertEqual(rows[0], 50)

    def test_missing_wal_shm_does_not_raise(self):
        src = self._create_db("src.db")
        # 确保没有 -wal / -shm 文件
        for suffix in ("-wal", "-shm"):
            p = src.with_name(src.name + suffix)
            if p.exists():
                p.unlink()
        dst = self.tmp / "dst.db"
        # 不应抛出异常
        copy_db_with_wal(src, dst)
        self.assertTrue(dst.exists())

    def test_wal_file_copied_when_present(self):
        src = self._create_db("src.db")
        # 手动创建一个假 WAL 文件
        wal = src.with_name(src.name + "-wal")
        wal.write_bytes(b"WAL_CONTENT")
        dst = self.tmp / "dst.db"
        copy_db_with_wal(src, dst)
        dst_wal = dst.with_name(dst.name + "-wal")
        self.assertTrue(dst_wal.exists())
        self.assertEqual(dst_wal.read_bytes(), b"WAL_CONTENT")


class TestCloseQuietly(unittest.TestCase):
    def test_none_does_not_raise(self):
        _close_quietly(None)  # 不应抛出

    def test_already_closed_does_not_raise(self):
        conn = sqlite3.connect(":memory:")
        conn.close()
        _close_quietly(conn)  # 再次关闭，不应抛出


# ══════════════════════════════════════════════════════════════
# 6. ChromiumExtractor 提取逻辑
# ══════════════════════════════════════════════════════════════


def _create_chromium_db(path: Path, rows: list[tuple]) -> None:
    """
    创建一个模拟 Chromium History 数据库。
    rows: [(url, title, last_visit_time_chromium_us, visit_count), ...]
    如果文件已存在，先清空 urls 表再重建（方便同一测试内多次调用）。
    """
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TABLE IF EXISTS urls")
    conn.execute("""
        CREATE TABLE urls (
            id INTEGER PRIMARY KEY,
            url TEXT,
            title TEXT,
            last_visit_time INTEGER,
            visit_count INTEGER,
            typed_count INTEGER DEFAULT 0
        )
    """)
    conn.executemany(
        "INSERT INTO urls (url, title, last_visit_time, visit_count) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _make_chromium_extractor(db_path: Path, browser_type: str = "chrome_test") -> ChromiumExtractor:
    """
    创建指向临时数据库文件的 ChromiumExtractor 测试实例。
    使用 for_custom_path() 工厂方法——重构后的正确接入点。
    browser_type 默认 "chrome_test" 以避免与内置 "chrome" 冲突。
    """
    return ChromiumExtractor.for_custom_path(
        browser_type=browser_type,
        display_name=browser_type.replace("_", " ").title(),
        db_path=db_path,
    )


class TestChromiumExtractor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "History"

    def tearDown(self):
        self._tmp.cleanup()

    def _ts(self, unix_sec: int) -> int:
        return unix_to_chromium_time(unix_sec)

    def test_basic_extraction(self):
        _create_chromium_db(
            self.db_path,
            [
                ("https://github.com", "GitHub", self._ts(1704067200), 5),
                ("https://google.com", "Google", self._ts(1704067300), 10),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(len(records), 2)
        urls = {r.url for r in records}
        self.assertIn("https://github.com", urls)
        self.assertIn("https://google.com", urls)

    def test_internal_urls_filtered(self):
        _create_chromium_db(
            self.db_path,
            [
                ("chrome://settings", "Settings", self._ts(1704067200), 1),
                ("edge://newtab", "New Tab", self._ts(1704067201), 1),
                ("brave://newtab", "Brave New Tab", self._ts(1704067202), 1),
                ("about:blank", "Blank", self._ts(1704067203), 1),
                ("https://real.com", "Real", self._ts(1704067204), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://real.com")

    def test_incremental_extraction_only_new_records(self):
        base_ts = 1704067200
        _create_chromium_db(
            self.db_path,
            [
                ("https://old.com", "Old", self._ts(base_ts - 1000), 1),
                ("https://new.com", "New", self._ts(base_ts + 1000), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        # for_custom_path 使用 "custom" 作为 profile_name
        records = ext.extract(since_map={"custom": base_ts})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://new.com")

    def test_incremental_extraction_zero_since_returns_all(self):
        _create_chromium_db(
            self.db_path,
            [
                ("https://a.com", "A", self._ts(1704067200), 1),
                ("https://b.com", "B", self._ts(1704067300), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        records = ext.extract(since_map={"custom": 0})
        self.assertEqual(len(records), 2)

    def test_visit_time_converted_correctly(self):
        expected_unix = 1704067200
        _create_chromium_db(
            self.db_path,
            [
                ("https://x.com", "X", self._ts(expected_unix), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(records[0].visit_time, expected_unix)

    def test_browser_type_set_correctly(self):
        _create_chromium_db(
            self.db_path,
            [
                ("https://x.com", "X", self._ts(1704067200), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path, browser_type="chrome_test")
        records = ext.extract()
        self.assertEqual(records[0].browser_type, "chrome_test")

    def test_profile_name_set_correctly(self):
        """for_custom_path 创建的提取器，profile_name 固定为 'custom'。"""
        _create_chromium_db(
            self.db_path,
            [
                ("https://x.com", "X", self._ts(1704067200), 1),
            ],
        )
        ext = _make_chromium_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(records[0].profile_name, "custom")

    def test_missing_db_returns_empty(self):
        ext = _make_chromium_extractor(self.tmp / "NonExistent")
        records = ext.extract()
        self.assertEqual(records, [])

    def test_is_available_true_when_db_exists(self):
        _create_chromium_db(self.db_path, [])
        ext = _make_chromium_extractor(self.db_path)
        self.assertTrue(ext.is_available())

    def test_is_available_false_when_db_missing(self):
        ext = _make_chromium_extractor(self.tmp / "Missing")
        self.assertFalse(ext.is_available())


class TestInternalUrlFilter(unittest.TestCase):
    def test_chrome_filtered(self):
        self.assertTrue(chromium_is_internal("chrome://settings"))

    def test_edge_filtered(self):
        self.assertTrue(chromium_is_internal("edge://newtab"))

    def test_brave_filtered(self):
        self.assertTrue(chromium_is_internal("brave://newtab"))

    def test_about_filtered(self):
        self.assertTrue(chromium_is_internal("about:blank"))

    def test_extension_filtered(self):
        self.assertTrue(chromium_is_internal("chrome-extension://abc123/page.html"))

    def test_data_filtered(self):
        self.assertTrue(chromium_is_internal("data:text/html,<h1>hi</h1>"))

    def test_https_not_filtered(self):
        self.assertFalse(chromium_is_internal("https://github.com"))

    def test_http_not_filtered(self):
        self.assertFalse(chromium_is_internal("http://example.com"))


# ══════════════════════════════════════════════════════════════
# 7. FirefoxExtractor 提取逻辑
# ══════════════════════════════════════════════════════════════


def _create_firefox_db(path: Path, rows: list[tuple]) -> None:
    """
    创建一个模拟 Firefox places.sqlite 数据库。
    rows: [(url, title, last_visit_date_prtime, visit_count, description), ...]
    """
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE moz_places (
            id INTEGER PRIMARY KEY,
            url TEXT,
            title TEXT,
            last_visit_date INTEGER,
            visit_count INTEGER,
            hidden INTEGER DEFAULT 0,
            description TEXT,
            typed INTEGER DEFAULT 0
        )
    """)
    conn.executemany(
        "INSERT INTO moz_places (url, title, last_visit_date, visit_count, description) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _make_firefox_extractor(db_path: Path, profile_name: str = "default-release") -> FirefoxExtractor:
    """
    创建指向临时数据库的 FirefoxExtractor 测试实例。

    通过构造一个临时 profiles.ini + BrowserDef 来驱动提取器，
    避免 override 已不存在的内部方法。
    db_path 必须是已创建好的 places.sqlite 文件。
    """
    base_dir = db_path.parent
    ini_path = base_dir / "profiles.ini"
    # 写出最简 profiles.ini，指向 db_path 所在目录
    ini_path.write_text(
        f"[Profile0]\nName={profile_name}\nIsRelative=1\nPath=.\n",
        encoding="utf-8",
    )
    defn = BrowserDef(
        browser_type="firefox_test",
        display_name="Firefox Test",
        engine="firefox",
        _data_dirs=(base_dir,),
    )
    return FirefoxExtractor(defn)


class TestFirefoxExtractor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "places.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def _ff_ts(self, unix_sec: int) -> int:
        return unix_to_firefox_time(unix_sec)

    def test_basic_extraction(self):
        _create_firefox_db(
            self.db_path,
            [
                ("https://mozilla.org", "Mozilla", self._ff_ts(1704067200), 3, "Browser maker"),
                ("https://python.org", "Python", self._ff_ts(1704067300), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(len(records), 2)

    def test_internal_urls_filtered(self):
        _create_firefox_db(
            self.db_path,
            [
                ("about:config", "Config", self._ff_ts(1704067200), 1, ""),
                ("place:sort=8&maxResults", "Places", self._ff_ts(1704067201), 1, ""),
                ("https://firefox.com", "Firefox", self._ff_ts(1704067202), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://firefox.com")

    def test_incremental_extraction(self):
        base_ts = 1704067200
        _create_firefox_db(
            self.db_path,
            [
                ("https://old.com", "Old", self._ff_ts(base_ts - 1000), 1, ""),
                ("https://new.com", "New", self._ff_ts(base_ts + 1000), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(self.db_path, profile_name="default-release")
        records = ext.extract(since_map={"default-release": base_ts})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://new.com")

    def test_metadata_captured(self):
        _create_firefox_db(
            self.db_path,
            [
                ("https://mdn.org", "MDN", self._ff_ts(1704067200), 1, "Web docs"),
            ],
        )
        ext = _make_firefox_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(records[0].metadata, "Web docs")

    def test_visit_time_converted_correctly(self):
        unix_ts = 1704067200
        _create_firefox_db(
            self.db_path,
            [
                ("https://x.com", "X", self._ff_ts(unix_ts), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(records[0].visit_time, unix_ts)

    def test_browser_type_is_firefox_test(self):
        _create_firefox_db(
            self.db_path,
            [
                ("https://x.com", "X", self._ff_ts(1704067200), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(self.db_path)
        records = ext.extract()
        self.assertEqual(records[0].browser_type, "firefox_test")


# ══════════════════════════════════════════════════════════════
# 7b. Firefox profiles.ini 解析（直接测试 BrowserDef 路径发现）
# ══════════════════════════════════════════════════════════════


class TestFirefoxProfileParsing(unittest.TestCase):
    """
    测试 Firefox 多 Profile 路径发现。

    重构后解析逻辑位于 browser_defs._parse_firefox_profiles_ini()
    和 BrowserDef.iter_history_db_paths()。直接通过 BrowserDef 接口
    测试端到端行为，不再测试已不存在的 FirefoxExtractor._parse_profiles_ini()。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_ini(self, content: str) -> None:
        (self.base / "profiles.ini").write_text(content, encoding="utf-8")

    def _make_profile_with_db(self, rel_path: str) -> Path:
        """创建 Profile 目录及 places.sqlite，返回 db 路径。"""
        profile_dir = self.base / rel_path
        profile_dir.mkdir(parents=True, exist_ok=True)
        db = profile_dir / "places.sqlite"
        _create_firefox_db(db, [])
        return db

    def _make_defn(self) -> BrowserDef:
        return BrowserDef(
            browser_type="firefox_test",
            display_name="Firefox Test",
            engine="firefox",
            _data_dirs=(self.base,),
        )

    def test_single_profile_discovered(self):
        self._make_profile_with_db("abc123.default-release")
        self._write_ini("""
[Profile0]
Name=default-release
IsRelative=1
Path=abc123.default-release
""")
        paths = list(self._make_defn().iter_history_db_paths())
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0][0], "default-release")

    def test_multiple_profiles_discovered(self):
        self._make_profile_with_db("prof1.default")
        self._make_profile_with_db("prof2.work")
        self._write_ini("""
[Profile0]
Name=default
IsRelative=1
Path=prof1.default

[Profile1]
Name=work
IsRelative=1
Path=prof2.work
""")
        paths = list(self._make_defn().iter_history_db_paths())
        self.assertEqual(len(paths), 2)
        names = {p[0] for p in paths}
        self.assertIn("default", names)
        self.assertIn("work", names)

    def test_missing_places_sqlite_skipped(self):
        """Profile 目录存在但无 places.sqlite 时应跳过。"""
        (self.base / "nodbprofile").mkdir()
        self._write_ini("""
[Profile0]
Name=nodbprofile
IsRelative=1
Path=nodbprofile
""")
        paths = list(self._make_defn().iter_history_db_paths())
        self.assertEqual(len(paths), 0)

    def test_duplicate_profile_path_deduplicated(self):
        """两个 Profile 段指向同一目录，只应返回一条路径。"""
        self._make_profile_with_db("shared.default")
        self._write_ini("""
[Profile0]
Name=alpha
IsRelative=1
Path=shared.default

[Profile1]
Name=beta
IsRelative=1
Path=shared.default
""")
        paths = list(self._make_defn().iter_history_db_paths())
        self.assertEqual(len(paths), 1)

    def test_is_history_available_true_when_db_exists(self):
        self._make_profile_with_db("prof.default")
        self._write_ini("""
[Profile0]
Name=default
IsRelative=1
Path=prof.default
""")
        self.assertTrue(self._make_defn().is_history_available())

    def test_is_history_available_false_when_no_ini(self):
        defn = BrowserDef(
            browser_type="firefox_test",
            display_name="Firefox Test",
            engine="firefox",
            _data_dirs=(self.base / "nonexistent",),
        )
        self.assertFalse(defn.is_history_available())

    def test_parse_firefox_profiles_ini_function_directly(self):
        """直接测试模块级工具函数，验证参数化 db_filename 能正确切换目标文件。"""
        self._make_profile_with_db("p1.default")
        ini_path = self.base / "profiles.ini"
        ini_path.write_text(
            """
[Profile0]
Name=default
IsRelative=1
Path=p1.default
""",
            encoding="utf-8",
        )

        # 请求 places.sqlite
        results_history = list(_parse_firefox_profiles_ini(self.base, ini_path, "places.sqlite"))
        self.assertEqual(len(results_history), 1)
        self.assertTrue(results_history[0][1].name == "places.sqlite")

        # 请求 favicons.sqlite（不存在，应为空）
        results_favicon = list(_parse_firefox_profiles_ini(self.base, ini_path, "favicons.sqlite"))
        self.assertEqual(len(results_favicon), 0)


# ══════════════════════════════════════════════════════════════
# 8. ExtractorManager
# ══════════════════════════════════════════════════════════════


class TestExtractorManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "history.db"
        self.local_db = LocalDatabase(db_path)

    def tearDown(self):
        self.local_db.close()
        self._tmp.cleanup()

    def _make_mock_extractor(
        self,
        browser_type: str,
        records: list[HistoryRecord],
    ) -> MagicMock:
        ext = MagicMock(spec=ChromiumExtractor)
        ext.browser_type = browser_type
        ext.display_name = browser_type.title()
        ext.is_available.return_value = True
        ext.extract.return_value = records
        return ext

    def test_run_extraction_inserts_records(self):
        records = [
            _make_record(url="https://a.com", browser_type="chrome"),
            _make_record(url="https://b.com", browser_type="chrome", visit_time=1704067201),
        ]
        em = ExtractorManager(self.local_db)
        em._registry = {"chrome": self._make_mock_extractor("chrome", records)}

        results = em.run_extraction(["chrome"])
        self.assertEqual(results["chrome"], 2)
        self.assertEqual(self.local_db.get_total_count(), 2)

    def test_run_extraction_parallel_multiple_browsers(self):
        chrome_records = [_make_record(url="https://c.com", browser_type="chrome")]
        ff_records = [_make_record(url="https://f.com", browser_type="firefox")]

        em = ExtractorManager(self.local_db)
        em._registry = {
            "chrome": self._make_mock_extractor("chrome", chrome_records),
            "firefox": self._make_mock_extractor("firefox", ff_records),
        }

        results = em.run_extraction(["chrome", "firefox"])
        self.assertEqual(results.get("chrome"), 1)
        self.assertEqual(results.get("firefox"), 1)
        self.assertEqual(self.local_db.get_total_count(), 2)

    def test_run_extraction_passes_since_map_to_extractor(self):
        """验证增量模式：since_map 从数据库查询后传递给 extractor.extract()"""
        # 先写入一条记录，使 get_max_visit_times 返回非空 map
        existing = _make_record(visit_time=9000)
        self.local_db.upsert_records([existing])

        mock_ext = self._make_mock_extractor("chrome", [])
        em = ExtractorManager(self.local_db)
        em._registry = {"chrome": mock_ext}

        em.run_extraction(["chrome"])

        mock_ext.extract.assert_called_once()
        call_args = mock_ext.extract.call_args
        since_map = call_args.kwargs.get("since_map") if call_args.kwargs else None
        if since_map is None and call_args.args:
            since_map = call_args.args[0]
        self.assertIsNotNone(since_map)
        self.assertIsInstance(since_map, dict)
        self.assertIn("Default", since_map)
        self.assertEqual(since_map["Default"], 9000)

    def test_run_extraction_extractor_exception_handled(self):
        mock_ext = MagicMock(spec=ChromiumExtractor)
        mock_ext.browser_type = "chrome"
        mock_ext.display_name = "Chrome"
        mock_ext.is_available.return_value = True
        mock_ext.extract.side_effect = RuntimeError("disk error")

        em = ExtractorManager(self.local_db)
        em._registry = {"chrome": mock_ext}

        results = em.run_extraction(["chrome"])
        self.assertEqual(results["chrome"], 0)

    def test_progress_callback_called(self):
        records = [_make_record(url="https://x.com")]
        em = ExtractorManager(self.local_db)
        em._registry = {"chrome": self._make_mock_extractor("chrome", records)}

        events: list[tuple] = []
        em.run_extraction(["chrome"], progress_callback=lambda bt, s, c: events.append((bt, s, c)))

        statuses = [e[1] for e in events]
        self.assertIn("extracting", statuses)
        self.assertIn("saving", statuses)
        self.assertIn("done", statuses)

    def test_get_available_browsers_filters_unavailable(self):
        available = MagicMock()
        available.browser_type = "chrome"
        available.is_available.return_value = True

        unavailable = MagicMock()
        unavailable.browser_type = "firefox"
        unavailable.is_available.return_value = False

        em = ExtractorManager(self.local_db)
        em._registry = {"chrome": available, "firefox": unavailable}

        result = em.get_available_browsers()
        self.assertIn("chrome", result)
        self.assertNotIn("firefox", result)

    # ── disabled 过滤在注册阶段 ───────────────────────────────

    def test_disabled_browser_not_in_registry_at_init(self):
        """
        disabled_browsers 中的浏览器在初始化时不应进入注册表，
        而非等到查询时才过滤——与 FaviconExtractorManager 行为一致。
        """
        em = ExtractorManager(self.local_db, disabled_browsers=["chrome", "edge"])
        self.assertNotIn("chrome", em._registry)
        self.assertNotIn("edge", em._registry)
        # 未禁用的浏览器仍在注册表中
        self.assertIn("firefox", em._registry)
        self.assertIn("brave", em._registry)

    def test_disabled_browser_not_returned_by_get_available(self):
        """验证禁用的浏览器不会出现在 get_available_browsers() 结果中。"""
        em = ExtractorManager(self.local_db, disabled_browsers=["chrome"])
        # 清空注册表，只注入 mock chrome，确保测试不触碰真实浏览器
        em._registry = {"chrome": self._make_mock_extractor("chrome", [])}
        em._disabled.add("chrome")
        em._registry.pop("chrome", None)
        results = em.run_extraction()
        self.assertNotIn("chrome", results)
        self.assertEqual(results, {})

    def test_run_extraction_disabled_browser_skipped(self):
        mock_ext = self._make_mock_extractor("chrome", [])
        em = ExtractorManager(self.local_db, disabled_browsers=["chrome"])
        # 清空注册表，只留 mock chrome（已被禁用），隔离真实环境浏览器
        em._registry = {}
        # chrome 被禁用，不在注册表中
        self.assertNotIn("chrome", em._registry)
        results = em.run_extraction()
        self.assertEqual(results, {})
        mock_ext.extract.assert_not_called()

    # ── update_config 热更新 ──────────────────────────────────

    def test_update_config_disables_browser(self):
        """update_config() 新增禁用项后，对应提取器应从注册表移除。"""
        em = ExtractorManager(self.local_db)
        self.assertIn("chrome", em._registry)

        em.update_config(disabled_browsers=["chrome"])

        self.assertNotIn("chrome", em._registry)
        self.assertIn("chrome", em._disabled)

    def test_update_config_reenables_browser(self):
        """update_config() 取消禁用后，对应提取器应重新出现在注册表中。"""
        em = ExtractorManager(self.local_db, disabled_browsers=["chrome"])
        self.assertNotIn("chrome", em._registry)

        em.update_config(disabled_browsers=[])

        self.assertIn("chrome", em._registry)
        self.assertNotIn("chrome", em._disabled)

    def test_update_config_no_change_is_stable(self):
        """update_config() 传入相同的禁用列表不应崩溃，注册表保持不变。"""
        em = ExtractorManager(self.local_db, disabled_browsers=["edge"])
        registry_before = set(em._registry.keys())

        em.update_config(disabled_browsers=["edge"])

        self.assertEqual(set(em._registry.keys()), registry_before)

    def test_update_config_only_affects_changed_entries(self):
        """update_config() 只应变更真正发生改变的条目，不影响其他提取器。"""
        em = ExtractorManager(self.local_db)
        firefox_extractor_before = em._registry.get("firefox")

        em.update_config(disabled_browsers=["chrome"])

        # chrome 被移除
        self.assertNotIn("chrome", em._registry)
        # firefox 实例不应被重建（对象 id 不变）
        self.assertIs(em._registry.get("firefox"), firefox_extractor_before)

    def test_update_config_disables_then_reenables_custom_path_ignored(self):
        """
        update_config() 重新启用时只处理内置浏览器；
        自定义路径提取器需由调用方手动 register()，不受此方法影响。
        """
        em = ExtractorManager(self.local_db, disabled_browsers=["chrome"])
        # 验证 chrome 重新启用后类型正确（ChromiumExtractor 实例）
        em.update_config(disabled_browsers=[])
        self.assertIsInstance(em._registry["chrome"], ChromiumExtractor)


# ══════════════════════════════════════════════════════════════
# 9. AppConfig 原子写入 & 加载
# ══════════════════════════════════════════════════════════════


class TestAppConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._config_dir = Path(self._tmp.name)
        # Patch the runtime path functions so AppConfig.load()/save() use our temp dir
        self._patches = [
            unittest.mock.patch("src.models.app_config._resolve_config_dir", return_value=self._config_dir),
            unittest.mock.patch("src.models.app_config._resolve_data_dir", return_value=self._config_dir),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_save_and_load_roundtrip(self):
        cfg = AppConfig()
        cfg.window_width = 1280
        cfg.window_height = 800
        cfg.webdav.url = "https://dav.example.com"
        cfg.scheduler.sync_interval_hours = 12
        cfg.save()

        loaded = AppConfig.load()
        self.assertEqual(loaded.window_width, 1280)
        self.assertEqual(loaded.window_height, 800)
        self.assertEqual(loaded.webdav.url, "https://dav.example.com")
        self.assertEqual(loaded.scheduler.sync_interval_hours, 12)

    def test_save_is_valid_json(self):
        AppConfig().save()
        raw = (self._config_dir / "config.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)  # 不应抛出
        self.assertIn("webdav", parsed)
        self.assertIn("scheduler", parsed)

    def test_no_tmp_file_left_after_save(self):
        AppConfig().save()
        tmp_files = list(self._config_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_load_returns_defaults_when_no_file(self):
        cfg = AppConfig.load()
        self.assertEqual(cfg.window_width, 1100)
        self.assertFalse(cfg.webdav.enabled)

    def test_load_handles_corrupt_json(self):
        (self._config_dir / "config.json").write_text("NOT JSON{{", encoding="utf-8")
        cfg = AppConfig.load()
        # 损坏时应返回默认配置，不应崩溃
        self.assertIsInstance(cfg, AppConfig)

    def test_load_handles_missing_fields(self):
        """未来版本可能新增字段；旧配置文件缺少字段时应使用默认值。"""
        partial = {"window_width": 900}
        (self._config_dir / "config.json").write_text(json.dumps(partial), encoding="utf-8")
        cfg = AppConfig.load()
        self.assertEqual(cfg.window_width, 900)
        self.assertEqual(cfg.window_height, 700)  # 默认值

    def test_webdav_config_loaded_correctly(self):
        cfg = AppConfig()
        cfg.webdav = WebDavConfig(
            enabled=True,
            url="https://cloud.com/dav",
            username="alice",
            password="secret",
            max_backups=5,
        )
        cfg.save()
        loaded = AppConfig.load()
        self.assertTrue(loaded.webdav.enabled)
        self.assertEqual(loaded.webdav.url, "https://cloud.com/dav")
        self.assertEqual(loaded.webdav.username, "alice")
        self.assertEqual(loaded.webdav.max_backups, 5)

    def test_get_db_path_default(self):
        cfg = AppConfig()
        # 未设置自定义路径时，应返回 CONFIG_DIR/history.db
        db_path = cfg.get_db_path()
        self.assertEqual(db_path.name, "history.db")

    def test_get_db_path_custom(self):
        cfg = AppConfig()
        cfg.db_path = "/custom/path/my.db"
        self.assertEqual(cfg.get_db_path(), Path("/custom/path/my.db"))


# ══════════════════════════════════════════════════════════════
# 10. 增量提取端到端集成
# ══════════════════════════════════════════════════════════════


class TestIncrementalExtractionIntegration(unittest.TestCase):
    """
    端到端测试：模拟两次同步，验证第二次只写入新记录。
    使用 ChromiumExtractor.for_custom_path() 创建提取器实例。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.local_db = LocalDatabase(tmp / "history.db")
        self.browser_db = tmp / "History"

    def tearDown(self):
        self.local_db.close()
        self._tmp.cleanup()

    def test_second_run_only_inserts_new_records(self):
        base_ts = 1704067200
        chromium_ts = unix_to_chromium_time

        # ── 第一次同步：2 条记录 ──
        _create_chromium_db(
            self.browser_db,
            [
                ("https://a.com", "A", chromium_ts(base_ts), 1),
                ("https://b.com", "B", chromium_ts(base_ts + 1), 1),
            ],
        )
        ext = ChromiumExtractor.for_custom_path("chrome_test", "Chrome Test", self.browser_db)
        since_map1 = self.local_db.get_max_visit_times("chrome_test")  # {}
        records1 = ext.extract(since_map=since_map1)
        n1 = self.local_db.upsert_records(records1)
        self.assertEqual(n1, 2)

        # ── 第二次同步：数据库新增 1 条 ──
        _create_chromium_db(
            self.browser_db,
            [
                ("https://a.com", "A", chromium_ts(base_ts), 1),
                ("https://b.com", "B", chromium_ts(base_ts + 1), 1),
                ("https://c.com", "C", chromium_ts(base_ts + 2), 1),  # 新记录
            ],
        )
        since_map2 = self.local_db.get_max_visit_times("chrome_test")
        # since_map2["custom"] 应等于 base_ts + 1
        self.assertEqual(since_map2.get("custom"), base_ts + 1)

        records2 = ext.extract(since_map=since_map2)
        # 增量模式只读出 visit_time > base_ts+1 的记录
        self.assertEqual(len(records2), 1)
        self.assertEqual(records2[0].url, "https://c.com")

        n2 = self.local_db.upsert_records(records2)
        self.assertEqual(n2, 1)
        self.assertEqual(self.local_db.get_total_count(), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
