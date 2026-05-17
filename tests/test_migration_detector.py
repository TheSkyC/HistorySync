# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for migration_detector.detect_legacy_installation()."""

from __future__ import annotations

import json
from pathlib import Path
import unittest.mock

import pytest

from src.utils.migration_detector import detect_legacy_installation


@pytest.fixture()
def _patch_dirs(tmp_path: Path):
    """Redirect config/data dir lookups to tmp_path."""
    with (
        unittest.mock.patch(
            "src.utils.path_helper.get_config_dir",
            return_value=tmp_path,
        ),
        unittest.mock.patch(
            "src.utils.path_helper.get_app_data_dir",
            return_value=tmp_path,
        ),
        unittest.mock.patch(
            "src.utils.migration_detector._default_config_dir",
            return_value=tmp_path,
        ),
        unittest.mock.patch(
            "src.utils.migration_detector._default_data_dir",
            return_value=tmp_path,
        ),
    ):
        yield tmp_path


class TestMigrationDetector:
    def test_no_config_file_returns_not_found(self, _patch_dirs: Path):
        result = detect_legacy_installation()
        assert not result.found

    def test_first_run_completed_true_returns_not_found(self, _patch_dirs: Path):
        (_patch_dirs / "config.json").write_text(json.dumps({"first_run_completed": True}), encoding="utf-8")
        result = detect_legacy_installation()
        assert not result.found

    def test_config_version_2_returns_not_found(self, _patch_dirs: Path):
        (_patch_dirs / "config.json").write_text(json.dumps({"config_version": 2}), encoding="utf-8")
        result = detect_legacy_installation()
        assert not result.found

    def test_config_version_higher_than_2_returns_not_found(self, _patch_dirs: Path):
        (_patch_dirs / "config.json").write_text(json.dumps({"config_version": 99}), encoding="utf-8")
        result = detect_legacy_installation()
        assert not result.found

    def test_corrupt_config_returns_parse_error(self, _patch_dirs: Path):
        (_patch_dirs / "config.json").write_text("NOT JSON{{", encoding="utf-8")
        result = detect_legacy_installation()
        assert result.parse_error
        assert not result.found
