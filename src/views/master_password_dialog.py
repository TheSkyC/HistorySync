# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.logger import get_logger
from src.utils.master_key_manager import get_session, hash_password, verify_password

log = get_logger("view.master_password_dialog")


# ── shared helpers ─────────────────────────────────────────────────────────────


def _password_field(placeholder: str = "") -> QLineEdit:
    w = QLineEdit()
    w.setEchoMode(QLineEdit.Password)
    w.setPlaceholderText(placeholder)
    w.setMinimumWidth(280)
    return w


def _eye_toggle(field: QLineEdit, parent: QWidget | None = None) -> QPushButton:
    from src.utils.icon_helper import get_icon

    btn = QPushButton(parent)
    btn.setFixedSize(32, 32)
    btn.setCheckable(True)
    btn.setToolTip(_("Show / hide password"))
    btn.setStyleSheet("QPushButton { border: none; background: transparent; }")
    icon = get_icon("eye", 16)
    if not icon.isNull():
        btn.setIcon(icon)

    def _toggle(checked: bool):
        field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    btn.toggled.connect(_toggle)
    return btn


def _field_row(label_text: str, field: QLineEdit) -> QHBoxLayout:
    row = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setMinimumWidth(120)
    row.addWidget(lbl)
    row.addWidget(field)
    row.addWidget(_eye_toggle(field))
    return row


# ── Reuse _StrengthBar and _pw_score from the wizard ──────────────────────────


def _get_strength_helpers():
    """Import shared strength UI from first_run_wizard to avoid duplication."""
    from src.views.first_run_wizard import _pw_score, _StrengthBar

    return _StrengthBar, _pw_score


# ── Unlock dialog ──────────────────────────────────────────────────────────────


class MasterPasswordUnlockDialog(QDialog):
    """Prompt the user to enter the master password to unlock the session."""

    def __init__(self, stored_hash: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stored_hash = stored_hash
        self.setWindowTitle(_("Master Password Required"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        from src.utils.icon_helper import get_icon

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        px = get_icon("lock", 32).pixmap(32, 32)
        if not px.isNull():
            icon_lbl.setPixmap(px)
        layout.addWidget(icon_lbl, 0, Qt.AlignCenter)

        title = QLabel(_("This action is protected by a master password."))
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(title)

        layout.addSpacing(4)

        self._pw_field = _password_field(_("Enter master password…"))
        self._pw_field.returnPressed.connect(self._accept)
        layout.addLayout(_field_row(_("Password:"), self._pw_field))

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #e05252; font-size: 12px;")
        self._error_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._error_label)

        btn_box = QDialogButtonBox()
        self._ok_btn = btn_box.addButton(_("Unlock"), QDialogButtonBox.AcceptRole)
        self._ok_btn.setObjectName("primary_btn")
        btn_box.addButton(QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _accept(self) -> None:
        pw = self._pw_field.text()
        if not pw:
            self._error_label.setText(_("Please enter the password."))
            return
        if verify_password(pw, self._stored_hash):
            get_session().unlock()
            log.info("Master password: session unlocked via dialog")
            self.accept()
        else:
            self._error_label.setText(_("Incorrect password. Please try again."))
            self._pw_field.clear()
            self._pw_field.setFocus()
            log.warning("Master password: incorrect password entered")


# ── Set (first time) dialog ────────────────────────────────────────────────────


class MasterPasswordSetDialog(QDialog):
    """Let the user set a master password for the first time."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._new_hash: str = ""
        self.setWindowTitle(_("Set Master Password"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(440)
        self._build_ui()

    def _build_ui(self) -> None:
        from src.utils.icon_helper import get_icon

        _StrengthBar, _pw_score = _get_strength_helpers()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setFixedSize(20, 20)
        px = get_icon("lock", 18).pixmap(18, 18)
        if not px.isNull():
            title_icon.setPixmap(px)
        title_row.addWidget(title_icon)
        title = QLabel(_("Set a Master Password"))
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(
            _(
                "The master password protects sensitive settings (WebDAV credentials, sync config, privacy rules). "
                "You will be asked to enter it before any protected action."
            )
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(desc)

        layout.addSpacing(6)

        self._pw1 = _password_field(_("New password…"))
        self._pw2 = _password_field(_("Confirm password…"))
        self._pw2.returnPressed.connect(self._accept)

        layout.addLayout(_field_row(_("New password:"), self._pw1))

        # Strength bar aligned with input field (lbl=120 + eye=32 gap)
        bar_container = QHBoxLayout()
        bar_container.setContentsMargins(124, 0, 36, 0)
        self._strength_bar = _StrengthBar()
        self._strength_bar.setFixedHeight(28)
        bar_container.addWidget(self._strength_bar)
        layout.addLayout(bar_container)

        layout.addLayout(_field_row(_("Confirm:"), self._pw2))

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #e05252; font-size: 12px;")
        layout.addWidget(self._error_label)

        btn_box = QDialogButtonBox()
        ok = btn_box.addButton(_("Set Password"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary_btn")
        btn_box.addButton(QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._pw_score = _pw_score
        self._pw1.textChanged.connect(self._update_strength)

    def _update_strength(self, text: str) -> None:
        self._strength_bar.set_score(self._pw_score(text))

    def _accept(self) -> None:
        pw1 = self._pw1.text()
        pw2 = self._pw2.text()
        if not pw1:
            self._error_label.setText(_("Password cannot be empty."))
            return
        if len(pw1) < 4:
            self._error_label.setText(_("Password must be at least 4 characters."))
            return
        if pw1 != pw2:
            self._error_label.setText(_("Passwords do not match."))
            self._pw2.clear()
            self._pw2.setFocus()
            return
        self._new_hash = hash_password(pw1)
        get_session().unlock()
        log.info("Master password: new password set")
        self.accept()

    def get_hash(self) -> str:
        return self._new_hash


# ── Change dialog ──────────────────────────────────────────────────────────────


class MasterPasswordChangeDialog(QDialog):
    """Let the user change an existing master password."""

    def __init__(self, stored_hash: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stored_hash = stored_hash
        self._new_hash: str = ""
        self.setWindowTitle(_("Change Master Password"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(440)
        self._build_ui()

    def _build_ui(self) -> None:
        from src.utils.icon_helper import get_icon

        _StrengthBar, _pw_score = _get_strength_helpers()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setFixedSize(20, 20)
        px = get_icon("settings", 18).pixmap(18, 18)
        if not px.isNull():
            title_icon.setPixmap(px)
        title_row.addWidget(title_icon)
        title = QLabel(_("Change Master Password"))
        title.setStyleSheet("font-size: 14px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        layout.addSpacing(4)

        self._old_pw = _password_field(_("Current password…"))
        self._new_pw1 = _password_field(_("New password…"))
        self._new_pw2 = _password_field(_("Confirm new password…"))
        self._new_pw2.returnPressed.connect(self._accept)

        layout.addLayout(_field_row(_("Current password:"), self._old_pw))
        layout.addLayout(_field_row(_("New password:"), self._new_pw1))

        # Strength bar
        bar_container = QHBoxLayout()
        bar_container.setContentsMargins(124, 0, 36, 0)
        self._strength_bar = _StrengthBar()
        self._strength_bar.setFixedHeight(22)
        bar_container.addWidget(self._strength_bar)
        layout.addLayout(bar_container)

        layout.addLayout(_field_row(_("Confirm:"), self._new_pw2))

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #e05252; font-size: 12px;")
        layout.addWidget(self._error_label)

        btn_box = QDialogButtonBox()
        ok = btn_box.addButton(_("Change Password"), QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary_btn")
        btn_box.addButton(QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._pw_score = _pw_score
        self._new_pw1.textChanged.connect(self._update_strength)

    def _update_strength(self, text: str) -> None:
        self._strength_bar.set_score(self._pw_score(text))

    def _accept(self) -> None:
        old_pw = self._old_pw.text()
        new_pw1 = self._new_pw1.text()
        new_pw2 = self._new_pw2.text()

        if not verify_password(old_pw, self._stored_hash):
            self._error_label.setText(_("Current password is incorrect."))
            self._old_pw.clear()
            self._old_pw.setFocus()
            return
        if not new_pw1:
            self._error_label.setText(_("New password cannot be empty."))
            return
        if len(new_pw1) < 4:
            self._error_label.setText(_("New password must be at least 4 characters."))
            return
        if new_pw1 != new_pw2:
            self._error_label.setText(_("New passwords do not match."))
            self._new_pw2.clear()
            self._new_pw2.setFocus()
            return
        self._new_hash = hash_password(new_pw1)
        get_session().unlock()
        log.info("Master password: password changed")
        self.accept()

    def get_hash(self) -> str:
        return self._new_hash


# ── Convenience guard ─────────────────────────────────────────────────────────


def require_master_password(stored_hash: str, parent: QWidget | None = None) -> bool:
    """Return True if the caller may proceed with a protected action.

    * No password set → always allowed.
    * Session already unlocked → allowed (touch the session to extend TTL).
    * Session locked → show the unlock dialog.
    """
    if not stored_hash:
        return True
    session = get_session()
    if session.is_unlocked:
        session.touch()
        return True
    dlg = MasterPasswordUnlockDialog(stored_hash, parent)
    return dlg.exec() == QDialog.Accepted
