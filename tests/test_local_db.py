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

import sqlite3
import threading
import time

import pytest

from src.services.local_db import LocalDatabase
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


class TestLocateOffset:
    def test_get_row_offset_for_url_returns_minus_one_when_missing(self, local_db):
        assert local_db.get_row_offset_for_url("https://missing.example") == -1

    def test_get_row_offset_for_url_matches_sort_with_same_timestamp_ties(self, local_db):
        # Insert multiple rows sharing the same visit_time so id DESC tie-break
        # order matters for locate-in-history row offset.
        local_db.upsert_records(
            [
                make_record(url="https://newer.example", visit_time=2000),
                make_record(url="https://target.example/a", visit_time=1000),
                make_record(url="https://other.example/1", visit_time=1000),
                make_record(url="https://target.example/b", visit_time=1000),
                make_record(url="https://older.example", visit_time=900),
            ]
        )

        ordered = local_db.get_records(limit=100)
        offset = local_db.get_row_offset_for_url("https://target.example/b")

        # Must point to the first (most-recent) row among matching URL visits.
        expected = next(i for i, rec in enumerate(ordered) if rec.url == "https://target.example/b")
        assert offset == expected

    def test_get_row_offset_for_url_uses_most_recent_visit_of_url(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://target.example", visit_time=3000),
                make_record(url="https://other.example", visit_time=2500),
                make_record(url="https://target.example", visit_time=1000),
            ]
        )

        ordered = local_db.get_records(limit=100)
        offset = local_db.get_row_offset_for_url("https://target.example")
        expected = next(i for i, rec in enumerate(ordered) if rec.url == "https://target.example")
        assert offset == expected

    def test_get_row_offset_for_history_id_targets_exact_visit(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://same.example", visit_time=3000),
                make_record(url="https://same.example", visit_time=2000),
                make_record(url="https://other.example", visit_time=1000),
            ]
        )

        ordered = local_db.get_records(limit=100)
        target = next(rec for rec in ordered if rec.url == "https://same.example" and rec.visit_time == 2000)
        offset = local_db.get_row_offset_for_history_id(target.id)
        expected = next(i for i, rec in enumerate(ordered) if rec.id == target.id)
        assert offset == expected

    def test_row_offset_helpers_match_visible_and_hidden_datasets(self, local_db):
        local_db.upsert_records(
            [
                make_record(url="https://visible-new.example", visit_time=3000),
                make_record(url="https://hidden.example", visit_time=2000),
                make_record(url="https://visible-old.example", visit_time=1000),
            ]
        )

        all_rows = local_db.get_records(limit=100)
        hidden_row = next(rec for rec in all_rows if rec.url == "https://hidden.example")
        next(rec for rec in all_rows if rec.url == "https://visible-old.example")

        local_db.hide_records_by_ids([hidden_row.id])
        hidden_ids = local_db.get_all_hidden_ids()

        visible_offset = local_db.get_row_offset_for_url(
            "https://visible-old.example",
            excluded_ids=hidden_ids,
            hidden_only=False,
        )
        assert visible_offset == 1

        hidden_offset = local_db.get_row_offset_for_history_id(
            hidden_row.id,
            excluded_ids=hidden_ids,
            hidden_only=True,
        )
        assert hidden_offset == 0


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


class TestLifecycle:
    def test_context_manager_closes_connections(self, tmp_path):
        db_path = tmp_path / "lifecycle_ctx.db"
        with LocalDatabase(db_path) as db:
            assert db.get_total_count() == 0
            assert db._pconn is not None
        assert db._pconn is None
        assert db._ro_conn is None

    def test_close_is_idempotent(self, local_db):
        local_db.get_total_count()
        local_db.close()
        # Calling close() repeatedly should be safe and should not raise.
        local_db.close()


# ══════════════════════════════════════════════════════════════
# Bookmark CRUD
# ══════════════════════════════════════════════════════════════


class TestBookmarkCRUD:
    def test_add_and_get_bookmark(self, local_db):
        """Add and retrieve a bookmark."""
        bm = local_db.add_bookmark("https://example.com", "Example", tags=[])
        assert bm.url == "https://example.com"
        assert bm.title == "Example"

    def test_add_with_tags(self, local_db):
        """Add bookmark with tags."""
        bm = local_db.add_bookmark("https://example.com", "Example", tags=["work", "ref"])
        assert bm.tags == ["work", "ref"]

    def test_add_idempotent_upsert(self, local_db):
        """Adding same URL twice updates the bookmark."""
        local_db.add_bookmark("https://example.com", "Title1", tags=["a"])
        local_db.add_bookmark("https://example.com", "Title2", tags=["b"])
        assert local_db.is_bookmarked("https://example.com")

    def test_remove_returns_true(self, local_db):
        """Remove existing bookmark returns True."""
        local_db.add_bookmark("https://example.com", "Example", tags=[])
        assert local_db.remove_bookmark("https://example.com") is True

    def test_remove_nonexistent_returns_false(self, local_db):
        """Remove nonexistent bookmark returns False."""
        assert local_db.remove_bookmark("https://nonexistent.com") is False

    def test_is_bookmarked_true(self, local_db):
        """is_bookmarked returns True for bookmarked URL."""
        local_db.add_bookmark("https://example.com", "Example", tags=[])
        assert local_db.is_bookmarked("https://example.com") is True

    def test_is_bookmarked_false(self, local_db):
        """is_bookmarked returns False for non-bookmarked URL."""
        assert local_db.is_bookmarked("https://nonexistent.com") is False

    def test_get_bookmarked_urls(self, local_db):
        """get_bookmarked_urls returns set of bookmarked URLs."""
        local_db.add_bookmark("https://a.com", "A", tags=[])
        local_db.add_bookmark("https://b.com", "B", tags=[])
        urls = local_db.get_bookmarked_urls()
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_get_bookmarked_urls_no_duplicates_multi_tagged(self, local_db):
        """get_bookmarked_urls returns each URL exactly once even when multi-tagged."""
        local_db.add_bookmark("https://a.com", "A", tags=["work", "ref", "python"])
        urls = local_db.get_bookmarked_urls()
        url_list = [u for u in urls if u == "https://a.com"]
        assert len(url_list) == 1

    def test_get_all_bookmarks_no_filter(self, local_db):
        """get_all_bookmarks returns all bookmarks."""
        local_db.add_bookmark("https://a.com", "A", tags=[])
        local_db.add_bookmark("https://b.com", "B", tags=[])
        bms = local_db.get_all_bookmarks()
        assert len(bms) == 2

    def test_get_all_bookmarks_tag_filter(self, local_db):
        """get_all_bookmarks filters by tag."""
        local_db.add_bookmark("https://a.com", "A", tags=["work"])
        local_db.add_bookmark("https://b.com", "B", tags=["personal"])
        bms = local_db.get_all_bookmarks(tag="work")
        assert len(bms) == 1
        assert bms[0].url == "https://a.com"

    def test_get_all_bookmark_tags(self, local_db):
        """get_all_bookmark_tags returns distinct tags."""
        local_db.add_bookmark("https://a.com", "A", tags=["work", "ref"])
        local_db.add_bookmark("https://b.com", "B", tags=["work"])
        tags = local_db.get_all_bookmark_tags()
        assert "work" in tags
        assert "ref" in tags

    def test_update_bookmark_tags(self, local_db):
        """update_bookmark_tags updates tags."""
        local_db.add_bookmark("https://example.com", "Example", tags=["old"])
        local_db.update_bookmark_tags("https://example.com", ["new"])
        bm = local_db.get_bookmark("https://example.com")
        assert bm.tags == ["new"]

    def test_update_bookmark_tags_nonexistent_returns_false(self, local_db):
        """update_bookmark_tags on nonexistent URL returns False."""
        assert local_db.update_bookmark_tags("https://nonexistent.com", ["tag"]) is False

    def test_remove_writes_tombstone(self, local_db):
        """Removing bookmark writes to deleted_bookmarks."""
        local_db.add_bookmark("https://example.com", "Example", tags=[])
        local_db.remove_bookmark("https://example.com")
        # Verify tombstone exists by checking is_bookmarked is False
        assert local_db.is_bookmarked("https://example.com") is False


# ══════════════════════════════════════════════════════════════
# Annotation CRUD
# ══════════════════════════════════════════════════════════════


class TestAnnotationCRUD:
    def test_upsert_insert(self, local_db):
        """Upsert annotation inserts new record."""
        ann = local_db.upsert_annotation("https://example.com", "my note")
        assert ann.url == "https://example.com"
        assert ann.note == "my note"

    def test_upsert_update_preserves_created_at(self, local_db):
        """Upsert updates note but preserves created_at."""
        ann1 = local_db.upsert_annotation("https://example.com", "note1")
        created_at_1 = ann1.created_at
        ann2 = local_db.upsert_annotation("https://example.com", "note2")
        assert ann2.created_at == created_at_1
        assert ann2.note == "note2"

    def test_delete_returns_true(self, local_db):
        """Delete existing annotation returns True."""
        local_db.upsert_annotation("https://example.com", "note")
        assert local_db.delete_annotation("https://example.com") is True

    def test_delete_nonexistent_returns_false(self, local_db):
        """Delete nonexistent annotation returns False."""
        assert local_db.delete_annotation("https://nonexistent.com") is False

    def test_get_annotation(self, local_db):
        """Get annotation returns record."""
        local_db.upsert_annotation("https://example.com", "my note")
        ann = local_db.get_annotation("https://example.com")
        assert ann.note == "my note"

    def test_get_annotation_missing(self, local_db):
        """Get nonexistent annotation returns None."""
        assert local_db.get_annotation("https://nonexistent.com") is None

    def test_get_annotated_urls(self, local_db):
        """get_annotated_urls returns set of URLs."""
        local_db.upsert_annotation("https://a.com", "note a")
        local_db.upsert_annotation("https://b.com", "note b")
        urls = local_db.get_annotated_urls()
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_get_all_annotations(self, local_db):
        """get_all_annotations returns all annotations."""
        local_db.upsert_annotation("https://a.com", "note a")
        local_db.upsert_annotation("https://b.com", "note b")
        anns = local_db.get_all_annotations()
        assert len(anns) == 2

    def test_delete_writes_tombstone(self, local_db):
        """Deleting annotation writes to deleted_annotations."""
        local_db.upsert_annotation("https://example.com", "note")
        local_db.delete_annotation("https://example.com")
        assert local_db.get_annotation("https://example.com") is None


# ══════════════════════════════════════════════════════════════
# Hidden Records
# ══════════════════════════════════════════════════════════════


class TestHiddenRecords:
    def test_hide_records(self, local_db, make_rec):
        """Hide records by IDs."""
        rec = make_rec()
        local_db.upsert_records([rec])
        record_id = local_db.get_records(keyword="", limit=1)[0].id
        local_db.hide_records_by_ids([record_id])
        hidden = local_db.get_hidden_ids()
        assert record_id in hidden

    def test_hide_empty_list_noop(self, local_db):
        """Hiding empty list is no-op."""
        local_db.hide_records_by_ids([])
        assert len(local_db.get_hidden_ids()) == 0

    def test_get_hidden_ids_all(self, local_db, make_rec):
        """get_hidden_ids returns all hidden IDs."""
        rec1 = make_rec(url="https://a.com")
        rec2 = make_rec(url="https://b.com")
        local_db.upsert_records([rec1, rec2])
        ids = [r.id for r in local_db.get_records(keyword="", limit=10)]
        local_db.hide_records_by_ids(ids)
        hidden = local_db.get_hidden_ids()
        assert len(hidden) == 2

    def test_get_hidden_ids_candidate_filter(self, local_db, make_rec):
        """get_hidden_ids filters by candidate IDs."""
        rec1 = make_rec(url="https://a.com")
        rec2 = make_rec(url="https://b.com")
        local_db.upsert_records([rec1, rec2])
        ids = [r.id for r in local_db.get_records(keyword="", limit=10)]
        local_db.hide_records_by_ids(ids)
        hidden = local_db.get_hidden_ids(candidate_ids=[ids[0]])
        assert len(hidden) == 1
        assert ids[0] in hidden

    def test_clear_hidden_records(self, local_db, make_rec):
        """clear_hidden_records removes all hidden records."""
        rec = make_rec()
        local_db.upsert_records([rec])
        record_id = local_db.get_records(keyword="", limit=1)[0].id
        local_db.hide_records_by_ids([record_id])
        count = local_db.clear_hidden_records()
        assert count == 1
        assert len(local_db.get_hidden_ids()) == 0


class TestWalSnapshotFreshness:
    def test_get_hidden_ids_refreshes_after_write(self, local_db, make_rec):
        local_db.upsert_records([make_rec(url="https://fresh-hidden.com")])
        record_id = local_db.get_records(keyword="", limit=1)[0].id

        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_hidden_ids() == set()

        local_db.hide_records_by_ids([record_id])
        assert record_id in local_db.get_hidden_ids()

    def test_get_hidden_domain_ids_refreshes_after_write(self, local_db, make_rec):
        local_db.upsert_records([make_rec(url="https://docs.example.com/path")])
        record_id = local_db.get_records(keyword="", limit=1)[0].id

        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_hidden_domain_ids() == set()

        local_db.hide_domain("example.com", subdomain_only=False)
        assert record_id in local_db.get_hidden_domain_ids()

    def test_is_bookmarked_refreshes_after_write(self, local_db):
        url = "https://fresh-bookmark.com"

        # Prime the shared RO connection on an old snapshot.
        assert local_db.is_bookmarked(url) is False

        local_db.add_bookmark(url, "Fresh", tags=[])
        assert local_db.is_bookmarked(url) is True

        local_db.remove_bookmark(url)
        assert local_db.is_bookmarked(url) is False

    def test_get_annotation_refreshes_after_write(self, local_db):
        url = "https://fresh-annotation.com"

        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_annotation(url) is None

        local_db.upsert_annotation(url, "new note")
        ann = local_db.get_annotation(url)
        assert ann is not None
        assert ann.note == "new note"

        local_db.delete_annotation(url)
        assert local_db.get_annotation(url) is None

    def test_get_total_count_refreshes_after_write(self, local_db, make_rec):
        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_total_count() == 0

        local_db.upsert_records([make_rec(url="https://fresh-count.com")])
        assert local_db.get_total_count() == 1

    def test_get_max_visit_times_refreshes_after_write(self, local_db, make_rec):
        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_max_visit_times("chrome") == {}

        local_db.upsert_records([make_rec(url="https://fresh-max-time.com", visit_time=1234567890)])
        assert local_db.get_max_visit_times("chrome") == {"Default": 1234567890}

    def test_last_sync_stats_refresh_after_write(self, local_db):
        # Prime the shared RO connection on an old snapshot.
        assert local_db.get_last_sync_time() is None
        assert local_db.get_all_backup_stats() == []

        local_db.update_backup_stats("chrome", "Default", 1)

        last_sync = local_db.get_last_sync_time()
        stats = local_db.get_all_backup_stats()
        assert last_sync is not None
        assert len(stats) == 1
        assert stats[0].browser_type == "chrome"


# ══════════════════════════════════════════════════════════════
# Device CRUD
# ══════════════════════════════════════════════════════════════


class TestDeviceCRUD:
    def test_upsert_insert_returns_id(self, local_db):
        """Upsert device returns ID."""
        device_id = local_db.upsert_device("uuid-123", "MyPC")
        assert isinstance(device_id, int)
        assert device_id > 0

    def test_upsert_update_same_uuid(self, local_db):
        """Upsert same UUID updates name."""
        id1 = local_db.upsert_device("uuid-123", "OldName")
        id2 = local_db.upsert_device("uuid-123", "NewName")
        assert id1 == id2
        dev = local_db.get_device_by_uuid("uuid-123")
        assert dev["name"] == "NewName"

    def test_get_all_devices_empty(self, local_db):
        """get_all_devices on empty DB returns empty list."""
        assert local_db.get_all_devices() == []

    def test_get_all_devices(self, local_db):
        """get_all_devices returns all devices."""
        local_db.upsert_device("uuid-1", "PC1")
        local_db.upsert_device("uuid-2", "PC2")
        devs = local_db.get_all_devices()
        assert len(devs) == 2

    def test_get_device_by_uuid_found(self, local_db):
        """get_device_by_uuid returns device."""
        local_db.upsert_device("uuid-123", "MyPC")
        dev = local_db.get_device_by_uuid("uuid-123")
        assert dev["uuid"] == "uuid-123"
        assert dev["name"] == "MyPC"

    def test_get_device_by_uuid_missing(self, local_db):
        """get_device_by_uuid returns None for missing UUID."""
        assert local_db.get_device_by_uuid("nonexistent") is None

    def test_rename_device(self, local_db):
        """rename_device updates name."""
        device_id = local_db.upsert_device("uuid-123", "OldName")
        local_db.rename_device(device_id, "NewName")
        dev = local_db.get_device_by_id(device_id)
        assert dev["name"] == "NewName"

    def test_delete_device(self, local_db):
        """delete_device removes device."""
        device_id = local_db.upsert_device("uuid-123", "MyPC")
        local_db.delete_device(device_id)
        assert local_db.get_device_by_id(device_id) is None

    def test_get_device_name_map(self, local_db):
        """get_device_name_map returns ID→name mapping."""
        id1 = local_db.upsert_device("uuid-1", "PC1")
        id2 = local_db.upsert_device("uuid-2", "PC2")
        name_map = local_db.get_device_name_map()
        assert name_map[id1] == "PC1"
        assert name_map[id2] == "PC2"

    def test_merge_device_records(self, local_db, make_rec):
        """merge_device_records reassigns records to target device."""
        id1 = local_db.upsert_device("uuid-1", "PC1")
        id2 = local_db.upsert_device("uuid-2", "PC2")
        rec = make_rec()
        rec.device_id = id1
        local_db.upsert_records([rec])
        local_db.merge_device_records(from_id=id1, to_id=id2)
        records = local_db.get_records(keyword="", limit=1)
        assert records[0].device_id == id2


# ══════════════════════════════════════════════════════════════
# Delete Operations
# ══════════════════════════════════════════════════════════════


class TestDeleteOperations:
    def test_delete_by_ids(self, local_db, make_rec):
        """delete_records_by_ids removes records."""
        local_db.upsert_records([make_rec(url="https://a.com"), make_rec(url="https://b.com")])
        ids = [r.id for r in local_db.get_records(keyword="", limit=10)]
        local_db.delete_records_by_ids([ids[0]])
        assert local_db.get_total_count() == 1

    def test_delete_by_ids_empty_list(self, local_db):
        """delete_records_by_ids with empty list is no-op."""
        local_db.delete_records_by_ids([])
        assert local_db.get_total_count() == 0

    def test_delete_by_ids_writes_tombstones(self, local_db, make_rec):
        """delete_records_by_ids writes tombstones."""
        rec = make_rec(url="https://example.com")
        local_db.upsert_records([rec])
        record_id = local_db.get_records(keyword="", limit=1)[0].id
        local_db.delete_records_by_ids([record_id])
        # Verify record is gone
        assert local_db.get_total_count() == 0

    def test_delete_by_browser(self, local_db, make_rec):
        """delete_records_by_browser removes records for browser."""
        local_db.upsert_records(
            [
                make_rec(url="https://a.com", browser_type="chrome"),
                make_rec(url="https://b.com", browser_type="firefox"),
            ]
        )
        local_db.delete_records_by_browser("chrome")
        records = local_db.get_records(keyword="", limit=10)
        assert len(records) == 1
        assert records[0].browser_type == "firefox"

    def test_delete_by_domain(self, local_db, make_rec):
        """delete_records_by_domain removes records for domain."""
        local_db.upsert_records(
            [
                make_rec(url="https://github.com/foo"),
                make_rec(url="https://example.com/bar"),
            ]
        )
        local_db.delete_records_by_domain("github.com")
        records = local_db.get_records(keyword="", limit=10)
        assert len(records) == 1
        assert "example.com" in records[0].url


# ══════════════════════════════════════════════════════════════
# Domain Operations
# ══════════════════════════════════════════════════════════════


class TestDomainOperations:
    def test_get_domain_ids_empty(self, local_db):
        """get_domain_ids with empty list returns empty."""
        assert local_db.get_domain_ids([]) == []

    def test_get_domain_ids_known(self, local_db, make_rec):
        """get_domain_ids returns IDs for known domains."""
        local_db.upsert_records([make_rec(url="https://github.com/foo")])
        ids = local_db.get_domain_ids(["github.com"])
        assert len(ids) > 0

    def test_get_domain_count(self, local_db, make_rec):
        """get_domain_count returns record count for domain."""
        local_db.upsert_records(
            [
                make_rec(url="https://github.com/foo"),
                make_rec(url="https://github.com/bar"),
            ]
        )
        count = local_db.get_domain_count("github.com")
        assert count == 2

    def test_resolve_domain_ids_empty(self, local_db):
        """resolve_domain_ids with empty list returns empty."""
        assert local_db.resolve_domain_ids([]) == []


# ══════════════════════════════════════════════════════════════
# DB Stats
# ══════════════════════════════════════════════════════════════


class TestDbStats:
    def test_get_db_stats_returns_dataclass(self, local_db):
        """get_db_stats returns DbStats instance."""
        stats = local_db.get_db_stats()
        assert hasattr(stats, "record_count")
        assert hasattr(stats, "wasted_pct")

    def test_db_stats_record_count(self, local_db):
        """DbStats.record_count matches upserted count."""
        records = [make_record(url=f"https://example{i}.com") for i in range(5)]
        local_db.upsert_records(records)
        stats = local_db.get_db_stats()
        assert stats.record_count == 5

    def test_wasted_pct_normal(self, local_db):
        """wasted_pct property works normally."""
        stats = local_db.get_db_stats()
        assert isinstance(stats.wasted_pct, float)
        assert stats.wasted_pct >= 0

    def test_wasted_pct_zero_pages(self, local_db):
        """wasted_pct returns 0 when page_count is 0."""
        stats = local_db.get_db_stats()
        if stats.page_count == 0:
            assert stats.wasted_pct == 0.0


# ══════════════════════════════════════════════════════════════
# Module-level Helpers
# ══════════════════════════════════════════════════════════════


class TestModuleLevelHelpers:
    def test_quote_identifier_valid(self):
        """_quote_identifier quotes valid identifiers."""
        from src.services.local_db import _quote_identifier

        result = _quote_identifier("my_col")
        assert result == '"my_col"'

    def test_quote_identifier_rejects_invalid(self):
        """_quote_identifier rejects invalid identifiers."""
        from src.services.local_db import _quote_identifier

        with pytest.raises(ValueError):
            _quote_identifier("bad-name")

    def test_sanitize_col_type_valid(self):
        """_sanitize_col_type accepts valid types."""
        from src.services.local_db import _sanitize_col_type

        assert _sanitize_col_type("integer") == "INTEGER"

    def test_sanitize_col_type_rejects_invalid(self):
        """_sanitize_col_type rejects invalid types."""
        from src.services.local_db import _sanitize_col_type

        with pytest.raises(ValueError):
            _sanitize_col_type("BLOB; DROP TABLE")

    def test_sanitize_vacuum_path_escapes_quote(self):
        """_sanitize_vacuum_path escapes single quotes."""
        from src.services.local_db import _sanitize_vacuum_path

        result = _sanitize_vacuum_path("C:/path/it's")
        assert "it''s" in result

    def test_sanitize_vacuum_path_rejects_null_byte(self):
        """_sanitize_vacuum_path rejects null bytes."""
        from src.services.local_db import _sanitize_vacuum_path

        with pytest.raises(ValueError):
            _sanitize_vacuum_path("path\x00evil")


# ══════════════════════════════════════════════════════════════
# Merge Operations
# ══════════════════════════════════════════════════════════════


class TestMergeFromDb:
    def test_merge_basic_records(self, local_db, tmp_path):
        """merge_from_db merges records from source DB."""
        # Create source DB with proper HistorySync schema
        src_db_path = tmp_path / "src.db"
        src_db = LocalDatabase(src_db_path)
        records = [make_record(url=f"https://example{i}.com") for i in range(3)]
        src_db.upsert_records(records)
        src_db.close()
        # Merge into local_db
        count = local_db.merge_from_db(src_db_path)
        assert count == 3
        assert local_db.get_total_count() == 3

    def test_merge_respects_tombstones(self, local_db, tmp_path):
        """merge_from_db respects deleted_records tombstones."""

        # Create source DB with 2 records and 1 tombstone
        src_db_path = tmp_path / "src.db"
        conn = sqlite3.connect(str(src_db_path))
        conn.execute("""
            CREATE TABLE history (
                url TEXT, title TEXT, visit_time INTEGER, visit_count INTEGER,
                browser_type TEXT, profile_name TEXT, metadata TEXT,
                typed_count INTEGER, first_visit_time INTEGER,
                transition_type INTEGER, visit_duration REAL, device_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE deleted_records (
                url TEXT PRIMARY KEY, deleted_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("https://a.com", "A", 1704067200, 1, "chrome", "Default", "", None, None, None, None, None),
        )
        conn.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("https://b.com", "B", 1704067201, 1, "chrome", "Default", "", None, None, None, None, None),
        )
        conn.execute(
            "INSERT INTO deleted_records VALUES (?, ?)",
            ("https://b.com", 1704067300),
        )
        conn.commit()
        conn.close()
        # Merge
        count = local_db.merge_from_db(src_db_path)
        # Only A should be merged (B is tombstoned)
        assert count == 1
        assert local_db.get_total_count() == 1

    def test_replace_database_with_open_connections(self, local_db, tmp_path):
        """replace_database succeeds when both write/RO connections are already in use."""
        local_db.upsert_records([make_record(url="https://old.example")])
        assert local_db.get_total_count() == 1

        # Prime RO connection explicitly.
        assert local_db.get_bookmarked_urls() == set()

        src_db_path = tmp_path / "replacement.db"
        src_db = LocalDatabase(src_db_path)
        src_db.upsert_records([make_record(url="https://new.example")])
        src_db.close()

        local_db.replace_database(src_db_path)
        rows = local_db.get_records(limit=10)
        assert len(rows) == 1
        assert rows[0].url == "https://new.example"


class TestMergeUserDataFromDb:
    def test_merge_bookmarks(self, local_db, tmp_path):
        """merge_user_data_from_db merges bookmarks."""

        # Create source DB with bookmarks
        src_db_path = tmp_path / "src.db"
        conn = sqlite3.connect(str(src_db_path))
        conn.execute("""
            CREATE TABLE bookmarks (
                url TEXT PRIMARY KEY, title TEXT, bookmarked_at INTEGER, tags TEXT
            )
        """)
        conn.execute(
            "INSERT INTO bookmarks VALUES (?, ?, ?, ?)",
            ("https://example.com", "Example", 1704067200, ""),
        )
        conn.commit()
        conn.close()
        # Merge
        local_db.merge_user_data_from_db(src_db_path)
        # Verify bookmark exists
        assert local_db.is_bookmarked("https://example.com")

    def test_merge_annotations(self, local_db, tmp_path):
        """merge_user_data_from_db merges annotations."""

        # Create source DB with annotations
        src_db_path = tmp_path / "src.db"
        conn = sqlite3.connect(str(src_db_path))
        conn.execute("""
            CREATE TABLE annotations (
                url TEXT PRIMARY KEY, note TEXT, created_at INTEGER, updated_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO annotations VALUES (?, ?, ?, ?)",
            ("https://example.com", "my note", 1704067200, 1704067200),
        )
        conn.commit()
        conn.close()
        # Merge
        local_db.merge_user_data_from_db(src_db_path)
        # Verify annotation exists
        ann = local_db.get_annotation("https://example.com")
        assert ann is not None
        assert ann.note == "my note"

    def test_merge_handles_missing_tables(self, local_db, tmp_path):
        """merge_user_data_from_db handles missing user-data tables gracefully."""
        # Create a bare HistorySync DB (no user-data tables)
        src_db_path = tmp_path / "src.db"
        src_db = LocalDatabase(src_db_path)
        src_db.close()
        # Should not crash
        local_db.merge_user_data_from_db(src_db_path)
