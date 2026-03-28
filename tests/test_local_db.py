# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``LocalDatabase``.

Sections:
  - Schema creation
  - Upsert (deduplication, large batches, cross-batch dedup)
  - get_total_count / get_max_visit_times
  - get_records (pagination, ordering, filters)
  - get_filtered_count
  - backup_stats
  - get_browser_types
  - Thread-safety (concurrent writes)
"""

from __future__ import annotations

import threading
import time

from tests.conftest import make_record

# ══════════════════════════════════════════════════════════════
# Schema
# ══════════════════════════════════════════════════════════════


class TestSchema:
    def test_history_table_created(self, local_db):
        with local_db._conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "history" in tables

    def test_backup_stats_table_created(self, local_db):
        with local_db._conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "backup_stats" in tables

    def test_fts_virtual_table_created(self, local_db):
        with local_db._conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "history_fts" in tables


# ══════════════════════════════════════════════════════════════
# Upsert
# ══════════════════════════════════════════════════════════════


class TestUpsert:
    def test_returns_correct_count(self, local_db):
        records = [make_record(url=f"https://site{i}.com") for i in range(10)]
        assert local_db.upsert_records(records) == 10

    def test_deduplication(self, local_db):
        r = make_record()
        local_db.upsert_records([r])
        assert local_db.upsert_records([r]) == 0
        assert local_db.get_total_count() == 1

    def test_empty_list(self, local_db):
        assert local_db.upsert_records([]) == 0

    def test_large_batch_exceeds_batch_size(self, local_db):
        """Insert 1200 records (crosses the internal _BATCH_SIZE boundary)."""
        records = [make_record(url=f"https://x.com/{i}") for i in range(1200)]
        assert local_db.upsert_records(records) == 1200
        assert local_db.get_total_count() == 1200

    def test_partial_dedup_across_batches(self, local_db):
        """First 600 already exist; only the next 600 should be counted as new."""
        existing = [make_record(url=f"https://x.com/{i}") for i in range(600)]
        local_db.upsert_records(existing)

        all_records = existing + [make_record(url=f"https://x.com/{i}") for i in range(600, 1200)]
        assert local_db.upsert_records(all_records) == 600

    def test_same_url_different_browsers_both_inserted(self, local_db):
        """Dedup key includes browser_type; different browsers must each be stored."""
        r1 = make_record(browser_type="chrome")
        r2 = make_record(browser_type="firefox")
        local_db.upsert_records([r1, r2])
        assert local_db.get_total_count() == 2


# ══════════════════════════════════════════════════════════════
# get_total_count / get_max_visit_times
# ══════════════════════════════════════════════════════════════


class TestCounts:
    def test_total_count_empty(self, local_db):
        assert local_db.get_total_count() == 0

    def test_max_visit_times_empty(self, local_db):
        assert local_db.get_max_visit_times("chrome") == {}

    def test_max_visit_times_single_profile(self, local_db):
        records = [
            make_record(visit_time=1000, profile_name="Default"),
            make_record(url="https://b.com", visit_time=9999, profile_name="Default"),
            make_record(url="https://c.com", visit_time=5000, profile_name="Default"),
        ]
        local_db.upsert_records(records)
        assert local_db.get_max_visit_times("chrome") == {"Default": 9999}

    def test_max_visit_times_multi_profile(self, local_db):
        records = [
            make_record(url="https://a.com", visit_time=1000, profile_name="Default"),
            make_record(url="https://b.com", visit_time=2000, profile_name="Default"),
            make_record(url="https://c.com", visit_time=3000, profile_name="Profile 1"),
            make_record(url="https://d.com", visit_time=500, profile_name="Profile 1"),
        ]
        local_db.upsert_records(records)
        result = local_db.get_max_visit_times("chrome")
        assert result["Default"] == 2000
        assert result["Profile 1"] == 3000

    def test_max_visit_times_ignores_other_browsers(self, local_db):
        chrome_r = make_record(url="https://a.com", visit_time=9999, browser_type="chrome")
        firefox_r = make_record(url="https://b.com", visit_time=1, browser_type="firefox")
        local_db.upsert_records([chrome_r, firefox_r])
        result = local_db.get_max_visit_times("firefox")
        assert result == {"Default": 1}


# ══════════════════════════════════════════════════════════════
# get_records (pagination, ordering, filters)
# ══════════════════════════════════════════════════════════════


class TestGetRecords:
    def test_returns_all_when_less_than_limit(self, local_db):
        local_db.upsert_records([make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(5)])
        assert len(local_db.get_records(limit=100)) == 5

    def test_pagination_is_disjoint(self, local_db):
        local_db.upsert_records([make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(20)])
        page1 = local_db.get_records(limit=10, offset=0)
        page2 = local_db.get_records(limit=10, offset=10)
        assert len(page1) == 10
        assert len(page2) == 10
        assert {r.url for r in page1}.isdisjoint({r.url for r in page2})

    def test_ordered_by_visit_time_desc(self, local_db):
        local_db.upsert_records([make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(5)])
        times = [r.visit_time for r in local_db.get_records(limit=100)]
        assert times == sorted(times, reverse=True)

    def test_browser_filter(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://a.com", browser_type="chrome"),
                make_record(url="https://b.com", browser_type="firefox"),
            ]
        )
        rows = local_db.get_records(browser_type="chrome")
        assert all(r.browser_type == "chrome" for r in rows)
        assert len(rows) == 1

    def test_date_from_filter(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://old.com", visit_time=1000),
                make_record(url="https://new.com", visit_time=9000),
            ]
        )
        rows = local_db.get_records(date_from=5000)
        assert len(rows) == 1
        assert rows[0].url == "https://new.com"


# ══════════════════════════════════════════════════════════════
# get_filtered_count
# ══════════════════════════════════════════════════════════════


class TestFilteredCount:
    def test_total_matches_upserted(self, local_db):
        local_db.upsert_records([make_record(url=f"https://x.com/{i}", visit_time=i + 1) for i in range(50)])
        assert local_db.get_filtered_count() == 50

    def test_browser_filter_count(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://a.com", browser_type="chrome"),
                make_record(url="https://b.com", browser_type="firefox"),
                make_record(url="https://c.com", browser_type="chrome"),
            ]
        )
        assert local_db.get_filtered_count(browser_type="chrome") == 2


# ══════════════════════════════════════════════════════════════
# backup_stats
# ══════════════════════════════════════════════════════════════


class TestBackupStats:
    def test_insert(self, local_db):
        local_db.update_backup_stats("chrome", "Default", 100)
        stats = local_db.get_all_backup_stats()
        assert len(stats) == 1
        assert stats[0].total_records_synced == 100

    def test_accumulates(self, local_db):
        local_db.update_backup_stats("chrome", "Default", 100)
        local_db.update_backup_stats("chrome", "Default", 50)
        stats = local_db.get_all_backup_stats()
        assert stats[0].total_records_synced == 150

    def test_multiple_profiles(self, local_db):
        local_db.update_backup_stats("chrome", "Default", 10)
        local_db.update_backup_stats("chrome", "Profile 1", 20)
        assert len(local_db.get_all_backup_stats()) == 2

    def test_last_sync_time_none_when_empty(self, local_db):
        assert local_db.get_last_sync_time() is None

    def test_last_sync_time_is_recent(self, local_db):
        local_db.update_backup_stats("chrome", "Default", 10)
        t = local_db.get_last_sync_time()
        assert t is not None
        assert abs(t - int(time.time())) <= 5


# ══════════════════════════════════════════════════════════════
# get_browser_types
# ══════════════════════════════════════════════════════════════


class TestBrowserTypes:
    def test_returns_all_inserted_browser_types(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://a.com", browser_type="chrome"),
                make_record(url="https://b.com", browser_type="firefox"),
            ]
        )
        types = local_db.get_browser_types()
        assert "chrome" in types
        assert "firefox" in types


# ══════════════════════════════════════════════════════════════
# Thread safety
# ══════════════════════════════════════════════════════════════


class TestThreadSafety:
    def test_concurrent_upsert(self, local_db):
        """Concurrent writes from 8 threads must not crash or lose records."""
        N_THREADS, N_PER_THREAD = 8, 50
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                records = [
                    make_record(
                        url=f"https://t{thread_id}.com/{j}",
                        visit_time=thread_id * 1000 + j,
                    )
                    for j in range(N_PER_THREAD)
                ]
                local_db.upsert_records(records)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert local_db.get_total_count() == N_THREADS * N_PER_THREAD
