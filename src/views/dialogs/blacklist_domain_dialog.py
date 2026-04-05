# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger

log = get_logger("view.blacklist_domain_dialog")


class BlacklistDomainDialog(QDialog):
    """
    Modal dialog for managing blacklisted domains.

    Domains in this list are permanently excluded from sync; all history
    records matching a blacklisted domain are deleted from the database
    when the domain is first added.

    Usage::

        dlg = BlacklistDomainDialog(current_domains, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_domains = dlg.get_domains()
    """

    def __init__(self, current_domains: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Blacklisted Domains"))
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Working copy — never mutate the caller's list directly.
        self._domains: list[str] = list(current_domains)

        self._build_ui()
        self._refresh_list()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 16, 20, 16)

        # ── Description ───────────────────────────────────────
        desc = QLabel(
            _(
                "Domains listed here are <b>permanently excluded</b> from sync. "
                "All history records for a blacklisted domain are deleted from the "
                "database as soon as the domain is added."
            )
        )
        desc.setWordWrap(True)
        desc.setObjectName("muted")
        desc.setTextFormat(Qt.RichText)
        root.addWidget(desc)

        # ── Add row ───────────────────────────────────────────
        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(_("e.g.  example.com"))
        self._input.setMinimumWidth(280)
        self._input.returnPressed.connect(self._on_add)

        add_btn = QPushButton(_("Add"))
        add_btn.setIcon(get_icon("plus"))
        add_btn.setDefault(False)
        add_btn.setAutoDefault(False)
        add_btn.clicked.connect(self._on_add)

        add_row.addWidget(self._input, 1)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        # ── Scrollable domain list ────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.StyledPanel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, 1)

        # ── Bottom bar: dialog buttons ─────────────────────────
        bottom = QHBoxLayout()
        bottom.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        # Prevent OK from being the default button so that pressing Enter
        # in the input adds a domain instead of closing the dialog.
        ok_btn = btn_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setDefault(False)
            ok_btn.setAutoDefault(False)

        bottom.addWidget(btn_box)
        root.addLayout(bottom)

    # ── List management ───────────────────────────────────────

    def _refresh_list(self) -> None:
        """Rebuild the scrollable rows from ``self._domains``."""
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._domains:
            empty_lbl = QLabel(_("No domains blacklisted — all domains are accepted."))
            empty_lbl.setObjectName("muted")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty_lbl)
            return

        for domain in self._domains:
            row_widget = self._make_row(domain)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row_widget)

    def _make_row(self, domain: str) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("prefix_row")
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(8)

        lbl = QLabel(f"<code>{domain}</code>")
        lbl.setTextFormat(Qt.RichText)
        lbl.setObjectName("muted")
        h.addWidget(lbl, 1)

        remove_btn = QPushButton(_("Remove"))
        remove_btn.setIcon(get_icon("x"))
        remove_btn.setDefault(False)
        remove_btn.setAutoDefault(False)
        remove_btn.clicked.connect(lambda _, d=domain: self._on_remove(d))
        h.addWidget(remove_btn)

        return wrapper

    # ── Slots ─────────────────────────────────────────────────

    def _on_add(self) -> None:
        raw = self._input.text().strip().lower()
        if not raw:
            return
        if raw in self._domains:
            self._input.clear()
            return
        self._domains.append(raw)
        self._input.clear()
        self._refresh_list()
        log.debug("Added domain to blacklist: %s", raw)

    def _on_remove(self, domain: str) -> None:
        if domain in self._domains:
            self._domains.remove(domain)
            self._refresh_list()
            log.debug("Removed domain from blacklist: %s", domain)

    # ── Public API ────────────────────────────────────────────

    def get_domains(self) -> list[str]:
        """Return the (possibly modified) domain list after dialog is accepted."""
        return list(self._domains)
