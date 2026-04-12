# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class HideDomainDialog(QDialog):
    """Confirmation dialog shown before hiding a domain.

    Displays how many records will be hidden immediately, and lets the user
    opt in or out of automatic hiding for records that arrive in future syncs.

    Usage::

        dlg = HideDomainDialog(domain, subdomain_only, record_count, parent=self)
        if dlg.exec() == QDialog.Accepted:
            auto_hide = dlg.auto_hide
    """

    def __init__(
        self,
        domain: str,
        subdomain_only: bool,
        record_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._domain = domain
        self._subdomain_only = subdomain_only
        self._record_count = record_count

        if subdomain_only:
            self.setWindowTitle(_("Hide Subdomain"))
        else:
            self.setWindowTitle(_("Hide Domain"))

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(420)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(24, 20, 24, 16)

        # ── Domain badge ──────────────────────────────────────
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("eye-off").pixmap(20, 20))
        domain_lbl = QLabel(f"<b>{self._domain}</b>")
        domain_lbl.setTextFormat(Qt.RichText)
        badge_row.addWidget(icon_lbl)
        badge_row.addSpacing(6)
        badge_row.addWidget(domain_lbl)
        badge_row.addStretch()
        root.addLayout(badge_row)

        # ── Divider ───────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # ── Scope description ─────────────────────────────────
        if self._subdomain_only:
            scope_text = _("Only records from the exact subdomain <b>{domain}</b> will be hidden.").format(
                domain=self._domain
            )
        else:
            scope_text = _("Records from <b>{domain}</b> and all its subdomains will be hidden.").format(
                domain=self._domain
            )
        scope_lbl = QLabel(scope_text)
        scope_lbl.setWordWrap(True)
        scope_lbl.setTextFormat(Qt.RichText)
        root.addWidget(scope_lbl)

        # ── Record count ──────────────────────────────────────
        if self._record_count == 0:
            count_text = _("No existing records match this domain — only future records will be affected.")
        elif self._record_count == 1:
            count_text = _("<b>1</b> existing record will be hidden immediately.")
        else:
            count_text = _("<b>{n}</b> existing records will be hidden immediately.").format(n=self._record_count)
        count_lbl = QLabel(count_text)
        count_lbl.setWordWrap(True)
        count_lbl.setTextFormat(Qt.RichText)
        count_lbl.setObjectName("muted")
        root.addWidget(count_lbl)

        # ── Auto-hide checkbox ────────────────────────────────
        self._auto_hide_cb = QCheckBox(_("Automatically hide new records from this domain in future syncs"))
        self._auto_hide_cb.setChecked(True)
        self._auto_hide_cb.setToolTip(
            _(
                "When enabled, the domain is saved to your hidden-domains list and records\n"
                "imported from any synced device will be filtered automatically.\n"
                "You can manage hidden domains in Settings → Privacy."
            )
        )
        root.addWidget(self._auto_hide_cb)

        # ── Unhide hint ───────────────────────────────────────
        hint_lbl = QLabel(_("You can unhide domains anytime in <i>Settings → Privacy</i>."))
        hint_lbl.setObjectName("muted")
        hint_lbl.setTextFormat(Qt.RichText)
        hint_lbl.setWordWrap(True)
        root.addWidget(hint_lbl)

        # ── Buttons ───────────────────────────────────────────
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = btn_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText(_("Hide"))
            ok_btn.setIcon(get_icon("eye-off"))
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    # ── Public API ────────────────────────────────────────────

    @property
    def auto_hide(self) -> bool:
        """True if the user wants future records from this domain auto-hidden."""
        return self._auto_hide_cb.isChecked()
