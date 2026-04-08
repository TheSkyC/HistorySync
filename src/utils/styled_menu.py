# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QMenu


class StyledMenu(QMenu):
    """QMenu subclass that ensures rounded corners display correctly on Windows."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set window flags to remove native window frame
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Add fade-in animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(120)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)

    def showEvent(self, event):
        """Trigger fade-in animation when menu is shown."""
        super().showEvent(event)
        self._fade_animation.stop()
        self._fade_animation.start()
