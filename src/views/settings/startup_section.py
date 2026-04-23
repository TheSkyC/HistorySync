# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.utils.i18n import _
from src.views.settings._label_utils import constrain_label_width


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
        self._status_lbl = constrain_label_width(QLabel(""))
        self._status_lbl.setObjectName("muted")
        self._status_lbl.setVisible(False)
        row.addWidget(self._startup_cb)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(self._status_lbl)

        note = constrain_label_width(
            QLabel(_("When enabled, HistorySync will start in the background and begin collecting on system startup."))
        )
        note.setObjectName("muted")
        layout.addWidget(note)

        self._minimized_cb = QCheckBox(_("Start minimized to tray when opening the app"))
        layout.addWidget(self._minimized_cb)

        minimized_note = constrain_label_width(
            QLabel(
                _(
                    "When enabled, the main window will not appear on launch — HistorySync runs silently in the system tray."
                )
            )
        )
        minimized_note.setObjectName("muted")
        layout.addWidget(minimized_note)

    # ── Public API ────────────────────────────────────────────

    def load(self, enabled: bool, start_minimized: bool = False):
        self._startup_cb.setChecked(enabled)
        self._minimized_cb.setChecked(start_minimized)
        self._status_lbl.setText("")
        self._status_lbl.setVisible(False)

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
        self._status_lbl.setVisible(bool(text))
        color = color_map.get(level, "")
        if color:
            self._status_lbl.setStyleSheet(f"color: {color};")
        else:
            self._status_lbl.setStyleSheet("")
