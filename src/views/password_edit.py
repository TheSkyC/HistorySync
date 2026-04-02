# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Slot
from PySide6.QtGui import QColor, QPainter, QPen, Qt
from PySide6.QtWidgets import QAbstractButton, QLineEdit

from src.utils.i18n import _
from src.utils.theme_manager import ThemeManager

# Color Configuration
_DARK_COLOR = QColor("#8a9098")
_DARK_COLOR_HOVER = QColor("#c8d0dc")
_LIGHT_COLOR = QColor("#6b7280")
_LIGHT_COLOR_HOVER = QColor("#1e2840")


class EyeButton(QAbstractButton):
    """Password visibility toggle button with animation, supporting light/dark themes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(24, 24)

        # Initial colors
        self._update_colors(ThemeManager.instance().current)

        self._is_hovered = False

        # Animation parameter: 0.0 = show password (eye open), 1.0 = hide password (eye closed with slash)
        self._anim_progress = 1.0  # Initial state: hide password
        self._anim = QPropertyAnimation(self, b"anim_progress", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.toggled.connect(self._start_animation)

        # Subscribe to theme changes
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def _update_colors(self, theme: str) -> None:
        if theme == "dark":
            self._color = QColor(_DARK_COLOR)
            self._color_hover = QColor(_DARK_COLOR_HOVER)
        else:
            self._color = QColor(_LIGHT_COLOR)
            self._color_hover = QColor(_LIGHT_COLOR_HOVER)

    def _on_theme_changed(self, theme: str) -> None:
        self._update_colors(theme)
        self.update()

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    @Property(float)
    def anim_progress(self):
        return self._anim_progress

    @anim_progress.setter
    def anim_progress(self, value):
        self._anim_progress = value
        self.update()

    def _start_animation(self, checked):
        self._anim.stop()
        self._anim.setEndValue(0.0 if checked else 1.0)
        self._anim.start()

    def set_checked_silent(self, checked: bool) -> None:
        """Set the button state without animation."""
        self.blockSignals(True)
        self.setChecked(checked)
        self._anim_progress = 0.0 if checked else 1.0
        self.update()
        self.blockSignals(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = self._color_hover if self._is_hovered else self._color
        pen = QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)

        rect = self.rect()
        center_x = rect.width() / 2
        center_y = rect.height() / 2

        # Eye outline
        eye_width = 16
        eye_height = 10
        eye_rect = QRectF(center_x - eye_width / 2, center_y - eye_height / 2, eye_width, eye_height)

        painter.drawArc(eye_rect, 0 * 16, 180 * 16)  # Upper arc
        painter.drawArc(eye_rect, 180 * 16, 180 * 16)  # Lower arc

        # Pupil: shrinks with animation
        pupil_size = 4 * (1 - self._anim_progress * 0.7)
        if pupil_size > 0.5:
            painter.setBrush(color)
            painter.drawEllipse(QPointF(center_x, center_y), pupil_size / 2, pupil_size / 2)

        # Slash: fades in with animation
        if self._anim_progress > 0.01:
            line_color = QColor(color)
            line_color.setAlphaF(self._anim_progress)
            painter.setPen(QPen(line_color, 2, Qt.SolidLine, Qt.RoundCap))

            line_length = 18 * self._anim_progress
            offset = line_length / 2
            painter.drawLine(
                QPointF(center_x - offset, center_y - offset),
                QPointF(center_x + offset, center_y + offset),
            )

    def sizeHint(self):
        return QSize(24, 24)


class PasswordEdit(QLineEdit):
    """Password input field with an eye toggle button, automatically adapting to light/dark themes."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setEchoMode(QLineEdit.Password)
        self.setInputMethodHints(
            Qt.ImhHiddenText | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase | Qt.ImhSensitiveData
        )

        self._toggle_button = EyeButton(self)
        self._toggle_button.setFocusPolicy(Qt.NoFocus)
        self._toggle_button.set_checked_silent(False)
        self._toggle_button.setToolTip(_("Show Password"))
        self._toggle_button.clicked.connect(self._on_toggle)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        btn_size = 24
        padding = 4
        self._toggle_button.setGeometry(
            self.width() - btn_size - padding,
            (self.height() - btn_size) // 2,
            btn_size,
            btn_size,
        )

    @Slot()
    def _on_toggle(self):
        cursor_pos = self.cursorPosition()

        if self.echoMode() == QLineEdit.Password:
            self.setEchoMode(QLineEdit.Normal)
            self._toggle_button.setToolTip(_("Hide Password"))
        else:
            self.setEchoMode(QLineEdit.Password)
            self._toggle_button.setToolTip(_("Show Password"))

        self.setCursorPosition(cursor_pos)
        self.setFocus()
