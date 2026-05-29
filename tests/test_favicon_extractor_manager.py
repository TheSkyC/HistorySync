# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from src.services import browser_defs
from src.services.browser_defs import (
    BrowserDef,
    DirectPathBrowserDef,
    get_browser_def,
    register_config_browsers,
    unregister_browser_def,
)
from src.services.favicon_extractor_manager import FaviconExtractorManager


class TestFaviconExtractorManagerRuntime:
    def test_firefox_custom_path_uses_sibling_favicons_db(self, tmp_path):
        profile_dir = tmp_path / "firefox-profile"
        profile_dir.mkdir()
        history_db = profile_dir / "places.sqlite"
        favicon_db = profile_dir / "favicons.sqlite"
        history_db.write_bytes(b"")
        favicon_db.write_bytes(b"")

        mgr = FaviconExtractorManager(custom_paths={"firefox": str(history_db)})

        available = mgr.get_available(["firefox"])

        assert len(available) == 1
        assert isinstance(get_browser_def("firefox"), DirectPathBrowserDef)
        unregister_browser_def("firefox")

    def test_init_registers_persisted_learned_browser(self):
        learned = {
            "detected_demo": {
                "display_name": "Detected Demo",
                "engine": "chromium",
                "data_dir": "C:/tmp/detected_demo/User Data",
            }
        }
        register_config_browsers(learned_browsers=learned, custom_browsers={})

        mgr = FaviconExtractorManager(learned_browsers=learned)

        assert mgr.get_all_registered()["detected_demo"] == "Detected Demo"
        unregister_browser_def("detected_demo")

    def test_init_registers_persisted_custom_browser(self, tmp_path):
        history_db = tmp_path / "History"
        history_db.write_bytes(b"")
        custom_browsers = {
            "portable_demo": {
                "display_name": "Portable Demo",
                "engine": "chromium",
                "path": str(history_db),
            }
        }
        register_config_browsers(learned_browsers={}, custom_browsers=custom_browsers)

        mgr = FaviconExtractorManager(custom_paths={"portable_demo": str(history_db)})

        assert mgr.get_all_registered()["portable_demo"] == "Portable Demo"
        unregister_browser_def("portable_demo")

    def test_update_config_removes_deleted_learned_browser(self):
        learned = {
            "detected_demo": {
                "display_name": "Detected Demo",
                "engine": "chromium",
                "data_dir": "C:/tmp/detected_demo/User Data",
            }
        }
        register_config_browsers(learned_browsers=learned, custom_browsers={})
        mgr = FaviconExtractorManager(learned_browsers=learned)
        assert "detected_demo" in mgr.get_all_registered()

        mgr.update_config(disabled_browsers=[], learned_browsers={}, custom_paths={})

        assert "detected_demo" not in mgr.get_all_registered()
        assert get_browser_def("detected_demo") is None
        unregister_browser_def("detected_demo")

    def test_update_config_removes_deleted_custom_browser_runtime_def(self, tmp_path):
        history_db = tmp_path / "History"
        history_db.write_bytes(b"")
        custom_browsers = {
            "portable_demo": {
                "display_name": "Portable Demo",
                "engine": "chromium",
                "path": str(history_db),
            }
        }
        register_config_browsers(learned_browsers={}, custom_browsers=custom_browsers)
        mgr = FaviconExtractorManager(custom_paths={"portable_demo": str(history_db)})

        assert isinstance(get_browser_def("portable_demo"), DirectPathBrowserDef)

        mgr.update_config(disabled_browsers=[], learned_browsers={}, custom_paths={})

        assert "portable_demo" not in mgr.get_all_registered()
        assert get_browser_def("portable_demo") is None

    def test_update_config_restores_builtin_def_after_custom_override_removed(self, tmp_path):
        history_db = tmp_path / "History"
        history_db.write_bytes(b"")
        custom_browsers = {
            "chrome": {
                "display_name": "Portable Chrome",
                "engine": "chromium",
                "path": str(history_db),
            }
        }
        register_config_browsers(learned_browsers={}, custom_browsers=custom_browsers)
        mgr = FaviconExtractorManager(custom_paths={"chrome": str(history_db)})

        assert isinstance(get_browser_def("chrome"), DirectPathBrowserDef)

        mgr.update_config(disabled_browsers=[], learned_browsers={}, custom_paths={})

        assert "chrome" in mgr.get_all_registered()
        assert not isinstance(get_browser_def("chrome"), DirectPathBrowserDef)

    def test_invalid_builtin_override_falls_back_to_builtin_availability(self, tmp_path):
        builtin_root = tmp_path / "chrome-user-data"
        default_profile = builtin_root / "Default"
        default_profile.mkdir(parents=True)
        (default_profile / "Favicons").write_bytes(b"")
        missing_history = tmp_path / "missing" / "History"

        fake_builtin = BrowserDef(
            browser_type="chrome",
            display_name="Google Chrome",
            engine="chromium",
            _data_dirs=(builtin_root,),
        )

        chrome_index = next(i for i, defn in enumerate(browser_defs.BUILTIN_BROWSERS) if defn.browser_type == "chrome")
        original_builtin = browser_defs.BUILTIN_BROWSERS[chrome_index]
        original_builtin_map = browser_defs._BUILTIN_BROWSER_DEF_MAP["chrome"]
        original_runtime = browser_defs.BROWSER_DEF_MAP["chrome"]
        browser_defs.BUILTIN_BROWSERS[chrome_index] = fake_builtin
        browser_defs._BUILTIN_BROWSER_DEF_MAP["chrome"] = fake_builtin
        browser_defs.BROWSER_DEF_MAP["chrome"] = fake_builtin

        try:
            mgr = FaviconExtractorManager(custom_paths={"chrome": str(missing_history)})

            available = mgr.get_available(["chrome"])

            assert len(available) == 1
            assert get_browser_def("chrome") is fake_builtin
            assert not isinstance(get_browser_def("chrome"), DirectPathBrowserDef)
        finally:
            browser_defs.BUILTIN_BROWSERS[chrome_index] = original_builtin
            browser_defs._BUILTIN_BROWSER_DEF_MAP["chrome"] = original_builtin_map
            browser_defs.BROWSER_DEF_MAP["chrome"] = original_runtime

    def test_safari_custom_path_does_not_register_unsupported_favicon_extractor(self, tmp_path):
        safari_dir = tmp_path / "safari"
        safari_dir.mkdir()
        history_db = safari_dir / "History.db"
        history_db.write_bytes(b"")
        (safari_dir / "Favicons").write_bytes(b"")

        mgr = FaviconExtractorManager(custom_paths={"safari": str(history_db)})

        assert mgr.get_available(["safari"]) == []
        assert "safari" not in mgr.get_all_registered()
