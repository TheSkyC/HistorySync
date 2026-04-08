# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.utils.i18n import _
from src.utils.styled_combobox import StyledComboBox


class LanguageSection(QWidget):
    """Language selection card.

    Exposes:
        load(langs, current_lang)  - populate combo
        get_selected_code() -> str - currently chosen language code
        show_restart_note()        - reveal the "restart required" hint
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        lang_row = QHBoxLayout()
        lang_lbl = QLabel(_("Interface language:"))
        lang_lbl.setObjectName("muted")
        self._combo = StyledComboBox()
        self._combo.setMinimumWidth(200)
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        self._restart_note = QLabel(_("Restart required to apply language changes."))
        self._restart_note.setObjectName("muted")
        self._restart_note.setVisible(False)
        layout.addWidget(self._restart_note)

    # ── Public API ────────────────────────────────────────────

    def load(self, langs: dict[str, str], current_lang: str):
        self._combo.blockSignals(True)
        self._combo.clear()
        for code, name in langs.items():
            self._combo.addItem(name, code)
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == current_lang:
                self._combo.setCurrentIndex(i)
                break
        self._combo.blockSignals(False)

    def get_selected_code(self) -> str:
        return self._combo.currentData() or ""

    def show_restart_note(self):
        self._restart_note.setVisible(True)

    # ── Internal ──────────────────────────────────────────────

    @property
    def combo(self) -> StyledComboBox:
        """Direct access for connecting currentIndexChanged externally."""
        return self._combo
