# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the ``HistoryRecord`` dataclass.

Covers:
  - dedup_key format and browser discrimination
  - default metadata value
  - id field excluded from equality comparison
"""

from __future__ import annotations

from tests.conftest import make_record


class TestHistoryRecord:
    def test_dedup_key_format(self):
        r = make_record(browser_type="edge", url="https://x.com", visit_time=12345)
        assert r.dedup_key() == "edge|https://x.com|12345"

    def test_dedup_key_distinguishes_browsers(self):
        r1 = make_record(browser_type="chrome")
        r2 = make_record(browser_type="firefox")
        assert r1.dedup_key() != r2.dedup_key()

    def test_default_metadata_empty(self):
        r = make_record()
        assert r.metadata == ""

    def test_id_not_in_equality(self):
        """``id`` is declared with ``compare=False``; it must not affect ``==``."""
        r1 = make_record()
        r2 = make_record()
        r1.id = 1
        r2.id = 99
        assert r1 == r2


class TestBookmarkRecord:
    def test_default_tags_empty(self):
        """Default tags is empty list."""
        from src.models.history_record import BookmarkRecord

        bm = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000)
        assert bm.tags == []

    def test_tags_str_empty(self):
        """tags_str() returns empty string for empty tags."""
        from src.models.history_record import BookmarkRecord

        bm = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000, tags=[])
        assert bm.tags_str() == ""

    def test_tags_str_single(self):
        """tags_str() returns single tag."""
        from src.models.history_record import BookmarkRecord

        bm = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000, tags=["work"])
        assert bm.tags_str() == "work"

    def test_tags_str_multiple(self):
        """tags_str() joins multiple tags with comma."""
        from src.models.history_record import BookmarkRecord

        bm = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000, tags=["work", "ref"])
        assert bm.tags_str() == "work, ref"

    def test_id_not_in_equality(self):
        """id field has compare=False."""
        from src.models.history_record import BookmarkRecord

        bm1 = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000)
        bm2 = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000)
        bm1.id = 1
        bm2.id = 99
        assert bm1 == bm2

    def test_history_id_not_in_equality(self):
        """history_id field has compare=False."""
        from src.models.history_record import BookmarkRecord

        bm1 = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000, history_id=1)
        bm2 = BookmarkRecord(url="https://example.com", title="Example", bookmarked_at=1000, history_id=99)
        assert bm1 == bm2


class TestAnnotationRecord:
    def test_fields_stored(self):
        """AnnotationRecord stores all fields."""
        from src.models.history_record import AnnotationRecord

        ann = AnnotationRecord(url="https://example.com", note="my note", created_at=1000, updated_at=2000)
        assert ann.url == "https://example.com"
        assert ann.note == "my note"
        assert ann.created_at == 1000
        assert ann.updated_at == 2000

    def test_id_not_in_equality(self):
        """id field has compare=False."""
        from src.models.history_record import AnnotationRecord

        ann1 = AnnotationRecord(url="https://example.com", note="note", created_at=1000, updated_at=2000)
        ann2 = AnnotationRecord(url="https://example.com", note="note", created_at=1000, updated_at=2000)
        ann1.id = 1
        ann2.id = 99
        assert ann1 == ann2
