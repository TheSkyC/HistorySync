# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class PrivacySection(QWidget):
    """Privacy & blacklist card.

    Signals:
        configure_blacklist_requested()
        configure_url_filters_requested()
        clear_hidden_requested()

    Exposes:
        refresh_blacklist_count(count: int)
        refresh_hidden_count(count: int)
    """

    configure_blacklist_requested = Signal()
    configure_url_filters_requested = Signal()
    clear_hidden_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        desc = QLabel(
            _(
                "Blacklisted domains are never synced and all their records are deleted. "
                "Hidden records are excluded from the History view but kept in the database."
            )
        )
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Blacklist row ─────────────────────────────────────
        bl_row = QHBoxLayout()
        bl_lbl = QLabel(_("Blacklisted Domains:"))
        bl_lbl.setObjectName("stat_label")
        self._bl_count_lbl = QLabel("")
        self._bl_count_lbl.setObjectName("muted")
        bl_cfg_btn = QPushButton(_("Configure…"))
        bl_cfg_btn.setIcon(get_icon("shield"))
        bl_cfg_btn.setToolTip(
            _("Manage domains that are permanently excluded from sync and whose records are deleted.")
        )
        bl_cfg_btn.clicked.connect(self.configure_blacklist_requested)
        bl_row.addWidget(bl_lbl)
        bl_row.addWidget(self._bl_count_lbl)
        bl_row.addStretch()
        bl_row.addWidget(bl_cfg_btn)
        layout.addLayout(bl_row)

        # ── URL Prefix Filters row ────────────────────────────
        url_filter_row = QHBoxLayout()
        url_filter_lbl = QLabel(_("URL Prefix Filters:"))
        url_filter_lbl.setObjectName("stat_label")
        url_filter_row.addWidget(url_filter_lbl)
        url_filter_row.addStretch()
        cfg_btn = QPushButton(_("Configure…"))
        cfg_btn.setIcon(get_icon("filter"))
        cfg_btn.setToolTip(
            _("Manage URL prefixes (e.g. chrome://, about:, data:) that are silently excluded from history collection.")
        )
        cfg_btn.clicked.connect(self.configure_url_filters_requested)
        url_filter_row.addWidget(cfg_btn)
        layout.addLayout(url_filter_row)

        url_filter_hint = QLabel(
            _("URLs starting with filtered prefixes are never stored (e.g. chrome://, about:, data:).")
        )
        url_filter_hint.setObjectName("muted")
        url_filter_hint.setWordWrap(True)
        layout.addWidget(url_filter_hint)

        # ── Hidden records row ────────────────────────────────
        hidden_header = QHBoxLayout()
        hidden_lbl = QLabel(_("Hidden Records:"))
        hidden_lbl.setObjectName("stat_label")
        self._hidden_count_lbl = QLabel("")
        self._hidden_count_lbl.setObjectName("muted")
        clear_btn = QPushButton(_("Unhide All"))
        clear_btn.setIcon(get_icon("eye"))
        clear_btn.clicked.connect(self.clear_hidden_requested)
        hidden_header.addWidget(hidden_lbl)
        hidden_header.addWidget(self._hidden_count_lbl)
        hidden_header.addStretch()
        hidden_header.addWidget(clear_btn)
        layout.addLayout(hidden_header)

    # ── Public API ────────────────────────────────────────────

    def refresh_blacklist_count(self, count: int) -> None:
        """Update the domain count label next to the Blacklisted Domains header."""
        if count:
            self._bl_count_lbl.setText(_("{n} domains").format(n=count))
        else:
            self._bl_count_lbl.setText(_("none"))

    def refresh_hidden_count(self, count: int) -> None:
        self._hidden_count_lbl.setText(_("{n} records hidden").format(n=count))
