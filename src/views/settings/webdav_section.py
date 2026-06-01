# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.models.app_config import WebDavConfig
from src.utils.constants import WEBDAV_DEFAULT_REMOTE_PATH
from src.utils.dialog_utils import exec_centered
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.views.password_edit import PasswordEdit
from src.views.settings._label_utils import constrain_label_width


class WebDavConnectionDialog(QDialog):
    """Child dialog for WebDAV connection details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._decrypt_failed = False
        self._password_dirty = False
        self._has_known_password = False

        self.setWindowTitle(_("WebDAV Connection"))
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        intro_lbl = constrain_label_width(
            QLabel(
                _(
                    "Edit server details here. The password stays out of the main settings page "
                    "and is only resolved when WebDAV is actually used."
                )
            )
        )
        intro_lbl.setObjectName("muted")
        layout.addWidget(intro_lbl)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._url = QLineEdit()
        self._url.setPlaceholderText("https://dav.example.com/dav/")

        self._user = QLineEdit()
        self._user.setPlaceholderText(_("Username").rstrip(":"))

        self._password = PasswordEdit()
        self._password.set_hide_toggle_when_empty(True)
        self._password.textChanged.connect(self._update_password_hint)

        self._path = QLineEdit()
        self._path.setPlaceholderText(WEBDAV_DEFAULT_REMOTE_PATH)

        self._max_backups_spin = QSpinBox()
        self._max_backups_spin.setRange(1, 100)
        self._max_backups_spin.setSuffix(_(" files"))
        self._max_backups_spin.setMinimumWidth(90)

        self._verify_ssl_cb = QCheckBox(_("Verify SSL certificate"))
        self._verify_ssl_cb.setChecked(True)
        self._verify_ssl_cb.toggled.connect(self._on_verify_ssl_toggled)

        self._password_hint_lbl = constrain_label_width(QLabel(""))
        self._password_hint_lbl.setObjectName("muted")

        self._password_warning_lbl = constrain_label_width(
            QLabel(_("The saved password could not be loaded. Enter a new one to replace it."))
        )
        self._password_warning_lbl.setStyleSheet("color: #e07b00;")
        self._password_warning_lbl.setVisible(False)

        self._ssl_warning_lbl = constrain_label_width(
            QLabel(_("Warning: disabling SSL verification exposes WebDAV traffic to man-in-the-middle attacks."))
        )
        self._ssl_warning_lbl.setStyleSheet("color: #e07b00;")
        self._ssl_warning_lbl.setVisible(False)

        form.addRow(_("Server URL:"), self._url)
        form.addRow(_("Username:"), self._user)
        form.addRow(_("Password:"), self._password)
        form.addRow("", self._password_hint_lbl)
        form.addRow("", self._password_warning_lbl)
        form.addRow(_("Remote Path:"), self._path)
        form.addRow(_("Max backups:"), self._max_backups_spin)
        form.addRow("", self._verify_ssl_cb)
        form.addRow("", self._ssl_warning_lbl)
        layout.addLayout(form)

        layout.addStretch()

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def load(
        self,
        cfg: WebDavConfig,
        *,
        password_dirty: bool = False,
        decrypt_failed: bool = False,
        has_known_password: bool = False,
    ) -> None:
        self._decrypt_failed = decrypt_failed
        self._password_dirty = password_dirty
        self._has_known_password = has_known_password

        self._url.setText(cfg.url)
        self._user.setText(cfg.username)
        self._password.clear()
        self._path.setText(cfg.remote_path)
        self._max_backups_spin.setValue(cfg.max_backups)
        self._verify_ssl_cb.setChecked(cfg.verify_ssl)
        self._password_warning_lbl.setVisible(decrypt_failed)

        if decrypt_failed:
            self._password.setPlaceholderText(_("Re-enter password"))
        elif password_dirty:
            self._password.setPlaceholderText(_("Leave blank to keep the pending new password"))
        else:
            self._password.setPlaceholderText(_("Leave blank unless you want to replace the password"))

        self._on_verify_ssl_toggled(cfg.verify_ssl)
        self._update_password_hint()

    def get_config(self) -> WebDavConfig:
        return WebDavConfig(
            url=self._url.text().strip(),
            username=self._user.text().strip(),
            remote_path=self._path.text().strip() or WEBDAV_DEFAULT_REMOTE_PATH,
            max_backups=self._max_backups_spin.value(),
            verify_ssl=self._verify_ssl_cb.isChecked(),
        )

    def get_password(self) -> str:
        return self._password.text()

    def _on_verify_ssl_toggled(self, checked: bool) -> None:
        self._ssl_warning_lbl.setVisible(not checked)

    def _update_password_hint(self) -> None:
        text = self._password.text()
        self._password.refresh_toggle_visibility()

        if text:
            hint = _("Saving will stage a new password for the next Settings save.")
        elif self._decrypt_failed:
            hint = _("A new password is required to recover this WebDAV connection.")
        elif self._password_dirty:
            hint = _("A new password is already staged. Leave this blank to keep that pending change.")
        elif self._has_known_password:
            hint = _("Leave this blank to keep the saved password.")
        else:
            hint = _("Leave this blank to keep the current credential unchanged.")

        self._password_hint_lbl.setText(hint)
        self._password_hint_lbl.setVisible(bool(hint))


class WebDavRemoteBackupsDialog(QDialog):
    """Compact dialog for viewing remote backup files."""

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Remote Backups"))
        self.setMinimumWidth(560)
        self.setMinimumHeight(360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 18, 20, 18)

        top_row = QHBoxLayout()
        title_lbl = QLabel(_("Remote backups"))
        title_lbl.setObjectName("stat_label")
        top_row.addWidget(title_lbl)
        top_row.addStretch()

        self._refresh_btn = QPushButton(_("Refresh"))
        self._refresh_btn.setIcon(get_icon("refresh-ccw", 14))
        self._refresh_btn.clicked.connect(self.refresh_requested)
        top_row.addWidget(self._refresh_btn)
        layout.addLayout(top_row)

        self._status_lbl = constrain_label_width(QLabel(_("Open this window to load the latest remote backup list.")))
        self._status_lbl.setObjectName("muted")
        layout.addWidget(self._status_lbl)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        layout.addWidget(close_box)

    def set_loading(self, loading: bool) -> None:
        self._refresh_btn.setEnabled(not loading)
        if loading:
            self._status_lbl.setText(_("Loading remote backups..."))

    def set_result(self, success: bool, msg: str, backups: list | None) -> None:
        self._list.clear()
        self._status_lbl.setText(msg or (_("Remote backup list updated") if success else _("Failed to load backups")))

        if not success:
            return

        if backups:
            for backup in backups:
                ts = backup.get("timestamp", 0)
                dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
                fmt = backup.get("format", "?").upper()
                self._list.addItem(f"[{fmt}] {backup['filename']}  -  {dt_str}")
            return

        self._list.addItem(_("(no backups found)"))


class WebDavSection(QWidget):
    """WebDAV cloud-backup settings card."""

    action_requested = Signal(str)  # "test" | "backup" | "restore" | "list_backups"
    toggle_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._draft_config = WebDavConfig()
        self._draft_password = ""
        self._password_dirty = False
        self._decrypt_failed = False
        self._has_known_password = False
        self._backups_dialog: WebDavRemoteBackupsDialog | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        self._enabled_cb = QCheckBox(_("Enable WebDAV Backup"))
        self._enabled_cb.stateChanged.connect(lambda _: self._on_toggle())
        layout.addWidget(self._enabled_cb)

        self._auto_backup_cb = QCheckBox(_("Automatically backup to WebDAV after local scan"))

        scheduled_row = QHBoxLayout()
        self._scheduled_cb = QCheckBox(_("Scheduled automatic backup every"))
        self._backup_interval_spin = QSpinBox()
        self._backup_interval_spin.setRange(1, 168)
        self._backup_interval_spin.setSuffix(_(" hours"))
        self._backup_interval_spin.setValue(24)
        scheduled_row.addWidget(self._scheduled_cb)
        scheduled_row.addWidget(self._backup_interval_spin)
        scheduled_row.addStretch()
        layout.addLayout(scheduled_row)

        next_backup_row = QHBoxLayout()
        next_backup_row.setSpacing(6)
        self._next_backup_icon_lbl = QLabel()
        self._next_backup_icon_lbl.setPixmap(get_icon("refresh-ccw", 14).pixmap(14, 14))
        self._next_backup_icon_lbl.setFixedSize(14, 14)
        self._next_backup_lbl = constrain_label_width(QLabel(""))
        self._next_backup_lbl.setObjectName("muted")
        next_backup_row.addWidget(self._next_backup_icon_lbl)
        next_backup_row.addWidget(self._next_backup_lbl, 1)
        next_backup_row.addStretch()
        self._next_backup_icon_lbl.hide()
        self._next_backup_lbl.hide()
        layout.addLayout(next_backup_row)

        self._backup_favicons_cb = QCheckBox(_("Include favicon cache in backup"))
        self._backup_favicons_cb.setToolTip(
            _("Backs up the favicon database alongside history. Increases backup size.")
        )
        layout.addWidget(self._backup_favicons_cb)

        summary_col = QVBoxLayout()
        summary_col.setSpacing(6)
        self._connection_summary_lbl = constrain_label_width(QLabel(""))
        self._connection_summary_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._password_status_lbl = constrain_label_width(QLabel(""))
        self._password_status_lbl.setObjectName("muted")
        self._password_status_lbl.setVisible(False)
        self._password_warning_lbl = constrain_label_width(
            QLabel(_("Password could not be decrypted. Open Connection Settings and enter it again."))
        )
        self._password_warning_lbl.setStyleSheet("color: #e07b00;")
        self._password_warning_lbl.setVisible(False)

        summary_col.addWidget(self._connection_summary_lbl)

        action_hint_row = QHBoxLayout()
        action_hint_row.setSpacing(8)
        self._edit_connection_btn = QPushButton(_("Connection Settings..."))
        self._edit_connection_btn.setIcon(get_icon("pencil"))
        self._edit_connection_btn.clicked.connect(self._open_connection_dialog)
        action_hint_row.addWidget(self._edit_connection_btn)

        self._discard_password_btn = QPushButton(_("Undo Password Change"))
        self._discard_password_btn.setVisible(False)
        self._discard_password_btn.clicked.connect(self._discard_pending_password_change)
        action_hint_row.addWidget(self._discard_password_btn)
        action_hint_row.addStretch()
        summary_col.addLayout(action_hint_row)
        summary_col.addWidget(self._password_status_lbl)
        summary_col.addWidget(self._password_warning_lbl)
        layout.addLayout(summary_col)

        self._test_btn = QPushButton(_("Test Connection"))
        self._test_btn.setIcon(get_icon("zap"))
        self._test_btn.clicked.connect(lambda: self.action_requested.emit("test"))

        self._list_btn = QPushButton(_("Remote Backups..."))
        self._list_btn.setIcon(get_icon("list"))
        self._list_btn.clicked.connect(self._open_remote_backups_dialog)

        self._backup_btn = QPushButton(_("Backup to WebDAV"))
        self._backup_btn.setIcon(get_icon("save"))
        self._backup_btn.clicked.connect(lambda: self.action_requested.emit("backup"))

        self._restore_btn = QPushButton(_("Restore from WebDAV"))
        self._restore_btn.setIcon(get_icon("download"))
        self._restore_btn.clicked.connect(lambda: self.action_requested.emit("restore"))

        top_action_row = QHBoxLayout()
        top_action_row.setSpacing(8)
        top_action_row.addWidget(self._test_btn)
        top_action_row.addWidget(self._list_btn)
        top_action_row.addStretch()
        layout.addLayout(top_action_row)

        bottom_action_row = QHBoxLayout()
        bottom_action_row.setSpacing(8)
        bottom_action_row.addWidget(self._backup_btn)
        bottom_action_row.addWidget(self._restore_btn)
        bottom_action_row.addStretch()
        layout.addLayout(bottom_action_row)

        self._status_lbl = constrain_label_width(QLabel(""))
        self._status_lbl.setObjectName("muted")
        self._status_lbl.setVisible(False)
        layout.addWidget(self._status_lbl)

        self._hash_info_lbl = constrain_label_width(QLabel(""))
        self._hash_info_lbl.setObjectName("muted")
        self._hash_info_lbl.setVisible(False)
        layout.addWidget(self._hash_info_lbl)

        self._gated_inputs = [
            self._auto_backup_cb,
            self._scheduled_cb,
            self._backup_interval_spin,
            self._backup_favicons_cb,
            self._test_btn,
            self._backup_btn,
            self._restore_btn,
            self._list_btn,
        ]

    def load(self, cfg) -> None:
        self._draft_config = WebDavConfig(
            enabled=cfg.webdav.enabled,
            url=cfg.webdav.url,
            username=cfg.webdav.username,
            remote_path=cfg.webdav.remote_path,
            max_backups=cfg.webdav.max_backups,
            verify_ssl=cfg.webdav.verify_ssl,
            auto_backup=cfg.webdav.auto_backup,
            backup_favicons=cfg.webdav.backup_favicons,
        )
        self._draft_password = ""
        self._password_dirty = False
        self._decrypt_failed = bool(getattr(cfg, "_webdav_password_decryption_failed", False))
        self._has_known_password = bool(
            cfg.webdav.password
            or getattr(cfg, "_webdav_password_cache", "")
            or getattr(cfg, "_webdav_password_ciphertext", "")
        )

        self._enabled_cb.blockSignals(True)
        self._enabled_cb.setChecked(cfg.webdav.enabled)
        self._enabled_cb.blockSignals(False)

        self._auto_backup_cb.setChecked(cfg.webdav.auto_backup)
        self._backup_favicons_cb.setChecked(cfg.webdav.backup_favicons)

        self._scheduled_cb.blockSignals(True)
        self._scheduled_cb.setChecked(cfg.scheduler.auto_backup_enabled)
        self._scheduled_cb.blockSignals(False)
        self._backup_interval_spin.setValue(cfg.scheduler.auto_backup_interval_hours)

        self._refresh_connection_summary()
        self._on_toggle()

    def get_webdav_config(self) -> WebDavConfig:
        return WebDavConfig(
            enabled=self._enabled_cb.isChecked(),
            url=self._draft_config.url.strip(),
            username=self._draft_config.username.strip(),
            password=self._draft_password if self._password_dirty else "",
            remote_path=self._draft_config.remote_path.strip() or WEBDAV_DEFAULT_REMOTE_PATH,
            max_backups=self._draft_config.max_backups,
            verify_ssl=self._draft_config.verify_ssl,
            auto_backup=self._auto_backup_cb.isChecked(),
            backup_favicons=self._backup_favicons_cb.isChecked(),
        )

    def has_pending_password_change(self) -> bool:
        return self._password_dirty and bool(self._draft_password)

    def get_scheduled_backup_enabled(self) -> bool:
        return self._scheduled_cb.isChecked()

    def get_backup_interval_hours(self) -> int:
        return self._backup_interval_spin.value()

    def is_enabled(self) -> bool:
        return self._enabled_cb.isChecked()

    def set_next_backup_text(self, text: str) -> None:
        self._next_backup_lbl.setText(text)
        self._next_backup_icon_lbl.setVisible(bool(text))
        self._next_backup_lbl.setVisible(bool(text))

    def set_status(self, text: str, kind: str = "muted") -> None:
        self._status_lbl.setObjectName(kind)
        self._status_lbl.style().unpolish(self._status_lbl)
        self._status_lbl.style().polish(self._status_lbl)
        self._status_lbl.setText(text)
        self._status_lbl.setVisible(bool(text))

    def set_action_buttons_enabled(self, enabled: bool) -> None:
        can_use = enabled and self._enabled_cb.isChecked()
        self._test_btn.setEnabled(can_use)
        self._backup_btn.setEnabled(can_use)
        self._restore_btn.setEnabled(can_use)
        self._list_btn.setEnabled(can_use)

    def on_action_progress(self, msg: str) -> None:
        self.set_status(msg, "muted")

    def on_action_finished(
        self,
        action: str,
        success: bool,
        msg: str,
        hash_info: dict | None = None,
        backups: list | None = None,
    ) -> None:
        self.set_status(msg, "success" if success else "error")

        if hash_info and success:
            lines = [_("SHA-256 Hashes:")]
            for fname, digest in hash_info.items():
                lines.append(f"  {fname}: {digest[:32]}...")
            self._hash_info_lbl.setText("\n".join(lines))
            self._hash_info_lbl.setVisible(True)
        else:
            self._hash_info_lbl.setVisible(False)

        if action == "list_backups" and self._backups_dialog is not None:
            self._backups_dialog.set_loading(False)
            self._backups_dialog.set_result(success, msg, backups if success else None)

        self._on_toggle()

    def _open_connection_dialog(self) -> None:
        dlg = WebDavConnectionDialog(parent=self)
        dlg.load(
            self._draft_config,
            password_dirty=self._password_dirty,
            decrypt_failed=self._decrypt_failed,
            has_known_password=self._has_known_password,
        )
        if exec_centered(dlg, self) != QDialog.Accepted:
            return

        updated = dlg.get_config()
        self._draft_config.url = updated.url
        self._draft_config.username = updated.username
        self._draft_config.remote_path = updated.remote_path
        self._draft_config.max_backups = updated.max_backups
        self._draft_config.verify_ssl = updated.verify_ssl

        new_password = dlg.get_password()
        if new_password:
            self._draft_password = new_password
            self._password_dirty = True
            self._decrypt_failed = False
            self._has_known_password = True

        self._refresh_connection_summary()

    def _open_remote_backups_dialog(self) -> None:
        if self._backups_dialog is None:
            self._backups_dialog = WebDavRemoteBackupsDialog(parent=self)
            self._backups_dialog.refresh_requested.connect(self._request_remote_backups)
            self._backups_dialog.finished.connect(self._clear_remote_backups_dialog)

        self._backups_dialog.set_loading(True)
        self._request_remote_backups()
        self._backups_dialog.show()
        self._backups_dialog.raise_()
        self._backups_dialog.activateWindow()

    def _request_remote_backups(self) -> None:
        if not self._enabled_cb.isChecked():
            if self._backups_dialog is not None:
                self._backups_dialog.set_loading(False)
                self._backups_dialog.set_result(False, _("Enable WebDAV Backup first."), None)
            return
        self.action_requested.emit("list_backups")

    def _clear_remote_backups_dialog(self) -> None:
        self._backups_dialog = None

    def _refresh_connection_summary(self) -> None:
        self._connection_summary_lbl.setText(self._build_connection_summary())
        if self._password_dirty:
            password_status = _("A new password is staged and will be saved with the next Settings save.")
        elif self._decrypt_failed:
            password_status = _("Saved password needs attention.")
        else:
            password_status = ""

        self._password_status_lbl.setText(password_status)
        self._password_status_lbl.setVisible(bool(password_status))
        self._password_warning_lbl.setVisible(self._decrypt_failed)
        self._discard_password_btn.setVisible(self._password_dirty)

    def _build_connection_summary(self) -> str:
        if not self._draft_config.url.strip():
            return _("Not configured yet.")

        host = self._display_host(self._draft_config.url)
        user = self._draft_config.username.strip() or _("(no username)")
        remote_path = self._draft_config.remote_path.strip() or WEBDAV_DEFAULT_REMOTE_PATH
        return _("{user} @ {host} | {path}").format(user=user, host=host, path=remote_path)

    @staticmethod
    def _display_host(url: str) -> str:
        parsed = urlparse(url.strip())
        return parsed.netloc or parsed.path or url.strip()

    def _discard_pending_password_change(self) -> None:
        self._draft_password = ""
        self._password_dirty = False
        self._refresh_connection_summary()

    def _on_toggle(self) -> None:
        enabled = self._enabled_cb.isChecked()
        for widget in self._gated_inputs:
            widget.setEnabled(enabled)
        self.toggle_changed.emit(enabled)

    @property
    def scheduled_cb(self) -> QCheckBox:
        return self._scheduled_cb

    @property
    def backup_interval_spin(self) -> QSpinBox:
        return self._backup_interval_spin

    @property
    def enabled_cb(self) -> QCheckBox:
        return self._enabled_cb
