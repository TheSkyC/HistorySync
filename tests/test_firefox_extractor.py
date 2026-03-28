# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``FirefoxExtractor`` and Firefox profile-discovery helpers.

Sections:
  - FirefoxExtractor: basic extraction, internal URL filtering, incremental
    extraction, metadata, timestamp conversion, browser_type propagation
  - TestFirefoxProfileParsing: single/multi profile discovery, missing DB
    skipped, duplicate path deduplication, is_history_available(),
    _parse_firefox_profiles_ini() directly
"""

from __future__ import annotations

from pathlib import Path

from src.services.browser_defs import BrowserDef, _parse_firefox_profiles_ini
from src.services.extractors.firefox_extractor import (
    FirefoxExtractor,
    unix_to_firefox_time,
)
from tests.conftest import create_firefox_db

# ══════════════════════════════════════════════════════════════
# Helper factories
# ══════════════════════════════════════════════════════════════


def _make_firefox_extractor(db_path: Path, profile_name: str = "default-release") -> FirefoxExtractor:
    """
    Wire up a ``FirefoxExtractor`` pointing at *db_path* via a minimal
    profiles.ini, without touching real system paths.
    """
    base_dir = db_path.parent
    ini_path = base_dir / "profiles.ini"
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


def _ff_ts(unix_sec: int) -> int:
    return unix_to_firefox_time(unix_sec)


# ══════════════════════════════════════════════════════════════
# FirefoxExtractor
# ══════════════════════════════════════════════════════════════


class TestFirefoxExtractor:
    def test_basic_extraction(self, tmp_path: Path):
        db = tmp_path / "places.sqlite"
        create_firefox_db(
            db,
            [
                ("https://mozilla.org", "Mozilla", _ff_ts(1_704_067_200), 3, "Browser maker"),
                ("https://python.org", "Python", _ff_ts(1_704_067_300), 1, ""),
            ],
        )
        records = _make_firefox_extractor(db).extract()
        assert len(records) == 2

    def test_internal_urls_filtered(self, tmp_path: Path):
        db = tmp_path / "places.sqlite"
        create_firefox_db(
            db,
            [
                ("about:config", "Config", _ff_ts(1_704_067_200), 1, ""),
                ("place:sort=8&maxResults", "Places", _ff_ts(1_704_067_201), 1, ""),
                ("https://firefox.com", "Firefox", _ff_ts(1_704_067_202), 1, ""),
            ],
        )
        records = _make_firefox_extractor(db).extract()
        assert len(records) == 1
        assert records[0].url == "https://firefox.com"

    def test_incremental_extraction(self, tmp_path: Path):
        base_ts = 1_704_067_200
        db = tmp_path / "places.sqlite"
        create_firefox_db(
            db,
            [
                ("https://old.com", "Old", _ff_ts(base_ts - 1000), 1, ""),
                ("https://new.com", "New", _ff_ts(base_ts + 1000), 1, ""),
            ],
        )
        ext = _make_firefox_extractor(db, profile_name="default-release")
        records = ext.extract(since_map={"default-release": base_ts})
        assert len(records) == 1
        assert records[0].url == "https://new.com"

    def test_metadata_captured(self, tmp_path: Path):
        db = tmp_path / "places.sqlite"
        create_firefox_db(db, [("https://mdn.org", "MDN", _ff_ts(1_704_067_200), 1, "Web docs")])
        records = _make_firefox_extractor(db).extract()
        assert records[0].metadata == "Web docs"

    def test_visit_time_converted_correctly(self, tmp_path: Path):
        unix_ts = 1_704_067_200
        db = tmp_path / "places.sqlite"
        create_firefox_db(db, [("https://x.com", "X", _ff_ts(unix_ts), 1, "")])
        records = _make_firefox_extractor(db).extract()
        assert records[0].visit_time == unix_ts

    def test_browser_type_propagated(self, tmp_path: Path):
        db = tmp_path / "places.sqlite"
        create_firefox_db(db, [("https://x.com", "X", _ff_ts(1_704_067_200), 1, "")])
        records = _make_firefox_extractor(db).extract()
        assert records[0].browser_type == "firefox_test"


# ══════════════════════════════════════════════════════════════
# Profile discovery
# ══════════════════════════════════════════════════════════════


class TestFirefoxProfileParsing:
    """
    Tests for Firefox multi-profile path discovery.

    All assertions go through the public ``BrowserDef`` API or the
    module-level ``_parse_firefox_profiles_ini`` helper.
    """

    def _make_defn(self, base: Path) -> BrowserDef:
        return BrowserDef(
            browser_type="firefox_test",
            display_name="Firefox Test",
            engine="firefox",
            _data_dirs=(base,),
        )

    def _make_profile_with_db(self, base: Path, rel_path: str) -> Path:
        profile_dir = base / rel_path
        profile_dir.mkdir(parents=True, exist_ok=True)
        db = profile_dir / "places.sqlite"
        create_firefox_db(db, [])
        return db

    def test_single_profile_discovered(self, tmp_path: Path):
        self._make_profile_with_db(tmp_path, "abc123.default-release")
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=default-release\nIsRelative=1\nPath=abc123.default-release\n",
            encoding="utf-8",
        )
        paths = list(self._make_defn(tmp_path).iter_history_db_paths())
        assert len(paths) == 1
        assert paths[0][0] == "default-release"

    def test_multiple_profiles_discovered(self, tmp_path: Path):
        self._make_profile_with_db(tmp_path, "prof1.default")
        self._make_profile_with_db(tmp_path, "prof2.work")
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=default\nIsRelative=1\nPath=prof1.default\n\n"
            "[Profile1]\nName=work\nIsRelative=1\nPath=prof2.work\n",
            encoding="utf-8",
        )
        paths = list(self._make_defn(tmp_path).iter_history_db_paths())
        assert len(paths) == 2
        names = {p[0] for p in paths}
        assert "default" in names
        assert "work" in names

    def test_missing_places_sqlite_skipped(self, tmp_path: Path):
        (tmp_path / "nodbprofile").mkdir()
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=nodbprofile\nIsRelative=1\nPath=nodbprofile\n",
            encoding="utf-8",
        )
        paths = list(self._make_defn(tmp_path).iter_history_db_paths())
        assert len(paths) == 0

    def test_duplicate_profile_path_deduplicated(self, tmp_path: Path):
        self._make_profile_with_db(tmp_path, "shared.default")
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=alpha\nIsRelative=1\nPath=shared.default\n\n"
            "[Profile1]\nName=beta\nIsRelative=1\nPath=shared.default\n",
            encoding="utf-8",
        )
        paths = list(self._make_defn(tmp_path).iter_history_db_paths())
        assert len(paths) == 1

    def test_is_history_available_true(self, tmp_path: Path):
        self._make_profile_with_db(tmp_path, "prof.default")
        (tmp_path / "profiles.ini").write_text(
            "[Profile0]\nName=default\nIsRelative=1\nPath=prof.default\n",
            encoding="utf-8",
        )
        assert self._make_defn(tmp_path).is_history_available()

    def test_is_history_available_false_no_ini(self, tmp_path: Path):
        defn = BrowserDef(
            browser_type="firefox_test",
            display_name="Firefox Test",
            engine="firefox",
            _data_dirs=(tmp_path / "nonexistent",),
        )
        assert not defn.is_history_available()

    def test_parse_firefox_profiles_ini_direct(self, tmp_path: Path):
        """Directly test the module-level helper with different db_filename values."""
        profile_dir = tmp_path / "p1.default"
        profile_dir.mkdir()
        create_firefox_db(profile_dir / "places.sqlite", [])

        ini_path = tmp_path / "profiles.ini"
        ini_path.write_text(
            "[Profile0]\nName=default\nIsRelative=1\nPath=p1.default\n",
            encoding="utf-8",
        )

        results_history = list(_parse_firefox_profiles_ini(tmp_path, ini_path, "places.sqlite"))
        assert len(results_history) == 1
        assert results_history[0][1].name == "places.sqlite"

        results_favicon = list(_parse_firefox_profiles_ini(tmp_path, ini_path, "favicons.sqlite"))
        assert len(results_favicon) == 0
