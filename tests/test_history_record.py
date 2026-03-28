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
