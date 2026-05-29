# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from src.models.app_config import AppConfig
from src.views.settings.webdav_section import WebDavSection


def test_saved_password_state_hides_eye_and_shows_keyring_status(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    cfg._webdav_password_cache = "cached"

    section.load(cfg)

    assert section._password._toggle_button.isHidden() is True
    assert (
        section._password_status_lbl.text() == "Saved in the system keyring. Leave blank to keep the current password."
    )


def test_typing_password_shows_eye_and_replace_status(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()

    section.load(cfg)
    section._password.setText("new-secret")

    assert section._password._toggle_button.isHidden() is False
    assert section._password_status_lbl.text() == "Saving will replace the currently saved password."


def test_decryption_warning_shows_reenter_status(qapp) -> None:
    section = WebDavSection()
    cfg = AppConfig()
    cfg._webdav_password_decryption_failed = True
    cfg._webdav_password_ciphertext = "ENC:legacy"

    section.load(cfg)

    assert (
        section._password_status_lbl.text()
        == "The saved password could not be loaded. Enter a new password to replace it."
    )
