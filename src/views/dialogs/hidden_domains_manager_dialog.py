# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
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

log = get_logger("view.hidden_domains_manager_dialog")


class HiddenDomainsManagerDialog(QDialog):
    """Modal dialog for reviewing, adding, and removing hidden-domain entries.

    Each row shows the domain, its scope (exact subdomain vs. whole domain),
    and a Remove button.  Removals are collected and applied only when the
    caller invokes :meth:`apply_removals` after the dialog is accepted.
    New domains added here are exposed via :attr:`domains_to_add`.

    Usage::

        dlg = HiddenDomainsManagerDialog(vm.get_hidden_domains(), parent=self)
        dlg.exec()
        for domain in dlg.domains_to_remove:
            vm.unhide_domain(domain)
        for entry in dlg.domains_to_add:
            vm.hide_domain(entry["domain"], entry["subdomain_only"], auto_hide=True)
    """

    def __init__(
        self,
        hidden_domains: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Hidden Domains"))
        self.setMinimumWidth(540)
        self.setMinimumHeight(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Work on a copy so we can preview removals without touching the DB.
        self._entries: list[dict] = list(hidden_domains)
        self._to_remove: list[str] = []
        self._to_add: list[dict] = []
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
                "Domains listed here are <b>soft-hidden</b>: their records remain in the "
                "database but are filtered from the History view.  Records from hidden "
                "domains that arrive via sync are also hidden automatically.\n"
                "Remove a domain to make its records visible again."
            )
        )
        desc.setWordWrap(True)
        desc.setObjectName("muted")
        desc.setTextFormat(Qt.RichText)
        root.addWidget(desc)

        # ── Divider ───────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # ── Add row ───────────────────────────────────────────
        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(_("e.g.  example.com"))
        self._input.setMinimumWidth(240)
        self._input.returnPressed.connect(self._on_add)

        self._subdomain_only_chk = QCheckBox(_("Subdomain only"))
        self._subdomain_only_chk.setToolTip(
            _("If checked, only hide the exact subdomain entered. Otherwise hide the domain and all its subdomains.")
        )

        add_btn = QPushButton(_("Add"))
        add_btn.setIcon(get_icon("plus"))
        add_btn.setDefault(False)
        add_btn.setAutoDefault(False)
        add_btn.clicked.connect(self._on_add)

        add_row.addWidget(self._input, 1)
        add_row.addWidget(self._subdomain_only_chk)
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

        # ── Bottom bar ────────────────────────────────────────
        bottom = QHBoxLayout()
        self._remove_all_btn = QPushButton(_("Remove All"))
        self._remove_all_btn.setIcon(get_icon("x"))
        self._remove_all_btn.setToolTip(_("Remove all hidden-domain entries (records become visible again)"))
        self._remove_all_btn.clicked.connect(self._on_remove_all)
        bottom.addWidget(self._remove_all_btn)
        bottom.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        close_btn = btn_box.button(QDialogButtonBox.Close)
        if close_btn:
            close_btn.setDefault(True)
        bottom.addWidget(btn_box)
        root.addLayout(bottom)

    # ── List management ───────────────────────────────────────

    def _refresh_list(self) -> None:
        """Rebuild the scrollable rows from the current ``self._entries``."""
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._entries:
            empty_lbl = QLabel(_("No hidden domains — all domains are visible."))
            empty_lbl.setObjectName("muted")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty_lbl)
            self._remove_all_btn.setEnabled(False)
            return

        self._remove_all_btn.setEnabled(True)
        for entry in self._entries:
            row = self._make_row(entry)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _make_row(self, entry: dict) -> QWidget:
        domain: str = entry["domain"]
        subdomain_only: bool = entry["subdomain_only"]

        wrapper = QWidget()
        wrapper.setObjectName("prefix_row")
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(8)

        # Domain label
        lbl = QLabel(f"<code>{domain}</code>")
        lbl.setTextFormat(Qt.RichText)
        h.addWidget(lbl, 1)

        # Scope badge
        scope_text = _("subdomain only") if subdomain_only else _("domain + subdomains")
        scope_lbl = QLabel(scope_text)
        scope_lbl.setObjectName("muted")
        h.addWidget(scope_lbl)

        # Remove button
        remove_btn = QPushButton(_("Remove"))
        remove_btn.setIcon(get_icon("eye"))
        remove_btn.setDefault(False)
        remove_btn.setAutoDefault(False)
        remove_btn.setToolTip(_("Unhide this domain — its records will become visible again"))
        remove_btn.clicked.connect(lambda _, d=domain: self._on_remove(d))
        h.addWidget(remove_btn)

        return wrapper

    # ── Event overrides ───────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)

    # ── Slots ─────────────────────────────────────────────────

    def _on_add(self) -> None:
        raw = self._input.text().strip().lower()
        if not raw:
            return
        # Skip if already in the current visible list
        if any(e["domain"] == raw for e in self._entries):
            self._input.clear()
            return
        subdomain_only = self._subdomain_only_chk.isChecked()
        entry = {"domain": raw, "subdomain_only": subdomain_only}
        self._entries.insert(0, entry)
        self._to_add.append(entry)
        # If it was previously queued for removal, cancel that
        if raw in self._to_remove:
            self._to_remove.remove(raw)
        self._input.clear()
        self._refresh_list()
        log.debug("Queued domain for hiding: %s (subdomain_only=%s)", raw, subdomain_only)

    def _on_remove(self, domain: str) -> None:
        self._entries = [e for e in self._entries if e["domain"] != domain]
        if domain not in self._to_remove:
            self._to_remove.append(domain)
        # If it was just added in this session, cancel the add instead
        self._to_add = [e for e in self._to_add if e["domain"] != domain]
        self._refresh_list()
        log.debug("Marked domain for unhiding: %s", domain)

    def _on_remove_all(self) -> None:
        for entry in self._entries:
            d = entry["domain"]
            if d not in self._to_remove:
                self._to_remove.append(d)
        self._entries.clear()
        self._to_add.clear()
        self._refresh_list()
        log.debug("Marked all domains for unhiding (%d total)", len(self._to_remove))

    # ── Public API ────────────────────────────────────────────

    @property
    def domains_to_remove(self) -> list[str]:
        """Domains the user requested to unhide (to be applied by the caller)."""
        return list(self._to_remove)

    @property
    def domains_to_add(self) -> list[dict]:
        """New domains the user added, each a dict with 'domain' and 'subdomain_only'."""
        return list(self._to_add)
