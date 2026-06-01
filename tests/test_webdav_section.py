# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QDialog

from src.models.app_config import AppConfig, WebDavConfig
from src.views.settings import webdav_section as webdav_section_module
from src.views.settings.webdav_section import WebDavSection


def test_load_does_not_probe_secret_store(monkeypatch, qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()

    def _boom():
        raise AssertionError("secret store should not be touched while loading settings")

    monkeypatch.setattr("src.utils.secret_store.get_secret_store", _boom)

    section.load(cfg)

    assert section._connection_summary_lbl.text() == "Not configured yet."
    assert section._password_status_lbl.isHidden() is True


def test_saved_password_state_shows_secure_summary_without_keyring_lookup(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    cfg._webdav_password_cache = "cached"

    section.load(cfg)

    assert section._password_status_lbl.isHidden() is True


def test_decryption_warning_shows_reenter_status(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    cfg._webdav_password_decryption_failed = True
    cfg._webdav_password_ciphertext = "ENC:legacy"

    section.load(cfg)

    assert section._password_warning_lbl.isHidden() is False
    assert section._password_status_lbl.text() == "Saved password needs attention."


def test_edit_connection_dialog_updates_draft_and_pending_password(monkeypatch, qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    section.load(cfg)

    class _FakeDialog:
        def __init__(self, parent=None):
            self.parent = parent

        def load(self, draft_cfg, **kwargs) -> None:
            self.loaded_cfg = draft_cfg
            self.loaded_kwargs = kwargs

        def get_config(self) -> WebDavConfig:
            return WebDavConfig(
                url="https://dav.example.com/dav/",
                username="alice",
                remote_path="/remote/historysync",
                max_backups=12,
                verify_ssl=False,
            )

        def get_password(self) -> str:
            return "new-secret"

    monkeypatch.setattr(webdav_section_module, "WebDavConnectionDialog", _FakeDialog)
    monkeypatch.setattr(webdav_section_module, "exec_centered", lambda dlg, parent: QDialog.Accepted)

    section._open_connection_dialog()
    draft = section.get_webdav_config()

    assert draft.url == "https://dav.example.com/dav/"
    assert draft.username == "alice"
    assert draft.password == "new-secret"
    assert draft.remote_path == "/remote/historysync"
    assert draft.max_backups == 12
    assert draft.verify_ssl is False
    assert "alice @ dav.example.com" in section._connection_summary_lbl.text()
    assert "staged" in section._password_status_lbl.text()


def test_remote_backups_dialog_receives_loaded_results(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    cfg.webdav.enabled = True
    section.load(cfg)

    emitted: list[str] = []
    section.action_requested.connect(emitted.append)

    section._open_remote_backups_dialog()

    assert emitted == ["list_backups"]
    assert section._backups_dialog is not None
    assert section._backups_dialog._status_lbl.text() == "Loading remote backups..."

    section.on_action_finished(
        "list_backups",
        True,
        "2 backup(s) found",
        backups=[
            {"filename": "history_1.zip", "timestamp": 1_780_000_000, "format": "zip"},
            {"filename": "history_2.zip", "timestamp": 1_780_000_100, "format": "zip"},
        ],
    )

    assert section._backups_dialog._status_lbl.text() == "2 backup(s) found"
    assert section._backups_dialog._list.count() == 2
