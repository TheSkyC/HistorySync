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
        configure_hidden_domains_requested()

    Exposes:
        refresh_blacklist_count(count: int)
        refresh_hidden_domains_count(count: int)
    """

    configure_blacklist_requested = Signal()
    configure_url_filters_requested = Signal()
    configure_hidden_domains_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

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

        # ── Hidden Domains row ────────────────────────────────
        hd_row = QHBoxLayout()
        hd_lbl = QLabel(_("Hidden Domains:"))
        hd_lbl.setObjectName("stat_label")
        self._hd_count_lbl = QLabel("")
        self._hd_count_lbl.setObjectName("muted")
        hd_manage_btn = QPushButton(_("Configure…"))
        hd_manage_btn.setIcon(get_icon("eye-off"))
        hd_manage_btn.setToolTip(
            _(
                "Manage soft-hidden domains. Records from hidden domains remain in the database but are excluded from the History view."
            )
        )
        hd_manage_btn.clicked.connect(self.configure_hidden_domains_requested)
        hd_row.addWidget(hd_lbl)
        hd_row.addWidget(self._hd_count_lbl)
        hd_row.addStretch()
        hd_row.addWidget(hd_manage_btn)
        layout.addLayout(hd_row)

    # ── Public API ────────────────────────────────────────────

    def refresh_blacklist_count(self, count: int) -> None:
        """Update the domain count label next to the Blacklisted Domains header."""
        if count:
            self._bl_count_lbl.setText(_("{n} domains").format(n=count))
        else:
            self._bl_count_lbl.setText(_("none"))

    def refresh_hidden_domains_count(self, count: int) -> None:
        """Update the count label next to the Hidden Domains header."""
        if count:
            self._hd_count_lbl.setText(_("{n} domains").format(n=count))
        else:
            self._hd_count_lbl.setText(_("none"))
