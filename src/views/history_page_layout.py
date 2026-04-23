# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QRect

# Date-separator layout constants used by HistoryPage and pure geometry tests.
_SEP_H = 16
_SEP_CONTENT_TOP_INSET = 10
_ROW_H = 38


def _separator_band_rect(rect: QRect) -> QRect:
    """Return the top band used to paint a separator pill."""
    return QRect(rect.left(), rect.top() + 1, rect.width(), min(_SEP_H, rect.height()))


def _separator_content_rect(rect: QRect) -> QRect:
    """Return the content rect for rows that render a separator pill."""
    inset = min(_SEP_CONTENT_TOP_INSET, max(rect.height() - 18, 0))
    if inset <= 0:
        return QRect(rect)
    return QRect(rect.left(), rect.top() + inset, rect.width(), max(rect.height() - inset, 0))
