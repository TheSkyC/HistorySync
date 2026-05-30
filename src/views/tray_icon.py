# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import math

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from src.utils.constants import APP_NAME
from src.utils.i18n import _
from src.utils.logger import get_logger
from src.utils.styled_menu import StyledMenu

log = get_logger("view.tray")

# ---------------------------------------------------------------------------
# Icon rendering
# ---------------------------------------------------------------------------

# Tray icon logical size. Qt scales to device pixels automatically.
_ICON_SIZE = 32

_S = _ICON_SIZE / 16.0

# Ring geometry (inset so the stroke doesn't clip at the edge)
_RING_MARGIN = 1.5 * _S
_RING_RECT = QRectF(_RING_MARGIN, _RING_MARGIN, _ICON_SIZE - _RING_MARGIN * 2, _ICON_SIZE - _RING_MARGIN * 2)

# Syncing arc: ~226 deg visible, ~134 deg gap (matches dasharray 22:16 ratio)
_ARC_SPAN_DEG = 226

# Ease-in-out spin: one full revolution takes this many ticks (~33 fps).
# _EASE_BLEND controls fast/slow contrast: 0 = uniform, 1 = full sine (stops at slow end).
# 0.55 gives ~3.4x speed ratio (fast:slow) while keeping minimum speed at 45% of average.
_SPIN_PERIOD = 60  # ticks per revolution (~1.8 s)
_EASE_BLEND = 0.55
_TWO_PI = 2.0 * math.pi

# SVG icons (viewBox 0 0 80 80) - dark and light variants.
# Background circle + gradient + H glyph; animated ring is painted on top by QPainter.
_SVG_DARK = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0" stop-color="#3C6880"/>
      <stop offset="0.45" stop-color="#122B3C"/>
      <stop offset="1" stop-color="#050D16"/>
    </linearGradient>
  </defs>
  <circle cx="40" cy="40" r="40" fill="url(#bg)"/>
  <path fill="#FFF" d="M24 20.8h5.1c0.7 0 1.2 0.5 1.2 1.2v14.3h19.4V22c0-0.7 0.5-1.2 1.2-1.2h5.1c0.7 0 1.2 0.5 1.2 1.2v36c0 0.7-0.5 1.2-1.2 1.2h-5.1c-0.7 0-1.2-0.5-1.2-1.2V43.8H30.3V58c0 0.7-0.5 1.2-1.2 1.2H24c-0.7 0-1.2-0.5-1.2-1.2V22c0-0.7 0.5-1.2 1.2-1.2z"/>
</svg>"""

_SVG_LIGHT = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0" stop-color="#F4F7FA"/>
      <stop offset="1" stop-color="#D8E2ED"/>
    </linearGradient>
  </defs>
  <circle cx="40" cy="40" r="40" fill="url(#bg)"/>
  <path fill="#122B3C" d="M24 20.8h5.1c0.7 0 1.2 0.5 1.2 1.2v14.3h19.4V22c0-0.7 0.5-1.2 1.2-1.2h5.1c0.7 0 1.2 0.5 1.2 1.2v36c0 0.7-0.5 1.2-1.2 1.2h-5.1c-0.7 0-1.2-0.5-1.2-1.2V43.8H30.3V58c0 0.7-0.5 1.2-1.2 1.2H24c-0.7 0-1.2-0.5-1.2-1.2V22c0-0.7 0.5-1.2 1.2-1.2z"/>
</svg>"""

_RENDERERS: dict[str, QSvgRenderer] = {}


def _get_renderer(light: bool) -> QSvgRenderer:
    if not _RENDERERS:
        _RENDERERS["dark"] = QSvgRenderer(_SVG_DARK)
        _RENDERERS["light"] = QSvgRenderer(_SVG_LIGHT)
    # Intentional: dark-background icon on light theme, light-background icon on dark theme.
    # This maximises contrast against the OS taskbar/menubar background.
    return _RENDERERS["dark"] if light else _RENDERERS["light"]


def _is_light() -> bool:
    from src.utils.theme_manager import ThemeManager

    return ThemeManager.instance().current == "light"


def _device_pixel_ratio() -> float:
    screen = QApplication.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def _base_pixmap(light: bool) -> QPixmap:
    dpr = _device_pixel_ratio()
    phys = int(_ICON_SIZE * dpr)
    px = QPixmap(phys, phys)
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    _get_renderer(light).render(p, QRectF(0, 0, _ICON_SIZE, _ICON_SIZE))
    p.end()
    return px


def _render_syncing(base: QPixmap, angle_deg: float, light: bool) -> QPixmap:
    accent = QColor("#2563eb") if light else QColor("#3DB8EE")

    # Copy the cached base so we don't mutate it
    px = base.copy()
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(accent)
    pen.setWidthF(1.6 * _S)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Qt drawArc: angles in 1/16-degree units, counter-clockwise from 3 o'clock
    p.drawArc(_RING_RECT, int(angle_deg * 16), int(_ARC_SPAN_DEG * 16))

    p.end()
    return px


# ---------------------------------------------------------------------------
# TrayIcon
# ---------------------------------------------------------------------------


class TrayIcon(QObject):
    open_requested = Signal()
    sync_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setToolTip(APP_NAME)
        self._menu = StyledMenu()
        self._build_menu()
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._main_vm = None

        self._syncing = False
        self._phase = 0  # integer tick counter, drives ease-in-out mapping
        self._light = _is_light()
        self._cached_base: QPixmap | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(30)  # ~33 fps
        self._timer.timeout.connect(self._tick)

        # Listen for theme changes so the icon repaints automatically
        try:
            from src.utils.theme_manager import ThemeManager

            ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        except Exception:
            pass

        self._refresh_icon()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_main_vm(self, vm) -> None:
        self._main_vm = vm

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_syncing(self, syncing: bool):
        self._syncing = syncing
        if syncing:
            self._phase = 0
            self._timer.start()
            self._sync_action.setEnabled(False)
            self._sync_action.setText(_("Syncing..."))
        else:
            self._timer.stop()
            self._sync_action.setEnabled(True)
            self._sync_action.setText(_("Sync Now"))
            self._refresh_icon()

    def set_status(self, msg: str):
        self._status_action.setText(msg)
        self._tray.setToolTip(f"{APP_NAME} — {msg}")

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information,
    ):
        if self._tray.supportsMessages():
            self._tray.showMessage(title, message, icon, 4000)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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

    def _get_base(self) -> QPixmap:
        if self._cached_base is None:
            self._cached_base = _base_pixmap(self._light)
        return self._cached_base

    def _refresh_icon(self):
        self._tray.setIcon(QIcon(self._get_base()))

    def _tick(self):
        self._phase = (self._phase + 1) % _SPIN_PERIOD
        # Offset by 0.25 so the arc starts at the speed peak (fast) and decelerates first.
        # Blend linear + sine: angle = t*360 - BLEND*sin(2π·t)/(2π)*360
        # Instantaneous speed = 1 - BLEND*cos(2π·t): min=(1-BLEND), max=(1+BLEND).
        t = self._phase / _SPIN_PERIOD + 0.25
        angle_deg = (t - _EASE_BLEND * math.sin(_TWO_PI * t) / _TWO_PI) * 360.0
        # Qt arc is counter-clockwise from 3 o'clock; negate for clockwise rotation
        px = _render_syncing(self._get_base(), -angle_deg, self._light)
        self._tray.setIcon(QIcon(px))

    def _on_theme_changed(self, _theme: str):
        self._light = _is_light()
        self._cached_base = None  # invalidate so _get_base() re-renders at correct DPR/theme
        if not self._syncing:
            self._refresh_icon()

    def _on_quit_requested(self) -> None:
        vm = self._main_vm
        sync_busy = vm is not None and vm.is_sync_running()
        backup_busy = vm is not None and vm.is_backup_running()
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
        # macOS and many Linux desktop environments do not reliably fire
        # DoubleClick; use Trigger (single left-click) to open the window.
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.open_requested.emit()
