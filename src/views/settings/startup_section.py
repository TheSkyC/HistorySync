# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.utils.i18n import _


class StartupSection(QWidget):
    """System-startup launch card.

    Exposes:
        load(enabled: bool, start_minimized: bool)  - set checkbox states
        get_launch_on_startup() -> bool
        get_start_minimized() -> bool
        set_status(text: str, level: str)            - update inline status label
            level: "info" | "warning" | "error" | "success" | ""
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        row = QHBoxLayout()
        self._startup_cb = QCheckBox(_("Launch at system startup (minimized to tray)"))
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("muted")
        row.addWidget(self._startup_cb)
        row.addStretch()
        row.addWidget(self._status_lbl)
        layout.addLayout(row)

        note = QLabel(
            _("When enabled, HistorySync will start in the background and begin collecting on system startup.")
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._minimized_cb = QCheckBox(_("Start minimized to tray when opening the app"))
        layout.addWidget(self._minimized_cb)

        minimized_note = QLabel(
            _("When enabled, the main window will not appear on launch — HistorySync runs silently in the system tray.")
        )
        minimized_note.setObjectName("muted")
        minimized_note.setWordWrap(True)
        layout.addWidget(minimized_note)

    # ── Public API ────────────────────────────────────────────

    def load(self, enabled: bool, start_minimized: bool = False):
        self._startup_cb.setChecked(enabled)
        self._minimized_cb.setChecked(start_minimized)
        self._status_lbl.setText("")

    def get_launch_on_startup(self) -> bool:
        return self._startup_cb.isChecked()

    def get_start_minimized(self) -> bool:
        return self._minimized_cb.isChecked()

    def set_status(self, text: str, level: str = "info"):
        """Display inline status next to the checkbox.

        Args:
            text:  Message to show. Pass "" to clear.
            level: "success" | "warning" | "error" | "info" | ""
        """
        color_map = {
            "success": "#4caf50",
            "warning": "#ff9800",
            "error": "#f44336",
            "info": "",  # inherits muted style
            "": "",
        }
        self._status_lbl.setText(text)
        color = color_map.get(level, "")
        if color:
            self._status_lbl.setStyleSheet(f"color: {color};")
        else:
            self._status_lbl.setStyleSheet("")
