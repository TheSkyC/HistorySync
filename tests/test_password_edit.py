# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from src.views.password_edit import PasswordEdit


def test_toggle_hidden_when_empty_if_enabled(qapp) -> None:
    edit = PasswordEdit()
    edit.set_hide_toggle_when_empty(True)

    assert edit._toggle_button.isHidden() is True


def test_toggle_shown_when_text_present_if_enabled(qapp) -> None:
    edit = PasswordEdit()
    edit.set_hide_toggle_when_empty(True)
    edit.setText("secret")

    assert edit._toggle_button.isHidden() is False


def test_toggle_remains_visible_by_default(qapp) -> None:
    edit = PasswordEdit()

    assert edit._toggle_button.isHidden() is False
