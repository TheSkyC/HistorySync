# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.models.app_config import DEFAULT_FILTERED_URL_PREFIXES
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.services.local_db import LocalDatabase

log = get_logger("view.url_prefix_filter_dialog")


class UrlPrefixFilterDialog(QDialog):
    """
    Modal dialog for managing filtered URL prefixes.

    Shows the current list of filtered URL prefixes (e.g. ``chrome://``,
    ``about:``, ``data:``) with add / remove controls and a
    *Reset to defaults* button.

    Usage::

        dlg = UrlPrefixFilterDialog(current_prefixes, db, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_prefixes = dlg.get_prefixes()
            deleted_count = dlg.records_deleted  # if user chose to delete
    """

    def __init__(
        self,
        current_prefixes: list[str],
        db: LocalDatabase | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("URL Prefix Filters"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Working copy - we never mutate the caller's list directly.
        self._prefixes: list[str] = list(current_prefixes)
        self._db = db
        self._records_deleted: int = 0

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
                "URLs whose address begins with any of the prefixes below are "
                "silently discarded during extraction and never stored in the "
                "database. This is useful for filtering browser-internal pages "
                "(e.g. <b>chrome://</b>, <b>about:</b>) and protocol handlers "
                "(e.g. <b>data:</b>)."
            )
        )
        desc.setWordWrap(True)
        desc.setObjectName("muted")
        desc.setTextFormat(Qt.RichText)
        root.addWidget(desc)

        # ── Add row ───────────────────────────────────────────
        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(_("e.g.  moz-extension://  or  chrome://"))
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

        # ── Scrollable prefix list ────────────────────────────
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

        # ── Bottom bar: Reset + Delete + dialog buttons ──────────────
        bottom = QHBoxLayout()

        reset_btn = QPushButton(_("Reset to Defaults"))
        reset_btn.setIcon(get_icon("rotate-ccw"))
        reset_btn.setDefault(False)
        reset_btn.setAutoDefault(False)
        reset_btn.setToolTip(_("Restore the built-in default URL prefix list"))
        reset_btn.clicked.connect(self._on_reset)
        bottom.addWidget(reset_btn)

        self._delete_btn = QPushButton(_("Delete Matching Records"))
        self._delete_btn.setIcon(get_icon("trash-2"))
        self._delete_btn.setDefault(False)
        self._delete_btn.setAutoDefault(False)
        self._delete_btn.setToolTip(
            _("Delete existing records that match any of the configured prefixes from the database")
        )
        self._delete_btn.clicked.connect(self._on_delete_matching)
        if not self._db:
            self._delete_btn.setEnabled(False)
        bottom.addWidget(self._delete_btn)

        bottom.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        # Prevent the OK button from acting as the dialog's default button.
        # Without this, pressing Enter in the input field would BOTH call
        # _on_add (via returnPressed) AND immediately close the dialog
        # (via Qt's default-button mechanism) — the user intends to add a
        # filter, not to confirm and exit.
        ok_btn = btn_box.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setDefault(False)
            ok_btn.setAutoDefault(False)

        bottom.addWidget(btn_box)

        root.addLayout(bottom)

    # ── List management ───────────────────────────────────────

    def _refresh_list(self) -> None:
        """Rebuild the scrollable rows from ``self._prefixes``."""
        # Clear existing rows (everything except the trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._prefixes:
            empty_lbl = QLabel(_("No filters configured — all URLs are accepted."))
            empty_lbl.setObjectName("muted")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty_lbl)
            return

        for prefix in self._prefixes:
            row_widget = self._make_row(prefix)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row_widget)

    def _make_row(self, prefix: str) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("prefix_row")
        h = QHBoxLayout(wrapper)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(8)

        lbl = QLabel(f"<code>{prefix}</code>")
        lbl.setTextFormat(Qt.RichText)
        lbl.setObjectName("muted")
        h.addWidget(lbl, 1)

        remove_btn = QPushButton(_("Remove"))
        remove_btn.setIcon(get_icon("x"))
        remove_btn.setDefault(False)
        remove_btn.setAutoDefault(False)
        remove_btn.clicked.connect(lambda _, p=prefix: self._on_remove(p))
        h.addWidget(remove_btn)

        return wrapper

    # ── Event overrides ───────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Swallow Enter/Return so the dialog never closes via keyboard;
        # _input.returnPressed already handles adding the prefix.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(event)

    # ── Slots ─────────────────────────────────────────────────

    def _on_add(self) -> None:
        raw = self._input.text().strip()
        if not raw:
            return

        # Basic normalisation: ensure it ends with "://" or ":"
        prefix = raw
        if not (prefix.endswith("://") or prefix.endswith(":")):
            QMessageBox.warning(
                self,
                _("Invalid Prefix"),
                _(
                    "A URL prefix must end with <b>://</b> (e.g. <code>chrome://</code>) "
                    "or <b>:</b> (e.g. <code>about:</code>).<br><br>"
                    "Entered: <code>{p}</code>"
                ).format(p=prefix),
            )
            return

        if prefix in self._prefixes:
            self._input.clear()
            return

        self._prefixes.append(prefix)
        self._input.clear()
        self._refresh_list()
        log.debug("Added URL prefix filter: %s", prefix)

    def _on_remove(self, prefix: str) -> None:
        if prefix in self._prefixes:
            self._prefixes.remove(prefix)
            self._refresh_list()
            log.debug("Removed URL prefix filter: %s", prefix)

    def _on_reset(self) -> None:
        reply = QMessageBox.question(
            self,
            _("Reset to Defaults"),
            _("This will replace your current filter list with the built-in defaults.\n\nContinue?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._prefixes = list(DEFAULT_FILTERED_URL_PREFIXES)
            self._refresh_list()
            log.info("URL prefix filters reset to defaults")

    def _on_delete_matching(self) -> None:
        """Delete existing records matching the configured prefixes."""
        if not self._db or not self._prefixes:
            return

        record_count = self._db.count_records_by_url_prefixes(self._prefixes)
        if record_count == 0:
            QMessageBox.information(
                self,
                _("No Records Found"),
                _("No existing records match the configured URL prefixes."),
            )
            return

        reply = QMessageBox.question(
            self,
            _("Delete Matching Records"),
            _(
                "This will permanently delete <b>{count}</b> records whose URLs match "
                "any of the configured prefixes from the database.\n\n"
                "This action cannot be undone. Continue?"
            ).format(count=record_count),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._records_deleted = self._db.delete_records_by_url_prefixes(self._prefixes)
            log.info("Deleted %d records matching URL prefixes", self._records_deleted)
            QMessageBox.information(
                self,
                _("Records Deleted"),
                _("Successfully deleted {count} records.").format(count=self._records_deleted),
            )

    # ── Public API ────────────────────────────────────────────

    def get_prefixes(self) -> list[str]:
        """Return the (possibly modified) prefix list after dialog is accepted."""
        return list(self._prefixes)

    @property
    def records_deleted(self) -> int:
        """Return the number of records deleted via the Delete Matching Records button."""
        return self._records_deleted
