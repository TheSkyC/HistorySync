# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger

log = get_logger("view.settings.devices")


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return _("Never")
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


class DevicesSection(QWidget):
    """Connected Devices card in Settings.

    Signals:
        rename_requested(device_id, new_name)
        adopt_requested(device_uuid)
        delete_requested(device_id)
    """

    rename_requested = Signal(int, str)  # device_id, new_name
    adopt_requested = Signal(str)  # target_uuid
    delete_requested = Signal(int)  # device_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_device_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ── This device row ───────────────────────────────────
        this_row = QHBoxLayout()
        this_row.setSpacing(8)

        device_icon = QLabel()
        device_icon.setFixedSize(20, 20)
        icon = get_icon("system", 18)
        if not icon.isNull():
            device_icon.setPixmap(icon.pixmap(18, 18))
        this_row.addWidget(device_icon)

        self._this_device_lbl = QLabel(_("This device: —"))
        self._this_device_lbl.setObjectName("stat_label")
        this_row.addWidget(self._this_device_lbl, 1)

        self._rename_this_btn = QPushButton(_("Rename…"))
        self._rename_this_btn.setIcon(get_icon("edit-2", 14))
        self._rename_this_btn.setMinimumHeight(32)
        self._rename_this_btn.clicked.connect(self._on_rename_this)
        this_row.addWidget(self._rename_this_btn)

        layout.addLayout(this_row)

        # ── Device list ───────────────────────────────────────
        list_lbl = QLabel(_("All known devices in this database:"))
        list_lbl.setObjectName("muted")
        layout.addWidget(list_lbl)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMaximumHeight(240)
        self._scroll.setMinimumHeight(60)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll)

        # ── Adopt button ──────────────────────────────────────
        adopt_row = QHBoxLayout()
        adopt_row.setSpacing(8)
        adopt_icon = QLabel()
        adopt_icon.setFixedSize(14, 14)
        info_icon = get_icon("info", 12)
        if not info_icon.isNull():
            adopt_icon.setPixmap(info_icon.pixmap(12, 12))
        layout.addLayout(adopt_row)

    # ── Public API ────────────────────────────────────────────

    def load(self, devices: list[dict], current_device_id: int | None) -> None:
        """Populate the section with device data from the DB.

        *devices* is a list of dicts with keys:
            id, uuid, name, platform, app_version, last_sync_at, created_at
        """
        self._current_device_id = current_device_id
        self._devices = devices

        # Update "this device" label
        current = next((d for d in devices if d["id"] == current_device_id), None)
        if current:
            self._this_device_lbl.setText(
                _("This device: {name}  ({platform})").format(
                    name=current["name"], platform=current.get("platform") or "—"
                )
            )
        else:
            self._this_device_lbl.setText(_("This device: —"))

        # Rebuild device list
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for dev in devices:
            self._list_layout.addWidget(self._make_device_row(dev, current_device_id))

        if not devices:
            empty = QLabel(_("No devices recorded yet."))
            empty.setObjectName("muted")
            self._list_layout.addWidget(empty)

    def _make_device_row(self, dev: dict, current_device_id: int | None) -> QWidget:
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        is_current = dev["id"] == current_device_id

        # Device icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon = get_icon("monitor", 14)
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(14, 14))
        row.addWidget(icon_lbl)

        # Name + platform + last sync
        name_lbl = QLabel(dev["name"] or "—")
        if is_current:
            name_lbl.setStyleSheet("font-weight: 600;")
        name_lbl.setMinimumWidth(120)
        row.addWidget(name_lbl)

        platform_lbl = QLabel(dev.get("platform") or "—")
        platform_lbl.setObjectName("muted")
        platform_lbl.setMinimumWidth(80)
        row.addWidget(platform_lbl)

        sync_lbl = QLabel(_("Last cloud sync: {t}").format(t=_fmt_ts(dev.get("last_sync_at"))))
        sync_lbl.setObjectName("muted")
        sync_lbl.setMinimumWidth(160)
        row.addWidget(sync_lbl)

        row.addStretch()

        # Current badge
        if is_current:
            badge = QLabel(_("(this device)"))
            badge.setObjectName("success")
            row.addWidget(badge)
        else:
            # Adopt button
            adopt_btn = QPushButton(_("Adopt"))
            adopt_btn.setMinimumHeight(30)
            adopt_btn.setIcon(get_icon("log-in", 12))
            adopt_btn.setToolTip(_("Adopt this device identity: your UUID will be changed to match this device."))
            adopt_btn.clicked.connect(lambda _checked, d=dev: self._on_adopt(d))
            row.addWidget(adopt_btn)

            # Rename button
            rename_btn = QPushButton(_("Rename"))
            rename_btn.setMinimumHeight(30)
            rename_btn.setIcon(get_icon("edit-2", 12))
            rename_btn.clicked.connect(lambda _checked, d=dev: self._on_rename(d))
            row.addWidget(rename_btn)

            # Delete button
            del_btn = QPushButton(_("Delete"))
            del_btn.setMinimumHeight(30)
            del_btn.setObjectName("danger_btn")
            del_btn.setIcon(get_icon("trash-2", 12))
            del_btn.setToolTip(_("Remove this device and all its history records from the database."))
            del_btn.clicked.connect(lambda _checked, d=dev: self._on_delete(d))
            row.addWidget(del_btn)

        return row_w

    # ── Action handlers ───────────────────────────────────────

    def _on_rename_this(self) -> None:
        if self._current_device_id is None:
            return
        current = next((d for d in self._devices if d["id"] == self._current_device_id), None)
        current_name = current["name"] if current else ""
        self._prompt_rename(self._current_device_id, current_name)

    def _on_rename(self, dev: dict) -> None:
        self._prompt_rename(dev["id"], dev["name"])

    def _prompt_rename(self, device_id: int, current_name: str) -> None:
        name, ok = QInputDialog.getText(
            self,
            _("Rename Device"),
            _("New device name:"),
            QLineEdit.Normal,
            current_name,
        )
        if ok and name.strip():
            self.rename_requested.emit(device_id, name.strip())

    def _on_adopt(self, dev: dict) -> None:
        reply = QMessageBox.question(
            self,
            _("Adopt Device Identity"),
            _(
                "This will change your current device UUID to match '{name}'.\n\n"
                "Future syncs will use this identity. History records already in the database "
                "will be attributed to this device.\n\nContinue?"
            ).format(name=dev["name"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.adopt_requested.emit(dev["uuid"])

    def _on_delete(self, dev: dict) -> None:
        reply = QMessageBox.warning(
            self,
            _("Delete Device"),
            _(
                "Delete device '{name}'?\n\n"
                "History records attributed to this device will be kept "
                "but will no longer be associated with any device. "
                "This cannot be undone."
            ).format(name=dev["name"]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(dev["id"])
