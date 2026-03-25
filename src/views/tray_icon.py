# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from src.utils.constants import APP_NAME
from src.utils.i18n import _
from src.utils.logger import get_logger

log = get_logger("view.tray")


def _make_tray_icon(syncing: bool = False) -> QIcon:
    from src.utils.icon_helper import _ICONS_DIR

    icon_name = "tray-syncing" if syncing else "tray-idle"
    ico_path = _ICONS_DIR / f"{icon_name}.ico"
    if ico_path.is_file():
        return QIcon(str(ico_path))
    # 降级：绘制字母图标（颜色跟随主题）
    size = 64
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    from src.utils.theme_manager import ThemeManager

    is_light = ThemeManager.instance().current == "light"
    if syncing:
        bg_color = QColor("#2563eb") if is_light else QColor("#3a5aaa")
        ring_color = QColor("#1d55d4") if is_light else QColor("#5b9cf6")
        text_color = QColor("#ffffff") if is_light else QColor("#e0e8ff")
    else:
        bg_color = QColor("#e4e7ed") if is_light else QColor("#252830")
        ring_color = QColor("#b0b6c8") if is_light else QColor("#404858")
        text_color = QColor("#4a5270") if is_light else QColor("#a0b0d0")

    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(bg_color)
    painter.setPen(ring_color)
    painter.drawEllipse(4, 4, size - 8, size - 8)
    font = QFont("Segoe UI", 24, QFont.Bold)
    painter.setFont(font)
    painter.setPen(text_color)
    painter.drawText(px.rect(), 0x0004 | 0x0080, "H")
    painter.end()
    return QIcon(px)


class TrayIcon(QObject):
    open_requested = Signal()
    sync_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip(APP_NAME)
        self._menu = QMenu()
        self._build_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._main_vm = None  # 由外部注入，用于退出时检查同步/备份状态

    def set_main_vm(self, vm) -> None:
        self._main_vm = vm

    def _build_menu(self):
        self._open_action = self._menu.addAction(_("Open Main Window"))
        self._open_action.triggered.connect(self.open_requested)

        self._menu.addSeparator()

        self._sync_action = self._menu.addAction(_("Sync Now"))
        self._sync_action.triggered.connect(self.sync_requested)

        self._menu.addSeparator()

        self._status_action = self._menu.addAction(_("Ready"))
        self._status_action.setEnabled(False)

        self._menu.addSeparator()

        self._quit_action = self._menu.addAction(_("Quit HistorySync"))
        self._quit_action.triggered.connect(self._on_quit_requested)

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_syncing(self, syncing: bool):
        self._tray.setIcon(_make_tray_icon(syncing))
        if syncing:
            self._sync_action.setEnabled(False)
            self._sync_action.setText(_("Syncing..."))
        else:
            self._sync_action.setEnabled(True)
            self._sync_action.setText(_("Sync Now"))

    def set_status(self, msg: str):
        self._status_action.setText(msg)
        self._tray.setToolTip(f"HistorySync — {msg}")

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information,
    ):
        if self._tray.supportsMessages():
            self._tray.showMessage(title, message, icon, 4000)

    def _on_quit_requested(self) -> None:
        vm = self._main_vm
        sync_busy = vm is not None and vm.is_sync_running()
        backup_busy = vm is not None and getattr(getattr(vm, "_scheduler", None), "_backup_running", False)
        if sync_busy or backup_busy:
            op = _("sync and backup") if (sync_busy and backup_busy) else (_("sync") if sync_busy else _("backup"))
            reply = QMessageBox.warning(
                None,
                _("Operation in Progress"),
                _(
                    "A {op} is currently running.\n\n"
                    "Quitting now may result in incomplete data or a corrupted backup.\n\n"
                    "Do you want to quit anyway?"
                ).format(op=op),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
        self.quit_requested.emit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_requested.emit()
