# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``AppConfig`` persistence.

Covers:
  - Save / load round-trip
  - Saved file is valid JSON
  - No .tmp files left after save
  - Defaults returned when no config file exists
  - Corrupt JSON handled gracefully
  - Missing fields use defaults
  - WebDavConfig nested serialisation
  - get_db_path (default and custom)
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest.mock

import pytest

from src.models.app_config import AppConfig, WebDavConfig


@pytest.fixture(autouse=True)
def _patch_config_dirs(tmp_path: Path):
    """Redirect all config/data dir lookups to the test's temp directory."""
    patches = [
        unittest.mock.patch("src.models.app_config._resolve_config_dir", return_value=tmp_path),
        unittest.mock.patch("src.models.app_config._resolve_data_dir", return_value=tmp_path),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


class TestAppConfigPersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        cfg = AppConfig()
        cfg.window_width = 1280
        cfg.window_height = 800
        cfg.webdav.url = "https://dav.example.com"
        cfg.scheduler.sync_interval_hours = 12
        cfg.save()

        loaded = AppConfig.load()
        assert loaded.window_width == 1280
        assert loaded.window_height == 800
        assert loaded.webdav.url == "https://dav.example.com"
        assert loaded.scheduler.sync_interval_hours == 12

    def test_save_produces_valid_json(self, tmp_path: Path):
        AppConfig().save()
        raw = (tmp_path / "config.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert "webdav" in parsed
        assert "scheduler" in parsed

    def test_no_tmp_files_left_after_save(self, tmp_path: Path):
        AppConfig().save()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_defaults_when_no_file(self):
        cfg = AppConfig.load()
        assert cfg.window_width == 1100
        assert not cfg.webdav.enabled

    def test_corrupt_json_returns_defaults(self, tmp_path: Path):
        (tmp_path / "config.json").write_text("NOT JSON{{", encoding="utf-8")
        cfg = AppConfig.load()
        assert isinstance(cfg, AppConfig)

    def test_missing_fields_use_defaults(self, tmp_path: Path):
        (tmp_path / "config.json").write_text(json.dumps({"window_width": 900}), encoding="utf-8")
        cfg = AppConfig.load()
        assert cfg.window_width == 900
        assert cfg.window_height == 700  # default

    def test_webdav_config_roundtrip(self, tmp_path: Path):
        cfg = AppConfig()
        cfg.webdav = WebDavConfig(
            enabled=True,
            url="https://cloud.com/dav",
            username="alice",
            password="secret",
            max_backups=5,
        )
        cfg.save()
        loaded = AppConfig.load()
        assert loaded.webdav.enabled
        assert loaded.webdav.url == "https://cloud.com/dav"
        assert loaded.webdav.username == "alice"
        assert loaded.webdav.max_backups == 5

    def test_get_db_path_default(self):
        cfg = AppConfig()
        assert cfg.get_db_path().name == "history.db"

    def test_get_db_path_custom(self):
        cfg = AppConfig()
        cfg.db_path = "/custom/path/my.db"
        assert cfg.get_db_path() == Path("/custom/path/my.db")
