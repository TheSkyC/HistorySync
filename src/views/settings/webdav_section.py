# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.views.password_edit import PasswordEdit
from src.views.settings._label_utils import constrain_label_width


class WebDavSection(QWidget):
    """WebDAV cloud-backup card.

    Signals:
        action_requested(action: str)  - "test" | "backup" | "restore" | "list_backups"
        toggle_changed(enabled: bool)  - WebDAV master switch flipped

    Exposes:
        load(cfg)                      - populate all fields
        get_webdav_config() -> WebDavConfig
        get_scheduled_backup_enabled() -> bool
        get_backup_interval_hours() -> int
        set_next_backup_text(text: str)
        set_status(text: str, kind: str)
        on_action_progress(msg: str)
        on_action_finished(action, success, msg, hash_info, backups)
        set_inputs_enabled(enabled: bool)
    """

    action_requested = Signal(str)  # "test" | "backup" | "restore" | "list_backups"
    toggle_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # Master enable
        self._enabled_cb = QCheckBox(_("Enable WebDAV Backup"))
        self._enabled_cb.stateChanged.connect(lambda _: self._on_toggle())
        layout.addWidget(self._enabled_cb)

        # Auto backup after extraction
        self._auto_backup_cb = QCheckBox(_("Automatically backup to WebDAV after local scan"))

        # Scheduled backup row
        auto_backup_row = QHBoxLayout()
        self._scheduled_cb = QCheckBox(_("Scheduled automatic backup every"))
        self._backup_interval_spin = QSpinBox()
        self._backup_interval_spin.setRange(1, 168)
        self._backup_interval_spin.setSuffix(_(" hours"))
        self._backup_interval_spin.setValue(24)
        auto_backup_row.addWidget(self._scheduled_cb)
        auto_backup_row.addWidget(self._backup_interval_spin)
        auto_backup_row.addStretch()
        layout.addLayout(auto_backup_row)

        # Next backup countdown
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

        # Favicon backup
        self._backup_favicons_cb = QCheckBox(_("Include favicon cache in backup"))
        self._backup_favicons_cb.setToolTip(
            _("Backs up the favicon database alongside history. Increases backup size.")
        )
        layout.addWidget(self._backup_favicons_cb)

        # Credentials form
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._url = QLineEdit()
        self._url.setPlaceholderText("https://dav.example.com/dav/")

        self._user = QLineEdit()
        self._user.setPlaceholderText(_("Username:").rstrip(":"))

        self._password = PasswordEdit()

        self._path = QLineEdit()
        self._path.setPlaceholderText(WEBDAV_DEFAULT_REMOTE_PATH)

        self._max_backups_spin = QSpinBox()
        self._max_backups_spin.setRange(1, 100)
        self._max_backups_spin.setSuffix(_(" files"))
        self._max_backups_spin.setMinimumWidth(90)

        self._verify_ssl_cb = QCheckBox(_("Verify SSL certificate"))
        self._ssl_warning_lbl = constrain_label_width(
            QLabel(
                _("\u26a0\ufe0f Warning: Disabling SSL verification exposes your backup to man-in-the-middle attacks.")
            )
        )
        self._ssl_warning_lbl.setStyleSheet("color: #e07b00;")
        self._ssl_warning_lbl.setVisible(False)
        self._verify_ssl_cb.toggled.connect(lambda checked: self._ssl_warning_lbl.setVisible(not checked))

        form.addRow(_("Server URL:"), self._url)
        form.addRow(_("Username:"), self._user)
        form.addRow(_("Password:"), self._password)
        form.addRow(_("Remote Path:"), self._path)
        form.addRow(_("Max backups:"), self._max_backups_spin)
        form.addRow("", self._verify_ssl_cb)
        form.addRow("", self._ssl_warning_lbl)
        form.addRow("", self._auto_backup_cb)
        layout.addLayout(form)

        # List remote backups
        list_row = QHBoxLayout()
        self._list_btn = QPushButton(_("List Remote Backups"))
        self._list_btn.setIcon(get_icon("list"))
        self._list_btn.clicked.connect(lambda: self.action_requested.emit("list_backups"))
        list_row.addWidget(self._list_btn)
        list_row.addStretch()
        layout.addLayout(list_row)

        self._backup_list = QListWidget()
        self._backup_list.setMaximumHeight(100)
        self._backup_list.setVisible(False)
        layout.addWidget(self._backup_list)

        # Action buttons + status
        btn_row = QHBoxLayout()
        self._test_btn = QPushButton(_("Test Connection"))
        self._test_btn.setIcon(get_icon("zap"))
        self._test_btn.clicked.connect(lambda: self.action_requested.emit("test"))

        self._backup_btn = QPushButton(_("Backup to WebDAV"))
        self._backup_btn.setIcon(get_icon("save"))
        self._backup_btn.clicked.connect(lambda: self.action_requested.emit("backup"))

        self._restore_btn = QPushButton(_("Restore from WebDAV"))
        self._restore_btn.setIcon(get_icon("download"))
        self._restore_btn.clicked.connect(lambda: self.action_requested.emit("restore"))

        self._status_lbl = constrain_label_width(QLabel(""))
        self._status_lbl.setObjectName("muted")
        self._status_lbl.setVisible(False)

        btn_row.addWidget(self._test_btn)
        btn_row.addWidget(self._backup_btn)
        btn_row.addWidget(self._restore_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(self._status_lbl)

        # Hash info
        self._hash_info_lbl = constrain_label_width(QLabel(""))
        self._hash_info_lbl.setObjectName("muted")
        self._hash_info_lbl.setVisible(False)
        layout.addWidget(self._hash_info_lbl)

        # Track which widgets are gated by the master toggle
        self._gated_inputs = [
            self._url,
            self._user,
            self._password,
            self._path,
            self._max_backups_spin,
            self._verify_ssl_cb,
            self._auto_backup_cb,
            self._scheduled_cb,
            self._backup_interval_spin,
            self._backup_favicons_cb,
            self._test_btn,
            self._backup_btn,
            self._restore_btn,
            self._list_btn,
        ]

    # ── Public API ────────────────────────────────────────────

    def load(self, cfg):
        self._enabled_cb.blockSignals(True)
        self._enabled_cb.setChecked(cfg.webdav.enabled)
        self._enabled_cb.blockSignals(False)

        self._url.setText(cfg.webdav.url)
        self._user.setText(cfg.webdav.username)
        self._password.setText(cfg.webdav.password)
        self._path.setText(cfg.webdav.remote_path)
        self._max_backups_spin.setValue(cfg.webdav.max_backups)
        self._verify_ssl_cb.setChecked(cfg.webdav.verify_ssl)
        self._auto_backup_cb.setChecked(cfg.webdav.auto_backup)
        self._backup_favicons_cb.setChecked(cfg.webdav.backup_favicons)

        self._scheduled_cb.blockSignals(True)
        self._scheduled_cb.setChecked(cfg.scheduler.auto_backup_enabled)
        self._scheduled_cb.blockSignals(False)

        self._backup_interval_spin.setValue(cfg.scheduler.auto_backup_interval_hours)
        self._on_toggle()

    def get_webdav_config(self) -> WebDavConfig:
        return WebDavConfig(
            enabled=self._enabled_cb.isChecked(),
            url=self._url.text().strip(),
            username=self._user.text().strip(),
            password=self._password.text(),
            remote_path=self._path.text().strip() or WEBDAV_DEFAULT_REMOTE_PATH,
            max_backups=self._max_backups_spin.value(),
            verify_ssl=self._verify_ssl_cb.isChecked(),
            auto_backup=self._auto_backup_cb.isChecked(),
            backup_favicons=self._backup_favicons_cb.isChecked(),
        )

    def get_scheduled_backup_enabled(self) -> bool:
        return self._scheduled_cb.isChecked()

    def get_backup_interval_hours(self) -> int:
        return self._backup_interval_spin.value()

    def is_enabled(self) -> bool:
        return self._enabled_cb.isChecked()

    def set_next_backup_text(self, text: str):
        self._next_backup_lbl.setText(text)
        self._next_backup_icon_lbl.setVisible(bool(text))
        self._next_backup_lbl.setVisible(bool(text))

    def set_status(self, text: str, kind: str = "muted"):
        self._status_lbl.setObjectName(kind)
        self._status_lbl.style().unpolish(self._status_lbl)
        self._status_lbl.style().polish(self._status_lbl)
        self._status_lbl.setText(text)
        self._status_lbl.setVisible(bool(text))

    def set_action_buttons_enabled(self, enabled: bool):
        """Lock/unlock the three action buttons during an in-flight operation."""
        self._test_btn.setEnabled(enabled)
        self._backup_btn.setEnabled(enabled)
        self._restore_btn.setEnabled(enabled)

    def on_action_progress(self, msg: str):
        self.set_status(msg, "muted")

    def on_action_finished(
        self,
        action: str,
        success: bool,
        msg: str,
        hash_info: dict | None = None,
        backups: list | None = None,
    ):
        self.set_status(msg, "success" if success else "error")

        if hash_info and success:
            lines = [_("SHA-256 Hashes:")]
            for fname, digest in hash_info.items():
                lines.append(f"  {fname}: {digest[:32]}...")
            self._hash_info_lbl.setText("\n".join(lines))
            self._hash_info_lbl.setVisible(True)
        else:
            self._hash_info_lbl.setVisible(False)

        if action == "list_backups" and success:
            self._backup_list.clear()
            if backups:
                for b in backups or []:
                    ts = b.get("timestamp", 0)
                    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
                    fmt = b.get("format", "?").upper()
                    self._backup_list.addItem(f"[{fmt}] {b['filename']}  —  {dt_str}")
            else:
                self._backup_list.addItem(_("(no backups found)"))
            self._backup_list.setVisible(True)

        self._on_toggle()

    # ── Internal ──────────────────────────────────────────────

    def _on_toggle(self):
        enabled = self._enabled_cb.isChecked()
        for w in self._gated_inputs:
            w.setEnabled(enabled)
        self.toggle_changed.emit(enabled)

    # ── Properties for signal wiring ──────────────────────────

    @property
    def scheduled_cb(self) -> QCheckBox:
        return self._scheduled_cb

    @property
    def backup_interval_spin(self) -> QSpinBox:
        return self._backup_interval_spin

    @property
    def enabled_cb(self) -> QCheckBox:
        return self._enabled_cb
