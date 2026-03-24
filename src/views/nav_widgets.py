# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QPushButton

from src.utils.i18n import N_, _
from src.utils.icon_helper import get_themed_icon
from src.utils.theme_manager import THEME_DARK, THEME_LIGHT, THEME_SYSTEM

# Theme cycle order and display metadata
_THEME_CYCLE = [THEME_SYSTEM, THEME_LIGHT, THEME_DARK]
_THEME_ICON: dict[str, tuple[str, str]] = {
    THEME_SYSTEM: ("system", N_("Theme: Auto")),
    THEME_LIGHT: ("sun", N_("Theme: Light")),
    THEME_DARK: ("moon", N_("Theme: Dark")),
}


class NavButton(QPushButton):
    """Icon-only sidebar navigation button (checkable, fixed 40×40)."""

    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setObjectName("nav_btn")
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setIcon(get_themed_icon(icon_name))
        self.setIconSize(QSize(20, 20))

    def refresh_icon(self):
        """Re-render icon with the current theme palette."""
        self.setIcon(get_themed_icon(self._icon_name))


class ThemeButton(QPushButton):
    """Sidebar bottom button that cycles through system → light → dark themes.

    Emits ``theme_cycle_requested(next_theme)`` on click; the caller is
    responsible for actually applying the new theme.
    """

    theme_cycle_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nav_btn")
        self.setCheckable(False)
        self.setFixedSize(40, 40)
        self.setIconSize(QSize(20, 20))
        self._current_raw = THEME_DARK
        self._update_icon()
        self.clicked.connect(self._on_click)

    def set_theme(self, raw_theme: str):
        self._current_raw = raw_theme
        self._update_icon()

    def refresh_icon(self):
        """Re-render icon after the theme palette changes."""
        self._update_icon()

    # ── Internal ──────────────────────────────────────────────

    def _update_icon(self):
        icon_name, tooltip = _THEME_ICON.get(self._current_raw, ("moon", N_("Theme: Dark")))
        self.setIcon(get_themed_icon(icon_name))
        self.setToolTip(_(tooltip))

    def _on_click(self):
        idx = _THEME_CYCLE.index(self._current_raw) if self._current_raw in _THEME_CYCLE else 0
        self.theme_cycle_requested.emit(_THEME_CYCLE[(idx + 1) % len(_THEME_CYCLE)])
