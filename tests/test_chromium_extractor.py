# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``ChromiumExtractor`` and the ``_is_internal_url`` filter.

Covers:
  - Basic extraction
  - Internal URL filtering (chrome://, edge://, about:, extensions, data:)
  - Incremental extraction (since_map)
  - Timestamp conversion correctness
  - browser_type and profile_name propagation
  - Missing DB returns empty list
  - is_available() reflects DB presence
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.extractors.chromium_extractor import (
    ChromiumExtractor,
    _is_internal_url as chromium_is_internal,
    unix_to_chromium_time,
)
from tests.conftest import create_chromium_db

# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════


def _make_extractor(db_path: Path, browser_type: str = "chrome_test") -> ChromiumExtractor:
    """Create a ``ChromiumExtractor`` via the ``for_custom_path`` factory."""
    return ChromiumExtractor.for_custom_path(
        browser_type=browser_type,
        display_name=browser_type.replace("_", " ").title(),
        db_path=db_path,
    )


def _ts(unix_sec: int) -> int:
    return unix_to_chromium_time(unix_sec)


# ══════════════════════════════════════════════════════════════
# ChromiumExtractor
# ══════════════════════════════════════════════════════════════


class TestChromiumExtractor:
    def test_basic_extraction(self, tmp_path: Path):
        db = tmp_path / "History"
        create_chromium_db(
            db,
            [
                ("https://github.com", "GitHub", _ts(1_704_067_200), 5),
                ("https://google.com", "Google", _ts(1_704_067_300), 10),
            ],
        )
        records = _make_extractor(db).extract()
        assert len(records) == 2
        urls = {r.url for r in records}
        assert "https://github.com" in urls
        assert "https://google.com" in urls

    def test_internal_urls_filtered(self, tmp_path: Path):
        db = tmp_path / "History"
        create_chromium_db(
            db,
            [
                ("chrome://settings", "Settings", _ts(1_704_067_200), 1),
                ("edge://newtab", "New Tab", _ts(1_704_067_201), 1),
                ("brave://newtab", "Brave New Tab", _ts(1_704_067_202), 1),
                ("about:blank", "Blank", _ts(1_704_067_203), 1),
                ("https://real.com", "Real", _ts(1_704_067_204), 1),
            ],
        )
        records = _make_extractor(db).extract()
        assert len(records) == 1
        assert records[0].url == "https://real.com"

    def test_incremental_only_new_records(self, tmp_path: Path):
        base_ts = 1_704_067_200
        db = tmp_path / "History"
        create_chromium_db(
            db,
            [
                ("https://old.com", "Old", _ts(base_ts - 1000), 1),
                ("https://new.com", "New", _ts(base_ts + 1000), 1),
            ],
        )
        records = _make_extractor(db).extract(since_map={"custom": base_ts})
        assert len(records) == 1
        assert records[0].url == "https://new.com"

    def test_zero_since_returns_all(self, tmp_path: Path):
        db = tmp_path / "History"
        create_chromium_db(
            db,
            [
                ("https://a.com", "A", _ts(1_704_067_200), 1),
                ("https://b.com", "B", _ts(1_704_067_300), 1),
            ],
        )
        assert len(_make_extractor(db).extract(since_map={"custom": 0})) == 2

    def test_visit_time_converted_correctly(self, tmp_path: Path):
        expected = 1_704_067_200
        db = tmp_path / "History"
        create_chromium_db(db, [("https://x.com", "X", _ts(expected), 1)])
        records = _make_extractor(db).extract()
        assert records[0].visit_time == expected

    def test_browser_type_propagated(self, tmp_path: Path):
        db = tmp_path / "History"
        create_chromium_db(db, [("https://x.com", "X", _ts(1_704_067_200), 1)])
        records = _make_extractor(db, browser_type="chrome_test").extract()
        assert records[0].browser_type == "chrome_test"

    def test_profile_name_is_custom(self, tmp_path: Path):
        """for_custom_path() always uses 'custom' as the profile name."""
        db = tmp_path / "History"
        create_chromium_db(db, [("https://x.com", "X", _ts(1_704_067_200), 1)])
        records = _make_extractor(db).extract()
        assert records[0].profile_name == "custom"

    def test_missing_db_returns_empty(self, tmp_path: Path):
        records = _make_extractor(tmp_path / "NonExistent").extract()
        assert records == []

    def test_is_available_true_when_db_exists(self, tmp_path: Path):
        db = tmp_path / "History"
        create_chromium_db(db, [])
        assert _make_extractor(db).is_available()

    def test_is_available_false_when_db_missing(self, tmp_path: Path):
        assert not _make_extractor(tmp_path / "Missing").is_available()


# ══════════════════════════════════════════════════════════════
# Internal URL filter
# ══════════════════════════════════════════════════════════════


class TestInternalUrlFilter:
    @pytest.mark.parametrize(
        "url",
        [
            "chrome://settings",
            "edge://newtab",
            "brave://newtab",
            "about:blank",
            "chrome-extension://abc123/page.html",
            "data:text/html,<h1>hi</h1>",
        ],
    )
    def test_internal_urls_filtered(self, url: str):
        assert chromium_is_internal(url)

    @pytest.mark.parametrize(
        "url",
        ["https://github.com", "http://example.com"],
    )
    def test_external_urls_not_filtered(self, url: str):
        assert not chromium_is_internal(url)
