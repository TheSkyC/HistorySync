# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.app_config import (
    BUILTIN_SEARCH_ENGINES,
    CUSTOM_ENGINE_KEY,
    SearchEngineConfig,
)
from src.utils.i18n import _
from src.utils.styled_combobox import StyledComboBox


class SearchEngineSection(QWidget):
    """Settings card for choosing the web-search engine.

    Public API
    ----------
    load(cfg)                   - populate from AppConfig
    get_search_engine_config()  - return updated SearchEngineConfig
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ── Engine selector row ───────────────────────────────────────────────
        engine_row = QHBoxLayout()
        engine_lbl = QLabel(_("Search engine:"))
        engine_lbl.setObjectName("muted")
        engine_lbl.setFixedWidth(130)

        self._engine_combo = StyledComboBox()
        self._engine_combo.setMinimumWidth(200)

        for name, __ in BUILTIN_SEARCH_ENGINES:
            self._engine_combo.addItem(name, name)
        self._engine_combo.addItem(_("Custom…"), CUSTOM_ENGINE_KEY)

        engine_row.addWidget(engine_lbl)
        engine_row.addWidget(self._engine_combo)
        engine_row.addStretch()
        layout.addLayout(engine_row)

        # ── URL template editor (visible for all entries so user can see it) ──
        url_row = QHBoxLayout()
        url_lbl = QLabel(_("URL template:"))
        url_lbl.setObjectName("muted")
        url_lbl.setFixedWidth(130)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://example.com/search?q={query}")
        self._url_edit.setMinimumWidth(340)
        self._url_edit.setToolTip(
            _("Use {query} as the placeholder for the search term.\nExample: https://www.google.com/search?q={query}")
        )

        url_row.addWidget(url_lbl)
        url_row.addWidget(self._url_edit)
        url_row.addStretch()
        layout.addLayout(url_row)

        # ── Signals ───────────────────────────────────────────────────────────
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        self._url_edit.textChanged.connect(self._on_url_edited)

        # Internal state: track whether the user is editing a custom URL
        self._block_url_sync = False

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, cfg) -> None:
        se: SearchEngineConfig = cfg.search_engine

        self._engine_combo.blockSignals(True)
        self._url_edit.blockSignals(True)

        # Select the matching engine in the combo
        idx = self._engine_combo.findData(se.engine)
        if idx < 0:
            # Unknown engine name → treat as custom
            idx = self._engine_combo.findData(CUSTOM_ENGINE_KEY)
        self._engine_combo.setCurrentIndex(max(idx, 0))

        self._url_edit.setText(se.url_template)
        self._update_url_edit_state()

        self._engine_combo.blockSignals(False)
        self._url_edit.blockSignals(False)

    def get_search_engine_config(self) -> SearchEngineConfig:
        engine = self._engine_combo.currentData() or "Google"
        url = self._url_edit.text().strip()
        if not url:
            # Fall back to builtin template if empty
            url = self._builtin_url_for(engine) or "https://www.google.com/search?q={query}"
        return SearchEngineConfig(engine=engine, url_template=url)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _on_engine_changed(self, _index: int) -> None:
        engine = self._engine_combo.currentData()
        if engine != CUSTOM_ENGINE_KEY:
            # Auto-fill the URL template from the builtin list
            builtin_url = self._builtin_url_for(engine)
            if builtin_url:
                self._block_url_sync = True
                self._url_edit.setText(builtin_url)
                self._block_url_sync = False
        self._update_url_edit_state()

    def _on_url_edited(self, _text: str) -> None:
        if self._block_url_sync:
            return
        # If the user edits the URL while a builtin is selected, switch to custom
        engine = self._engine_combo.currentData()
        if engine != CUSTOM_ENGINE_KEY:
            builtin_url = self._builtin_url_for(engine)
            if _text != builtin_url:
                self._engine_combo.blockSignals(True)
                self._engine_combo.setCurrentIndex(self._engine_combo.findData(CUSTOM_ENGINE_KEY))
                self._engine_combo.blockSignals(False)
                self._update_url_edit_state()

    def _update_url_edit_state(self) -> None:
        engine = self._engine_combo.currentData()
        is_custom = engine == CUSTOM_ENGINE_KEY
        # Editable for both builtin and custom, but read-only visual hint for builtins
        self._url_edit.setReadOnly(False)
        # Style: dim for builtin (informational), normal for custom
        self._url_edit.setProperty("muted_input", not is_custom)
        self._url_edit.style().unpolish(self._url_edit)
        self._url_edit.style().polish(self._url_edit)

    @staticmethod
    def _builtin_url_for(engine_name: str) -> str | None:
        for name, url in BUILTIN_SEARCH_ENGINES:
            if name == engine_name:
                return url
        return None
