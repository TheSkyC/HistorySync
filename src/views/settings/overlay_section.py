# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.utils.i18n import _
from src.utils.styled_combobox import StyledComboBox


class OverlaySection(QWidget):
    """Quick-access overlay settings card.

    Exposes:
        load(cfg, db)              - populate from config + available browsers
        get_overlay_config() -> OverlayConfig
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        self._enabled_cb = QCheckBox(_("Enable quick-access overlay"))
        layout.addWidget(self._enabled_cb)

        # Filter browsers row
        filter_row = QHBoxLayout()
        filter_lbl = QLabel(_("Filter browsers:"))
        filter_lbl.setObjectName("muted")
        self._filter_combo = StyledComboBox()
        self._filter_combo.setMinimumWidth(180)
        filter_row.addWidget(filter_lbl)
        filter_row.addWidget(self._filter_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Open with row
        open_row = QHBoxLayout()
        open_lbl = QLabel(_("Open with:"))
        open_lbl.setObjectName("muted")
        self._open_combo = StyledComboBox()
        self._open_combo.setMinimumWidth(180)
        open_row.addWidget(open_lbl)
        open_row.addWidget(self._open_combo)
        open_row.addStretch()
        layout.addLayout(open_row)

        self._enabled_cb.toggled.connect(self._on_enabled_toggled)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, cfg, db=None) -> None:
        from src.models.app_config import OverlayConfig

        oc: OverlayConfig = cfg.overlay
        self._enabled_cb.setChecked(oc.enabled)

        browsers: list[tuple[str, str]] = []
        if db is not None:
            try:
                browsers = db.get_available_browsers()
            except Exception:
                pass

        self._filter_combo.blockSignals(True)
        self._open_combo.blockSignals(True)

        self._filter_combo.clear()
        self._open_combo.clear()

        self._filter_combo.addItem(_("Auto (Active / All)"), "auto")
        self._filter_combo.addItem(_("All"), "all")
        self._open_combo.addItem(_("Auto"), "auto")

        for bt, display in browsers:
            self._filter_combo.addItem(display, bt)
            self._open_combo.addItem(display, bt)

        for i in range(self._filter_combo.count()):
            if self._filter_combo.itemData(i) == oc.filter_browsers:
                self._filter_combo.setCurrentIndex(i)
                break
        for i in range(self._open_combo.count()):
            if self._open_combo.itemData(i) == oc.open_with:
                self._open_combo.setCurrentIndex(i)
                break

        self._filter_combo.blockSignals(False)
        self._open_combo.blockSignals(False)
        self._on_enabled_toggled(oc.enabled)

    def get_overlay_config(self):
        from src.models.app_config import OverlayConfig

        return OverlayConfig(
            enabled=self._enabled_cb.isChecked(),
            filter_browsers=self._filter_combo.currentData() or "auto",
            open_with=self._open_combo.currentData() or "auto",
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._filter_combo.setEnabled(enabled)
        self._open_combo.setEnabled(enabled)
