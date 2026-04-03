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
from src.utils.logger import get_logger
from src.utils.master_key_manager import get_session

log = get_logger("view.settings.security")


class SecuritySection(QWidget):
    """
    Master password management panel.
    Emits password_changed(new_hash) signal, which SettingsPage handles to write to config.
    """

    password_changed = Signal(str)  # new_hash (empty string = removed)
    lock_session_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stored_hash: str = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        # ── Status Row ─────────────────────────────────────────
        status_row = QHBoxLayout()
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(24, 24)
        self._status_label = QLabel(_("No master password set"))
        self._status_label.setStyleSheet("")
        status_row.addWidget(self._status_icon)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        # ── Description ────────────────────────────────────────
        self._desc_label = QLabel(
            _(
                "A master password protects sensitive settings from unauthorized changes.\n"
                "You will be prompted before modifying WebDAV credentials, sync config, or privacy rules."
            )
        )
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: #888;")
        layout.addWidget(self._desc_label)

        # ── Button Row ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._set_btn = QPushButton(_("Set Master Password"))
        self._set_btn.setObjectName("primary_btn")
        self._set_btn.clicked.connect(self._on_set_password)

        self._change_btn = QPushButton(_("Change Password"))
        self._change_btn.clicked.connect(self._on_change_password)
        self._change_btn.setVisible(False)

        self._remove_btn = QPushButton(_("Remove Password"))
        self._remove_btn.setStyleSheet("color: #e05252;")
        self._remove_btn.clicked.connect(self._on_remove_password)
        self._remove_btn.setVisible(False)

        self._lock_btn = QPushButton(_("Lock Session"))
        self._lock_btn.setToolTip(_("Lock the current session — next protected action will require the password"))
        self._lock_btn.clicked.connect(self._on_lock_session)
        self._lock_btn.setVisible(False)

        btn_row.addWidget(self._set_btn)
        btn_row.addWidget(self._change_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._lock_btn)
        layout.addLayout(btn_row)

        # ── Session Status Hint ────────────────────────────────
        self._session_label = QLabel("")
        self._session_label.setStyleSheet("color: #888;")
        layout.addWidget(self._session_label)

    # ── Public Interfaces ─────────────────────────────────────

    def load(self, stored_hash: str):
        """Load the current master password hash from config (empty string = not set)."""
        self._stored_hash = stored_hash
        self._refresh_ui()

    def _refresh_ui(self):
        from src.utils.icon_helper import get_icon

        has_password = bool(self._stored_hash)
        session = get_session()
        unlocked = session.is_unlocked

        if has_password:
            px = get_icon("lock", 20).pixmap(20, 20)
            if not px.isNull():
                self._status_icon.setPixmap(px)
            self._status_label.setText(_("Master password is set"))
            self._status_label.setStyleSheet("color: #34a853;")
            self._set_btn.setVisible(False)
            self._change_btn.setVisible(True)
            self._remove_btn.setVisible(True)
            self._lock_btn.setVisible(unlocked)
            if unlocked:
                self._session_label.setText(_("Session unlocked — no password required until you lock or restart"))
                self._session_label.setStyleSheet("color: #34a853;")
            else:
                self._session_label.setText(_("Session locked — password will be requested on next protected action"))
                self._session_label.setStyleSheet("color: #888;")
        else:
            px = get_icon("shield", 20).pixmap(20, 20)
            if not px.isNull():
                self._status_icon.setPixmap(px)
            self._status_label.setText(_("No master password set"))
            self._status_label.setStyleSheet("color: #888;")
            self._set_btn.setVisible(True)
            self._change_btn.setVisible(False)
            self._remove_btn.setVisible(False)
            self._lock_btn.setVisible(False)
            self._session_label.setText("")

    # ── Button Handlers ───────────────────────────────────────

    def _on_set_password(self):
        from src.views.master_password_dialog import MasterPasswordSetDialog

        dlg = MasterPasswordSetDialog(self)
        if dlg.exec():
            new_hash = dlg.get_hash()
            self._stored_hash = new_hash
            self.password_changed.emit(new_hash)
            self._refresh_ui()
            log.info("Master password set from Security section")

    def _on_change_password(self):
        from src.views.master_password_dialog import (
            MasterPasswordChangeDialog,
            require_master_password,
        )

        if not require_master_password(self._stored_hash, self):
            return
        dlg = MasterPasswordChangeDialog(self._stored_hash, self)
        if dlg.exec():
            new_hash = dlg.get_hash()
            self._stored_hash = new_hash
            self.password_changed.emit(new_hash)
            self._refresh_ui()
            log.info("Master password changed from Security section")

    def _on_remove_password(self):
        from PySide6.QtWidgets import QMessageBox

        from src.views.master_password_dialog import require_master_password

        if not require_master_password(self._stored_hash, self):
            return

        reply = QMessageBox.warning(
            self,
            _("Remove Master Password"),
            _("Are you sure you want to remove the master password?\n\nThis will leave your settings unprotected."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._stored_hash = ""
            get_session().lock()
            self.password_changed.emit("")
            self._refresh_ui()
            log.info("Master password removed")

    def _on_lock_session(self):
        get_session().lock()
        self.lock_session_requested.emit()
        self._refresh_ui()
        log.info("Session locked from Security section")
