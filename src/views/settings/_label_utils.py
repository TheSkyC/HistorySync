# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QSizePolicy


def constrain_label_width(label: QLabel, *, word_wrap: bool = True) -> QLabel:
    """Prevent long label text from forcing settings cards to grow wider."""

    label.setMinimumWidth(0)
    label.setWordWrap(word_wrap)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label
