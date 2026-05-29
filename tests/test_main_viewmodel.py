# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.app_config import AppConfig
from src.viewmodels.main_viewmodel import MainViewModel


@pytest.fixture(autouse=True)
def _patch_config_dirs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("src.models.app_config._resolve_config_dir", lambda: tmp_path)
    monkeypatch.setattr("src.models.app_config._resolve_data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.utils.security_utils.get_config_dir", lambda: tmp_path)


class _SignalRecorder:
    def __init__(self):
        self.calls: list[tuple] = []

    def emit(self, *args):
        self.calls.append(args)


def _make_vm_stub(config: AppConfig):
    apply_calls: list[bool] = []
    vm = SimpleNamespace(
        _config=config,
        _db=SimpleNamespace(delete_records_by_browser=lambda _browser_type: 0),
        history_vm=None,
        _em=SimpleNamespace(get_all_registered=lambda: {}),
        browser_status_changed=_SignalRecorder(),
        config_changed=_SignalRecorder(),
        _apply_browser_runtime_from_config=lambda force_monitor=False: apply_calls.append(force_monitor),
        _monitor_status_snapshot=lambda: {},
    )
    return vm, apply_calls


class TestOnBrowserRemove:
    def test_removing_builtin_override_keeps_disabled_builtin(self):
        cfg = AppConfig()
        cfg.extractor.disabled_browsers = ["chrome"]
        cfg.extractor.set_custom_browser("chrome", "C:/Portable/History")
        vm, apply_calls = _make_vm_stub(cfg)

        MainViewModel.on_browser_remove(vm, "chrome", False)

        assert cfg.extractor.disabled_browsers == ["chrome"]
        assert "chrome" not in cfg.extractor.custom_browsers
        assert apply_calls == [True]

    def test_removing_nonbuiltin_custom_browser_clears_stale_disabled_entry(self):
        cfg = AppConfig()
        cfg.extractor.disabled_browsers = ["portable"]
        cfg.extractor.set_custom_browser("portable", "C:/Portable/History", display_name="Portable")
        vm, apply_calls = _make_vm_stub(cfg)

        MainViewModel.on_browser_remove(vm, "portable", False)

        assert "portable" not in cfg.extractor.disabled_browsers
        assert "portable" not in cfg.extractor.custom_browsers
        assert apply_calls == [True]
