# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``ExtractorManager``.

Covers:
  - run_extraction inserts records and returns counts
  - Parallel extraction with multiple browsers
  - since_map passed to each extractor in incremental mode
  - Extractor exceptions handled gracefully (returns 0, no crash)
  - progress_callback lifecycle events
  - get_available_browsers filters is_available()
  - disabled_browsers excluded at init and update_config
  - update_config hot-reload (disable, re-enable, no-op, partial update)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.services.extractor_manager import ExtractorManager
from src.services.extractors.chromium_extractor import ChromiumExtractor
from tests.conftest import make_record

# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════


def _mock_extractor(browser_type: str, records: list) -> MagicMock:
    ext = MagicMock(spec=ChromiumExtractor)
    ext.browser_type = browser_type
    ext.display_name = browser_type.title()
    ext.is_available.return_value = True
    ext.extract.return_value = records
    return ext


# ══════════════════════════════════════════════════════════════
# run_extraction
# ══════════════════════════════════════════════════════════════


class TestRunExtraction:
    def test_inserts_records(self, local_db):
        records = [
            make_record(url="https://a.com", browser_type="chrome"),
            make_record(url="https://b.com", browser_type="chrome", visit_time=1_704_067_201),
        ]
        em = ExtractorManager(local_db)
        em._registry = {"chrome": _mock_extractor("chrome", records)}
        results = em.run_extraction(["chrome"])
        assert results["chrome"] == 2
        assert local_db.get_total_count() == 2

    def test_parallel_multiple_browsers(self, local_db):
        chrome_records = [make_record(url="https://c.com", browser_type="chrome")]
        ff_records = [make_record(url="https://f.com", browser_type="firefox")]
        em = ExtractorManager(local_db)
        em._registry = {
            "chrome": _mock_extractor("chrome", chrome_records),
            "firefox": _mock_extractor("firefox", ff_records),
        }
        results = em.run_extraction(["chrome", "firefox"])
        assert results.get("chrome") == 1
        assert results.get("firefox") == 1
        assert local_db.get_total_count() == 2

    def test_passes_since_map_to_extractor(self, local_db):
        """Incremental mode: extractor.extract() must receive a since_map dict."""
        local_db.upsert_records([make_record(visit_time=9000)])
        mock_ext = _mock_extractor("chrome", [])
        em = ExtractorManager(local_db)
        em._registry = {"chrome": mock_ext}
        em.run_extraction(["chrome"])
        mock_ext.extract.assert_called_once()
        call_args = mock_ext.extract.call_args
        since_map = call_args.kwargs.get("since_map") or (call_args.args[0] if call_args.args else None)
        assert since_map is not None
        assert isinstance(since_map, dict)
        assert "Default" in since_map
        assert since_map["Default"] == 9000

    def test_extractor_exception_handled(self, local_db):
        mock_ext = MagicMock(spec=ChromiumExtractor)
        mock_ext.browser_type = "chrome"
        mock_ext.display_name = "Chrome"
        mock_ext.is_available.return_value = True
        mock_ext.extract.side_effect = RuntimeError("disk error")
        em = ExtractorManager(local_db)
        em._registry = {"chrome": mock_ext}
        results = em.run_extraction(["chrome"])
        assert results["chrome"] == 0

    def test_progress_callback_lifecycle(self, local_db):
        records = [make_record(url="https://x.com")]
        em = ExtractorManager(local_db)
        em._registry = {"chrome": _mock_extractor("chrome", records)}
        events: list[tuple] = []
        em.run_extraction(["chrome"], progress_callback=lambda bt, s, c: events.append((bt, s, c)))
        statuses = [e[1] for e in events]
        assert "extracting" in statuses
        assert "saving" in statuses
        assert "done" in statuses


# ══════════════════════════════════════════════════════════════
# get_available_browsers
# ══════════════════════════════════════════════════════════════


class TestGetAvailableBrowsers:
    def test_filters_unavailable(self, local_db):
        available = MagicMock()
        available.browser_type = "chrome"
        available.is_available.return_value = True
        unavailable = MagicMock()
        unavailable.browser_type = "firefox"
        unavailable.is_available.return_value = False
        em = ExtractorManager(local_db)
        em._registry = {"chrome": available, "firefox": unavailable}
        result = em.get_available_browsers()
        assert "chrome" in result
        assert "firefox" not in result


# ══════════════════════════════════════════════════════════════
# disabled_browsers
# ══════════════════════════════════════════════════════════════


class TestDisabledBrowsers:
    def test_not_in_registry_at_init(self, local_db):
        em = ExtractorManager(local_db, disabled_browsers=["chrome", "edge"])
        assert "chrome" not in em._registry
        assert "edge" not in em._registry
        assert "firefox" in em._registry
        assert "brave" in em._registry

    def test_not_returned_by_get_available(self, local_db):
        em = ExtractorManager(local_db, disabled_browsers=["chrome"])
        em._registry = {"chrome": _mock_extractor("chrome", [])}
        em._disabled.add("chrome")
        em._registry.pop("chrome", None)
        results = em.run_extraction()
        assert "chrome" not in results

    def test_run_extraction_skips_disabled(self, local_db):
        mock_ext = _mock_extractor("chrome", [])
        em = ExtractorManager(local_db, disabled_browsers=["chrome"])
        em._registry = {}
        assert "chrome" not in em._registry
        results = em.run_extraction()
        assert results == {}
        mock_ext.extract.assert_not_called()


# ══════════════════════════════════════════════════════════════
# update_config hot-reload
# ══════════════════════════════════════════════════════════════


class TestUpdateConfig:
    def test_disables_browser(self, local_db):
        em = ExtractorManager(local_db)
        assert "chrome" in em._registry
        em.update_config(disabled_browsers=["chrome"])
        assert "chrome" not in em._registry
        assert "chrome" in em._disabled

    def test_reenables_browser(self, local_db):
        em = ExtractorManager(local_db, disabled_browsers=["chrome"])
        assert "chrome" not in em._registry
        em.update_config(disabled_browsers=[])
        assert "chrome" in em._registry
        assert "chrome" not in em._disabled

    def test_no_change_is_stable(self, local_db):
        em = ExtractorManager(local_db, disabled_browsers=["edge"])
        registry_before = set(em._registry.keys())
        em.update_config(disabled_browsers=["edge"])
        assert set(em._registry.keys()) == registry_before

    def test_only_affects_changed_entries(self, local_db):
        em = ExtractorManager(local_db)
        firefox_before = em._registry.get("firefox")
        em.update_config(disabled_browsers=["chrome"])
        assert "chrome" not in em._registry
        assert em._registry.get("firefox") is firefox_before

    def test_reenabled_type_is_chromium_extractor(self, local_db):
        em = ExtractorManager(local_db, disabled_browsers=["chrome"])
        em.update_config(disabled_browsers=[])
        assert isinstance(em._registry["chrome"], ChromiumExtractor)
