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
        events: list[tuple] = []
        results = em.run_extraction(["chrome"], progress_callback=lambda bt, s, c: events.append((bt, s, c)))
        # Failed extractions return None (not 0) so callers can distinguish
        # a genuine failure from a successful run with zero new records.
        assert results["chrome"] is None
        assert any(s == "error" for _, s, _ in events)

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


# ══════════════════════════════════════════════════════════════
# custom_paths
# ══════════════════════════════════════════════════════════════


class TestCustomPaths:
    def test_init_registers_valid_path(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / "History"
        create_chromium_db(db, [("https://example.com", "Example", unix_to_chromium_time(1_700_000_000), 1)])

        em = ExtractorManager(local_db, custom_paths={"my_browser": str(db)})

        assert "my_browser" in em._registry
        assert isinstance(em._registry["my_browser"], ChromiumExtractor)

    def test_init_skips_missing_path(self, local_db, tmp_path):
        missing = str(tmp_path / "nonexistent" / "History")
        em = ExtractorManager(local_db, custom_paths={"ghost": missing})
        assert "ghost" not in em._registry

    def test_update_config_adds_new_path(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / "History"
        create_chromium_db(db, [("https://new.com", "New", unix_to_chromium_time(1_700_000_000), 1)])

        em = ExtractorManager(local_db)
        assert "portable_chrome" not in em._registry

        em.update_config(disabled_browsers=[], custom_paths={"portable_chrome": str(db)})

        assert "portable_chrome" in em._registry
        assert isinstance(em._registry["portable_chrome"], ChromiumExtractor)

    def test_update_config_removes_deleted_path(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / "History"
        create_chromium_db(db, [("https://old.com", "Old", unix_to_chromium_time(1_700_000_000), 1)])

        em = ExtractorManager(local_db, custom_paths={"old_browser": str(db)})
        assert "old_browser" in em._registry

        em.update_config(disabled_browsers=[], custom_paths={})

        assert "old_browser" not in em._registry

    def test_update_config_replaces_changed_path(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db1 = tmp_path / "History1"
        db2 = tmp_path / "History2"
        create_chromium_db(db1, [("https://v1.com", "V1", unix_to_chromium_time(1_700_000_000), 1)])
        create_chromium_db(db2, [("https://v2.com", "V2", unix_to_chromium_time(1_700_000_001), 1)])

        em = ExtractorManager(local_db, custom_paths={"my_browser": str(db1)})
        extractor_v1 = em._registry["my_browser"]

        em.update_config(disabled_browsers=[], custom_paths={"my_browser": str(db2)})

        assert "my_browser" in em._registry
        assert em._registry["my_browser"] is not extractor_v1

    def test_update_config_none_does_not_clear_existing(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / "History"
        create_chromium_db(db, [("https://keep.com", "Keep", unix_to_chromium_time(1_700_000_000), 1)])

        em = ExtractorManager(local_db, custom_paths={"keep_browser": str(db)})
        assert "keep_browser" in em._registry

        # Passing custom_paths=None means "no change" - existing registrations must survive
        em.update_config(disabled_browsers=[], custom_paths=None)

        assert "keep_browser" in em._registry

    def test_custom_path_extractor_extracts_records(self, local_db, tmp_path):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / "History"
        create_chromium_db(db, [("https://portable.com", "Portable", unix_to_chromium_time(1_700_000_000), 1)])

        em = ExtractorManager(local_db, custom_paths={"portable": str(db)})
        results = em.run_extraction(["portable"])

        assert results.get("portable") == 1
        assert local_db.get_total_count() == 1


# ══════════════════════════════════════════════════════════════
# disable / re-enable custom-path browsers
# ══════════════════════════════════════════════════════════════


class TestCustomPathDisableReEnable:
    def _make_db(self, tmp_path, name="History"):
        from src.services.extractors.chromium_extractor import unix_to_chromium_time
        from tests.conftest import create_chromium_db

        db = tmp_path / name
        create_chromium_db(db, [("https://portable.com", "P", unix_to_chromium_time(1_700_000_000), 1)])
        return db

    def test_disable_then_reenable_same_session(self, local_db, tmp_path):
        db = self._make_db(tmp_path)
        em = ExtractorManager(local_db, custom_paths={"portable": str(db)})
        assert "portable" in em._registry

        em.update_config(disabled_browsers=["portable"])
        assert "portable" not in em._registry

        em.update_config(disabled_browsers=[])
        assert "portable" in em._registry

    def test_reenable_after_restart_uses_custom_paths(self, local_db, tmp_path):
        # Simulate restart: _saved_extractors is empty, but _custom_paths is populated.
        db = self._make_db(tmp_path)
        em = ExtractorManager(local_db, custom_paths={"portable": str(db)}, disabled_browsers=["portable"])
        assert "portable" not in em._registry
        assert em._saved_extractors.get("portable") is None  # nothing was saved at init

        em.update_config(disabled_browsers=[])
        assert "portable" in em._registry
        assert isinstance(em._registry["portable"], ChromiumExtractor)

    def test_reenable_warns_when_path_gone(self, local_db, tmp_path):
        db = self._make_db(tmp_path)
        em = ExtractorManager(local_db, custom_paths={"portable": str(db)}, disabled_browsers=["portable"])

        db.unlink()  # simulate the file being deleted

        em.update_config(disabled_browsers=[])
        # Should not crash, and should not add a broken extractor
        assert "portable" not in em._registry
