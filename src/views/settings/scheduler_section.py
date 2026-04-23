# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.views.settings._label_utils import constrain_label_width


class SchedulerSection(QWidget):
    """Auto-sync scheduler card.

    Exposes:
        load(cfg)                      - populate from config
        get_auto_sync_enabled() -> bool
        get_interval_hours() -> int
        set_next_sync_text(text: str)  - update countdown label
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        self._auto_sync_cb = QCheckBox(_("Enable scheduled auto-sync"))
        layout.addWidget(self._auto_sync_cb)

        interval_row = QHBoxLayout()
        interval_lbl = QLabel(_("Sync interval:"))
        interval_lbl.setObjectName("muted")
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 168)
        self._interval_spin.setSuffix(_(" hours"))
        interval_row.addWidget(interval_lbl)
        interval_row.addWidget(self._interval_spin)
        interval_row.addStretch()
        layout.addLayout(interval_row)

        next_sync_row = QHBoxLayout()
        next_sync_row.setSpacing(6)
        self._next_sync_icon_lbl = QLabel()
        self._next_sync_icon_lbl.setPixmap(get_icon("refresh-ccw", 14).pixmap(14, 14))
        self._next_sync_icon_lbl.setFixedSize(14, 14)
        self._next_sync_lbl = constrain_label_width(QLabel(""))
        self._next_sync_lbl.setObjectName("muted")
        next_sync_row.addWidget(self._next_sync_icon_lbl)
        next_sync_row.addWidget(self._next_sync_lbl, 1)
        next_sync_row.addStretch()
        self._next_sync_icon_lbl.hide()
        self._next_sync_lbl.hide()
        layout.addLayout(next_sync_row)

    # ── Public API ────────────────────────────────────────────

    def load(self, cfg):
        self._auto_sync_cb.setChecked(cfg.scheduler.auto_sync_enabled)
        self._interval_spin.setValue(cfg.scheduler.sync_interval_hours)

    def get_auto_sync_enabled(self) -> bool:
        return self._auto_sync_cb.isChecked()

    def get_interval_hours(self) -> int:
        return self._interval_spin.value()

    def set_next_sync_text(self, text: str):
        self._next_sync_lbl.setText(text)
        self._next_sync_icon_lbl.setVisible(bool(text))
        self._next_sync_lbl.setVisible(bool(text))

    # ── Internal (for signal wiring in SettingsPage) ──────────

    @property
    def auto_sync_cb(self) -> QCheckBox:
        return self._auto_sync_cb

    @property
    def interval_spin(self) -> QSpinBox:
        return self._interval_spin
