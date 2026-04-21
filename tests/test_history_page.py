# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)

from PySide6.QtCore import QRect

from src.views.history_page import _SEP_CONTENT_TOP_INSET, _SEP_H, _separator_band_rect, _separator_content_rect


def test_separator_band_rect_stays_in_top_band() -> None:
    rect = QRect(10, 20, 200, 38)

    band = _separator_band_rect(rect)

    assert band.top() == rect.top() + 1
    assert band.height() == _SEP_H
    assert band.width() == rect.width()


def test_separator_content_rect_reserves_top_inset() -> None:
    rect = QRect(0, 0, 120, 38)

    content = _separator_content_rect(rect)

    assert content.top() == rect.top() + _SEP_CONTENT_TOP_INSET
    assert content.height() == rect.height() - _SEP_CONTENT_TOP_INSET
    assert content.width() == rect.width()


def test_separator_content_rect_clamps_for_short_rows() -> None:
    rect = QRect(0, 0, 80, 16)

    content = _separator_content_rect(rect)

    assert content.top() >= rect.top()
    assert content.height() > 0
    assert content.bottom() <= rect.bottom()
