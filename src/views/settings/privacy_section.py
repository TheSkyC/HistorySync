# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class PrivacySection(QWidget):
    """Privacy & blacklist card.

    Signals:
        add_domain_requested(domain: str)
        remove_domain_requested(domain: str)
        clear_hidden_requested()
        configure_url_filters_requested()

    Exposes:
        refresh_blacklist(domains: list[str])
        refresh_hidden_count(count: int)
        get_pending_domain() -> str
        clear_domain_input()
    """

    add_domain_requested = Signal(str)
    remove_domain_requested = Signal(str)
    clear_hidden_requested = Signal()
    configure_url_filters_requested = Signal()

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

        # Blacklist header
        bl_header = QHBoxLayout()
        bl_lbl = QLabel(_("Blacklisted Domains:"))
        bl_lbl.setObjectName("stat_label")
        bl_header.addWidget(bl_lbl)
        bl_header.addStretch()
        layout.addLayout(bl_header)

        # Add row
        bl_add_row = QHBoxLayout()
        self._bl_input = QLineEdit()
        self._bl_input.setPlaceholderText(_("example.com"))
        add_btn = QPushButton(_("Add"))
        add_btn.setIcon(get_icon("plus"))
        add_btn.clicked.connect(self._on_add_clicked)
        self._bl_input.returnPressed.connect(self._on_add_clicked)
        bl_add_row.addWidget(self._bl_input, 1)
        bl_add_row.addWidget(add_btn)
        layout.addLayout(bl_add_row)

        # Dynamic blacklist entries
        self._blacklist_container = QVBoxLayout()
        self._blacklist_container.setSpacing(4)
        layout.addLayout(self._blacklist_container)

        # ── URL Prefix Filters button ─────────────────────────
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

        # Hidden records row
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

    def refresh_blacklist(self, domains: list[str]):
        while self._blacklist_container.count():
            item = self._blacklist_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for domain in domains:
            row = QHBoxLayout()
            lbl = QLabel(f"🚫  {domain}")
            lbl.setObjectName("muted")
            remove_btn = QPushButton(_("Remove"))
            remove_btn.setIcon(get_icon("x"))
            remove_btn.clicked.connect(lambda _, d=domain: self.remove_domain_requested.emit(d))
            row.addWidget(lbl, 1)
            row.addWidget(remove_btn)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self._blacklist_container.addWidget(wrapper)

    def refresh_hidden_count(self, count: int):
        self._hidden_count_lbl.setText(_("{n} records hidden").format(n=count))

    def get_pending_domain(self) -> str:
        return self._bl_input.text().strip().lower()

    def clear_domain_input(self):
        self._bl_input.clear()

    def set_domain_input(self, domain: str):
        """Pre-fill the domain input (e.g. called from history page)."""
        self._bl_input.setText(domain)

    # ── Internal ──────────────────────────────────────────────

    def _on_add_clicked(self):
        domain = self.get_pending_domain()
        if domain:
            self.add_domain_requested.emit(domain)
