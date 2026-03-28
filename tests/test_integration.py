# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
End-to-end integration test: incremental two-run extraction.

Simulates two consecutive sync cycles with a Chromium browser database:
  1. First run imports all existing records.
  2. Second run imports *only* records added since the last sync.
"""

from __future__ import annotations

from pathlib import Path

from src.services.extractors.chromium_extractor import (
    ChromiumExtractor,
    unix_to_chromium_time,
)
from tests.conftest import create_chromium_db


class TestIncrementalExtractionIntegration:
    def test_second_run_only_inserts_new_records(self, tmp_path: Path, local_db):
        base_ts = 1_704_067_200
        browser_db = tmp_path / "History"

        # ── First sync: 2 records ──────────────────────────────
        create_chromium_db(
            browser_db,
            [
                ("https://a.com", "A", unix_to_chromium_time(base_ts), 1),
                ("https://b.com", "B", unix_to_chromium_time(base_ts + 1), 1),
            ],
        )
        ext = ChromiumExtractor.for_custom_path("chrome_test", "Chrome Test", browser_db)
        since_map1 = local_db.get_max_visit_times("chrome_test")  # {}
        records1 = ext.extract(since_map=since_map1)
        n1 = local_db.upsert_records(records1)
        assert n1 == 2

        # ── Second sync: one new record added ──────────────────
        create_chromium_db(
            browser_db,
            [
                ("https://a.com", "A", unix_to_chromium_time(base_ts), 1),
                ("https://b.com", "B", unix_to_chromium_time(base_ts + 1), 1),
                ("https://c.com", "C", unix_to_chromium_time(base_ts + 2), 1),  # new
            ],
        )
        since_map2 = local_db.get_max_visit_times("chrome_test")
        assert since_map2.get("custom") == base_ts + 1

        records2 = ext.extract(since_map=since_map2)
        assert len(records2) == 1
        assert records2[0].url == "https://c.com"

        n2 = local_db.upsert_records(records2)
        assert n2 == 1
        assert local_db.get_total_count() == 3
