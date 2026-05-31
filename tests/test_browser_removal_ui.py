# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QCheckBox, QMessageBox

from src.models.app_config import AppConfig
from src.views.dashboard_page import BrowserCard, DashboardPage
from src.views.settings_page import SettingsPage


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


class _DummySignal:
    def connect(self, _cb):
        return None


class _ManagedSignal:
    def __init__(self):
        self._callbacks: list = []

    def connect(self, cb):
        self._callbacks.append(cb)

    def disconnect(self, cb):
        if cb not in self._callbacks:
            raise AssertionError("disconnect called for a slot that is no longer connected")
        self._callbacks.remove(cb)

    def emit(self, *args):
        for cb in list(self._callbacks):
            cb(*args)


def _make_settings_page(config: AppConfig, *, main_vm_override=None):
    save_calls: list[AppConfig] = []

    def _save(cfg: AppConfig) -> None:
        save_calls.append(cfg)

    db_stats = SimpleNamespace(file_size_bytes=0, record_count=0, hidden_count=0, domain_count=0)
    main_vm = main_vm_override or SimpleNamespace(
        get_hidden_domains=lambda: [],
        _db=SimpleNamespace(get_db_stats=lambda: db_stats),
        history_vm=SimpleNamespace(set_hidden_ids=lambda _ids: None),
        sync_started=_DummySignal(),
        sync_finished=_DummySignal(),
        sync_error=_DummySignal(),
    )

    vm = SimpleNamespace(
        get_config=lambda: config,
        get_available_languages=lambda: {"en_US": "English"},
        get_current_language=lambda: "en_US",
        save=_save,
        saved=_DummySignal(),
        error=_DummySignal(),
        language_change_requested=_DummySignal(),
        webdav_action_progress=_DummySignal(),
        webdav_action_finished=_DummySignal(),
        maintenance_progress=_DummySignal(),
        maintenance_finished=_DummySignal(),
        get_db_stats=lambda: db_stats,
        _main_vm=main_vm,
    )
    page = SettingsPage(vm)
    return page, save_calls


class TestBrowserCardRemovalWarnings:
    def test_builtin_override_delete_cancelled_by_warning(self, monkeypatch, qapp):
        cfg = AppConfig()
        cfg.extractor.set_custom_browser("chrome", "C:/Portable/History")

        dashboard = DashboardPage()
        dashboard.refresh_from_config(cfg)
        dashboard.bind_main_vm(SimpleNamespace(_db=SimpleNamespace(get_filtered_count=lambda **_kwargs: 42)))

        card = BrowserCard("chrome", "Google Chrome", dashboard)
        emitted = _SignalRecorder()
        card.browser_remove_requested.connect(emitted.emit)

        def _accept_dialog(dialog, *_args, **_kwargs):
            clear_cb = dialog.findChild(QCheckBox)
            assert clear_cb is not None
            clear_cb.setChecked(True)
            assert clear_cb.isChecked() is False
            return 1

        monkeypatch.setattr("src.views.dashboard_page.exec_centered", _accept_dialog)
        monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.No)

        card._on_remove_browser()

        assert emitted.calls == [("chrome", False)]

    def test_builtin_override_delete_confirmed_emits_request(self, monkeypatch, qapp):
        cfg = AppConfig()
        cfg.extractor.set_custom_browser("chrome", "C:/Portable/History")

        dashboard = DashboardPage()
        dashboard.refresh_from_config(cfg)
        dashboard.bind_main_vm(SimpleNamespace(_db=SimpleNamespace(get_filtered_count=lambda **_kwargs: 42)))

        card = BrowserCard("chrome", "Google Chrome", dashboard)
        emitted = _SignalRecorder()
        card.browser_remove_requested.connect(emitted.emit)

        def _accept_dialog(dialog, *_args, **_kwargs):
            clear_cb = dialog.findChild(QCheckBox)
            assert clear_cb is not None
            clear_cb.setChecked(True)
            assert clear_cb.isChecked() is True
            return 1

        monkeypatch.setattr("src.views.dashboard_page.exec_centered", _accept_dialog)
        monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.Yes)

        card._on_remove_browser()

        assert emitted.calls == [("chrome", True)]

    def test_nonbuiltin_custom_browser_delete_does_not_warn_on_checkbox(self, monkeypatch, qapp):
        cfg = AppConfig()
        cfg.extractor.set_custom_browser("portable", "C:/Portable/History", display_name="Portable")

        dashboard = DashboardPage()
        dashboard.refresh_from_config(cfg)
        dashboard.bind_main_vm(SimpleNamespace(_db=SimpleNamespace(get_filtered_count=lambda **_kwargs: 42)))

        card = BrowserCard("portable", "Portable", dashboard)
        emitted = _SignalRecorder()
        card.browser_remove_requested.connect(emitted.emit)

        warning_calls: list[tuple] = []

        def _accept_dialog(dialog, *_args, **_kwargs):
            clear_cb = dialog.findChild(QCheckBox)
            assert clear_cb is not None
            clear_cb.setChecked(True)
            return 1

        monkeypatch.setattr("src.views.dashboard_page.exec_centered", _accept_dialog)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warning_calls.append((args, kwargs)))

        card._on_remove_browser()

        assert warning_calls == []
        assert emitted.calls == [("portable", True)]


class TestSettingsCustomPathRemoval:
    def test_settings_path_delete_requires_confirmation(self, monkeypatch, qapp):
        cfg = AppConfig()
        cfg.extractor.set_custom_browser("portable", "C:/Portable/History", display_name="Portable")
        page, save_calls = _make_settings_page(cfg)

        monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.No)

        page._on_remove_custom_path("portable")

        assert "portable" in cfg.extractor.custom_browsers
        assert save_calls == []

    def test_settings_path_delete_confirmed_removes_path(self, monkeypatch, qapp):
        cfg = AppConfig()
        cfg.extractor.set_custom_browser("portable", "C:/Portable/History", display_name="Portable")
        page, save_calls = _make_settings_page(cfg)

        monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

        page._on_remove_custom_path("portable")

        assert "portable" not in cfg.extractor.custom_browsers
        assert save_calls == [cfg]


class TestSettingsUpdateCheckCleanup:
    def test_update_check_cleanup_is_idempotent_after_page_destroy(self, qapp):
        cfg = AppConfig()
        update_available = _ManagedSignal()
        update_not_available = _ManagedSignal()
        update_check_failed = _ManagedSignal()

        main_vm = SimpleNamespace(
            get_hidden_domains=lambda: [],
            _db=SimpleNamespace(
                get_db_stats=lambda: SimpleNamespace(file_size_bytes=0, record_count=0, hidden_count=0, domain_count=0)
            ),
            history_vm=SimpleNamespace(set_hidden_ids=lambda _ids: None),
            sync_started=_DummySignal(),
            sync_finished=_DummySignal(),
            sync_error=_DummySignal(),
            update_available=update_available,
            update_not_available=update_not_available,
            update_check_failed=update_check_failed,
            update_service=SimpleNamespace(
                is_version_skipped=lambda _version: False,
                context=SimpleNamespace(can_self_update=True),
            ),
            check_for_updates=lambda manual=True: None,
        )

        page, _ = _make_settings_page(cfg, main_vm_override=main_vm)
        page._on_check_for_updates()

        update_available.emit(SimpleNamespace(release=SimpleNamespace(version="1.4.0")))
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, 0)
        qapp.processEvents()

        assert update_available._callbacks == []
        assert update_not_available._callbacks == []
        assert update_check_failed._callbacks == []
