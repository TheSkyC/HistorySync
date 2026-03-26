# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import N_, _
from src.utils.icon_helper import get_browser_pixmap, get_icon
from src.utils.logger import get_logger
from src.utils.theme_manager import ThemeManager

log = get_logger("view.dashboard")


def _make_dot_pixmap(color: str, size: int = 10) -> QPixmap:
    """Create a solid circle QPixmap for status indicators."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return px


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "—", accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card_highlight" if accent else "card")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(20, 16, 20, 16)

        self._label_widget = QLabel(label)
        self._label_widget.setObjectName("stat_label")
        self._value_widget = QLabel(value)
        self._value_widget.setObjectName("stat_value")
        self._value_widget.setWordWrap(False)

        layout.addWidget(self._label_widget)
        layout.addWidget(self._value_widget)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, v: str):
        self._value_widget.setText(v)

    def set_label(self, lbl: str):
        self._label_widget.setText(lbl)


# ── Status badge metadata ──────────────────────────────────────────────────────

_STATUS_META_DARK: dict[str, tuple[str, str, str]] = {
    "UP_TO_DATE": (N_("Up to date"), "#3fb950", "#1a3a28"),
    "NEEDS_SYNC": (N_("Needs sync"), "#d29922", "#3a2e12"),
    "NOT_SYNCED": (N_("Not synced"), "#8b949e", "#252830"),
    "SYNCING": (N_("Syncing..."), "#58a6ff", "#152038"),
    "NOT_FOUND": (N_("Not found"), "#4a5068", "#1e2028"),
}

_STATUS_META_LIGHT: dict[str, tuple[str, str, str]] = {
    "UP_TO_DATE": (N_("Up to date"), "#16a34a", "#dcfce7"),
    "NEEDS_SYNC": (N_("Needs sync"), "#d97706", "#fef9c3"),
    "NOT_SYNCED": (N_("Not synced"), "#6b7280", "#f3f4f6"),
    "SYNCING": (N_("Syncing..."), "#2563eb", "#dbeafe"),
    "NOT_FOUND": (N_("Not found"), "#9ca3af", "#f3f4f6"),
}


def _get_status_meta() -> dict:
    return _STATUS_META_LIGHT if ThemeManager.instance().current == "light" else _STATUS_META_DARK


def _status_label(status_name: str) -> str:
    meta_map = _get_status_meta()
    meta = meta_map.get(status_name, meta_map["NOT_FOUND"])
    return _(meta[0])


def _status_colors(status_name: str) -> tuple[str, str]:
    meta_map = _get_status_meta()
    meta = meta_map.get(status_name, meta_map["NOT_FOUND"])
    return meta[1], meta[2]


# ── Browser card ───────────────────────────────────────────────────────────────


class BrowserCard(QFrame):
    sync_browser_requested = Signal(str)
    open_browser_requested = Signal(str)
    view_history_requested = Signal(str)
    sync_toggle_requested = Signal(str, bool)  # (browser_type, enabled)

    # Windows browser registry paths and common install locations
    _WINDOWS_BROWSERS: dict[str, list[str]] = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ],
        "chromium": [
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
        ],
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        ],
        "brave": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "brave_beta": [
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser-Beta\Application\brave.exe",
        ],
        "brave_dev": [
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser-Dev\Application\brave.exe",
        ],
        "brave_nightly": [
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser-Nightly\Application\brave.exe",
        ],
        "vivaldi": [
            r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
            r"C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe",
            r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",
        ],
        "opera": [
            r"C:\Program Files\Opera\launcher.exe",
            r"C:\Program Files (x86)\Opera\launcher.exe",
            r"%LOCALAPPDATA%\Programs\Opera\launcher.exe",
        ],
        "opera_gx": [
            r"C:\Program Files\Opera GX\launcher.exe",
            r"C:\Program Files (x86)\Opera GX\launcher.exe",
            r"%LOCALAPPDATA%\Programs\Opera GX\launcher.exe",
        ],
        "firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "librewolf": [
            r"C:\Program Files\LibreWolf\librewolf.exe",
            r"C:\Program Files (x86)\LibreWolf\librewolf.exe",
        ],
        "waterfox": [
            r"C:\Program Files\Waterfox\waterfox.exe",
            r"C:\Program Files (x86)\Waterfox\waterfox.exe",
        ],
        "tor_browser": [
            r"C:\Program Files\Tor Browser\Browser\firefox.exe",
            r"%USERPROFILE%\Desktop\Tor Browser\Browser\firefox.exe",
        ],
    }

    _LAUNCH_HINTS: dict[str, list[str]] = {
        "chrome": ["google-chrome", "chrome", "chromium-browser", "chromium"],
        "chromium": ["chromium-browser", "chromium", "google-chrome"],
        "edge": ["microsoft-edge", "msedge"],
        "brave": ["brave-browser", "brave"],
        "brave_beta": ["brave-browser-beta", "brave-beta"],
        "brave_dev": ["brave-browser-dev", "brave-dev"],
        "brave_nightly": ["brave-browser-nightly", "brave-nightly"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "opera": ["opera"],
        "opera_gx": ["opera"],
        "arc": ["arc"],
        "firefox": ["firefox", "firefox-esr"],
        "librewolf": ["librewolf"],
        "waterfox": ["waterfox"],
        "safari": ["open", "-a", "Safari"],
        "tor_browser": ["torbrowser-launcher", "tor-browser"],
    }

    def __init__(self, browser_type: str, display_name: str, parent=None):
        super().__init__(parent)
        self._browser_type = browser_type
        self._display_name = display_name
        self._status_name = "NOT_FOUND"
        self._sync_enabled = True  # 该浏览器是否启用同步

        self.setObjectName("browser_card")
        self.setFixedWidth(168)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        self._build_ui()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme: str):
        self._apply_status()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        # Icon + name row
        top = QHBoxLayout()
        top.setSpacing(10)
        top.setContentsMargins(0, 0, 0, 0)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(28, 28)
        self._icon_label.setAlignment(Qt.AlignCenter)
        px = get_browser_pixmap(self._browser_type, 28)
        if not px.isNull():
            self._icon_label.setPixmap(px)
        else:
            self._icon_label.setText(self._display_name[:1].upper())
            self._icon_label.setObjectName("browser_card_icon_fallback")

        self._name_label = QLabel(self._display_name)
        self._name_label.setObjectName("browser_card_name")
        self._name_label.setWordWrap(False)

        top.addWidget(self._icon_label)
        top.addWidget(self._name_label, 1)
        layout.addLayout(top)

        # Status badge
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(0)

        self._badge = QLabel()
        self._badge.setObjectName("browser_card_badge")
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        badge_row.addWidget(self._badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        self._apply_status()

    def _apply_status(self):
        if not self._sync_enabled:
            # 浏览器同步已禁用，显示灰色覆盖提示
            is_light = ThemeManager.instance().current == "light"
            dot_color = "#9ca3af" if is_light else "#6b7280"
            bg_color = "#f3f4f6" if is_light else "#1e2028"
            self._badge.setText("● " + _("Sync disabled"))
            self._badge.setStyleSheet(
                f"color: {dot_color};"
                f"background-color: {bg_color};"
                f"border-radius: 8px;"
                f"font-size: 11px;"
                f"padding: 2px 8px 2px 6px;"
            )
        else:
            dot_color, bg_color = _status_colors(self._status_name)
            self._badge.setText(f"● {_status_label(self._status_name)}")
            self._badge.setStyleSheet(
                f"color: {dot_color};"
                f"background-color: {bg_color};"
                f"border-radius: 8px;"
                f"font-size: 11px;"
                f"padding: 2px 8px 2px 6px;"
            )

    def update_status(self, status_name: str):
        if self._status_name == status_name:
            return
        self._status_name = status_name
        self._apply_status()

    def _show_context_menu(self, _pos):
        menu = QMenu(self)

        # Non-interactive header showing browser name
        header_action = menu.addAction(self._display_name)
        header_action.setEnabled(False)
        menu.addSeparator()

        sync_action = menu.addAction(get_icon("refresh", 14), _("Sync This Browser"))
        sync_action.triggered.connect(lambda: self.sync_browser_requested.emit(self._browser_type))
        sync_action.setEnabled(self._sync_enabled)

        view_history_action = menu.addAction(get_icon("list", 14), _("View History"))
        view_history_action.triggered.connect(lambda: self.view_history_requested.emit(self._browser_type))

        menu.addSeparator()

        # 启用/禁用该浏览器的同步
        if self._sync_enabled:
            toggle_action = menu.addAction(get_icon("pause", 14), _("Disable Sync for This Browser"))
            toggle_action.triggered.connect(lambda: self._on_toggle_sync(False))
        else:
            toggle_action = menu.addAction(get_icon("play", 14), _("Enable Sync for This Browser"))
            toggle_action.triggered.connect(lambda: self._on_toggle_sync(True))

        menu.addSeparator()

        open_action = menu.addAction(get_icon("globe", 14), _("Open Browser"))
        open_action.triggered.connect(lambda: self.open_browser_requested.emit(self._browser_type))

        copy_action = menu.addAction(get_icon("copy", 14), _("Copy Browser Name"))
        copy_action.triggered.connect(self._copy_name)

        menu.exec(QCursor.pos())

    def _on_toggle_sync(self, enabled: bool):
        self._sync_enabled = enabled
        self._apply_status()
        self.sync_toggle_requested.emit(self._browser_type, enabled)

    def set_sync_enabled(self, enabled: bool):
        """由外部调用以同步浏览器启用状态。"""
        self._sync_enabled = enabled
        self._apply_status()

    def _copy_name(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._display_name)

    @property
    def browser_type(self) -> str:
        return self._browser_type


# ── Empty state ────────────────────────────────────────────────────────────────


class _EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 8)
        layout.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent;")
        px = get_icon("search", 28).pixmap(28, 28)
        if not px.isNull():
            icon_lbl.setPixmap(px)

        text_lbl = QLabel(_("No browsers detected"))
        text_lbl.setObjectName("muted")
        text_lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon_lbl, 0, Qt.AlignCenter)
        layout.addSpacing(6)
        layout.addWidget(text_lbl)


# ── Browser settings dialog ────────────────────────────────────────────────────


class BrowserSettingsDialog(QDialog):
    """浏览器同步设置对话框：启用/禁用各浏览器，支持重新检测。"""

    browser_sync_changed = Signal(str, bool)   # (browser_type, enabled)
    redetect_requested = Signal()

    def __init__(self, disabled_browsers: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Browser Sync Settings"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(360)
        self.setMinimumHeight(300)
        self.resize(420, 520)
        self._disabled_browsers = set(disabled_browsers)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._dots: dict[str, QLabel] = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel(_("Browser Sync Selection"))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        root.addLayout(title_row)

        desc = QLabel(_("Enable or disable history sync for each browser.\nDisabled browsers will not be scanned during sync."))
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #888;")
        root.addWidget(desc)

        # Select-all / none buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_all = QPushButton(_("Select All"))
        btn_all.setFixedHeight(30)
        btn_none = QPushButton(_("Deselect All"))
        btn_none.setFixedHeight(30)
        btn_all.clicked.connect(self._on_select_all)
        btn_none.clicked.connect(self._on_deselect_all)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Scroll area with browser checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(280)

        inner = QWidget()
        cb_layout = QVBoxLayout(inner)
        cb_layout.setSpacing(6)
        cb_layout.setContentsMargins(4, 4, 4, 4)

        from src.services.browser_defs import BUILTIN_BROWSERS

        # Pre-detect which browsers have history available
        detected = {bdef.browser_type for bdef in BUILTIN_BROWSERS if bdef.is_history_available()}

        # Sort: detected first, then undetected
        sorted_browsers = sorted(
            BUILTIN_BROWSERS, key=lambda b: (0 if b.browser_type in detected else 1, b.display_name)
        )

        for bdef in sorted_browsers:
            is_detected = bdef.browser_type in detected
            row = QHBoxLayout()
            row.setSpacing(8)
            # Browser icon
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(20, 20)
            icon_lbl.setAlignment(Qt.AlignCenter)
            px = get_browser_pixmap(bdef.browser_type, 20)
            if not px.isNull():
                icon_lbl.setPixmap(px)
            else:
                icon_lbl.setText(bdef.display_name[:1].upper())

            cb = QCheckBox(bdef.display_name)
            cb.setChecked(bdef.browser_type not in self._disabled_browsers)
            cb.setStyleSheet("font-size: 13px;")
            self._checkboxes[bdef.browser_type] = cb

            # Status dot: green=detected+enabled, yellow=detected+disabled, red=not detected
            dot = QLabel()
            dot.setFixedSize(10, 10)
            if is_detected:
                if bdef.browser_type not in self._disabled_browsers:
                    dot.setPixmap(_make_dot_pixmap("#34a853", 10))
                    dot.setToolTip(_("Detected — sync enabled"))
                else:
                    dot.setPixmap(_make_dot_pixmap("#d29922", 10))
                    dot.setToolTip(_("Detected — sync disabled"))
            else:
                dot.setPixmap(_make_dot_pixmap("#e05252", 10))
                dot.setToolTip(_("Not detected"))
            self._dots[bdef.browser_type] = dot

            # Update dot when checkbox changes
            bt = bdef.browser_type
            cb.toggled.connect(lambda checked, b=bt: self._on_cb_toggled(b, checked))

            row.addWidget(icon_lbl)
            row.addWidget(cb, 1)
            row.addWidget(dot)
            cb_layout.addLayout(row)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # Re-detect button
        redetect_btn = QPushButton(_("Re-detect Browsers Now"))
        redetect_btn.setIcon(get_icon("search", 16))
        redetect_btn.setFixedHeight(32)
        redetect_btn.clicked.connect(self._on_redetect)
        root.addWidget(redetect_btn)

        # OK / Cancel
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_cb_toggled(self, browser_type: str, checked: bool) -> None:
        """Update the status dot when a checkbox is toggled."""
        dot = self._dots.get(browser_type)
        if dot is None:
            return
        # We need to know if it was detected; re-check from what we stored
        from src.services.browser_defs import BUILTIN_BROWSERS
        bdef = next((b for b in BUILTIN_BROWSERS if b.browser_type == browser_type), None)
        is_detected = bdef.is_history_available() if bdef else False
        if is_detected:
            if checked:
                dot.setPixmap(_make_dot_pixmap("#34a853", 10))
                dot.setToolTip(_("Detected — sync enabled"))
            else:
                dot.setPixmap(_make_dot_pixmap("#d29922", 10))
                dot.setToolTip(_("Detected — sync disabled"))
        else:
            dot.setPixmap(_make_dot_pixmap("#e05252", 10))
            dot.setToolTip(_("Not detected"))

    def _on_select_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _on_deselect_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(False)

    def _on_redetect(self):
        self.redetect_requested.emit()

    def _on_accept(self):
        # Emit changes for each browser whose state differs from original
        for bt, cb in self._checkboxes.items():
            enabled = cb.isChecked()
            was_disabled = bt in self._disabled_browsers
            if enabled == was_disabled:   # state changed
                self.browser_sync_changed.emit(bt, enabled)
        self.accept()

    def get_disabled_browsers(self) -> list[str]:
        return [bt for bt, cb in self._checkboxes.items() if not cb.isChecked()]


# ── Dashboard page ─────────────────────────────────────────────────────────────


class DashboardPage(QWidget):
    sync_requested = Signal()
    sync_browser_requested = Signal(str)
    view_history_requested = Signal(str)
    browser_sync_toggle_requested = Signal(str, bool)  # (browser_type, enabled)
    redetect_browsers_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(40)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_value = 0
        self._browser_cards: dict[str, BrowserCard] = {}
        self._disabled_browsers: set[str] = set()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(24)

        # Header
        header = QWidget()
        header.setObjectName("page_header")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.setSpacing(2)
        self._title_lbl = QLabel(_("Overview"))
        self._title_lbl.setObjectName("page_title")
        self._subtitle_lbl = QLabel(_("Browser History Sync Center"))
        self._subtitle_lbl.setObjectName("page_subtitle")
        left.addWidget(self._title_lbl)
        left.addWidget(self._subtitle_lbl)

        self._sync_btn = QPushButton(_("Sync Now"))
        self._sync_btn.setObjectName("primary_btn")
        self._sync_btn.setMinimumWidth(120)
        self._sync_btn.setFixedHeight(36)
        self._sync_btn.setIcon(get_icon("refresh"))
        self._sync_btn.clicked.connect(self.sync_requested)

        h_layout.addLayout(left)
        h_layout.addStretch()
        h_layout.addWidget(self._sync_btn)
        root.addWidget(header)

        # Stat cards
        cards_grid = QGridLayout()
        cards_grid.setSpacing(12)

        self._card_total = StatCard(_("Total Local Records"), "0", accent=True)
        self._card_browsers = StatCard(_("Browsers Detected"), "0")
        self._card_sync = StatCard(_("Last Sync"), _("Never"))
        self._card_webdav = StatCard(_("WebDAV Status"), _("Not enabled"))

        cards_grid.addWidget(self._card_total, 0, 0)
        cards_grid.addWidget(self._card_browsers, 0, 1)
        cards_grid.addWidget(self._card_sync, 0, 2)
        cards_grid.addWidget(self._card_webdav, 0, 3)
        root.addLayout(cards_grid)

        # Progress area
        self._progress_frame = QFrame()
        self._progress_frame.setObjectName("card")
        self._progress_frame.setVisible(False)
        p_layout = QVBoxLayout(self._progress_frame)
        p_layout.setContentsMargins(20, 14, 20, 14)
        p_layout.setSpacing(8)
        self._progress_label = QLabel(_("Preparing..."))
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        p_layout.addWidget(self._progress_label)
        p_layout.addWidget(self._progress_bar)
        root.addWidget(self._progress_frame)

        # Browser cards section
        detail_frame = QFrame()
        detail_frame.setObjectName("card")
        d_layout = QVBoxLayout(detail_frame)
        d_layout.setContentsMargins(20, 16, 20, 16)
        d_layout.setSpacing(0)

        # Section header row with settings button
        section_header_row = QHBoxLayout()
        section_header_row.setContentsMargins(0, 0, 0, 0)
        section_header = QLabel(_("Browser Detection Status"))
        section_header.setObjectName("stat_label")
        section_header_row.addWidget(section_header)
        section_header_row.addStretch()

        self._browser_settings_btn = QPushButton()
        self._browser_settings_btn.setIcon(get_icon("settings", 16))
        self._browser_settings_btn.setFixedSize(28, 28)
        self._browser_settings_btn.setToolTip(_("Browser Sync Settings & Re-detect"))
        self._browser_settings_btn.setObjectName("icon_btn")
        self._browser_settings_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 6px; background: transparent; }"
            "QPushButton:hover { background: rgba(128,128,128,0.15); }"
            "QPushButton:pressed { background: rgba(128,128,128,0.25); }"
        )
        self._browser_settings_btn.clicked.connect(self._on_browser_settings)
        section_header_row.addWidget(self._browser_settings_btn)

        d_layout.addLayout(section_header_row)
        d_layout.addSpacing(14)

        self._cards_container = QWidget()
        self._cards_container.setObjectName("cards_container")
        self._cards_grid = QGridLayout(self._cards_container)
        self._cards_grid.setSpacing(10)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._empty_state = _EmptyState()
        self._empty_state.setVisible(False)

        d_layout.addWidget(self._cards_container)
        d_layout.addWidget(self._empty_state)

        root.addWidget(detail_frame)
        root.addStretch()

    # ── Public update API ──────────────────────────────────────

    def update_stats(self, total_count: int, last_sync_time: int | None, webdav_status: str):
        self._card_total.set_value(f"{total_count:,}")
        self._card_sync.set_value(_fmt_time(last_sync_time))
        self._card_webdav.set_value(webdav_status)

    def update_browser_statuses(self, statuses: dict, display_names: dict, disabled_browsers: list | None = None):
        if disabled_browsers is not None:
            self._disabled_browsers = set(disabled_browsers)

        detected = {bt: s for bt, s in statuses.items() if s != "NOT_FOUND"}
        self._card_browsers.set_value(str(len(detected)))

        # Remove cards for browsers no longer detected
        to_remove = [bt for bt in self._browser_cards if bt not in detected]
        for bt in to_remove:
            card = self._browser_cards.pop(bt)
            self._cards_grid.removeWidget(card)
            card.deleteLater()

        # Add or update
        for bt, status_name in detected.items():
            if bt not in self._browser_cards:
                display_name = display_names.get(bt, bt.title())
                card = BrowserCard(bt, display_name, self._cards_container)
                card.sync_browser_requested.connect(self._on_sync_browser)
                card.open_browser_requested.connect(self._on_open_browser)
                card.view_history_requested.connect(self._on_view_history)
                card.sync_toggle_requested.connect(self.browser_sync_toggle_requested)
                self._browser_cards[bt] = card
            card = self._browser_cards[bt]
            card.set_sync_enabled(bt not in self._disabled_browsers)
            card.update_status(status_name)

        self._relayout_cards()

        has_detected = len(detected) > 0
        self._empty_state.setVisible(not has_detected)
        self._cards_container.setVisible(has_detected)

    def _relayout_cards(self):
        while self._cards_grid.count():
            item = self._cards_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(self._cards_container)

        cols = 4
        for i, card in enumerate(self._browser_cards.values()):
            row, col = divmod(i, cols)
            self._cards_grid.addWidget(card, row, col)

    # ── Per-browser actions ────────────────────────────────────

    def _on_browser_settings(self):
        """打开浏览器同步设置对话框。"""
        dlg = BrowserSettingsDialog(self._disabled_browsers, parent=self)
        dlg.browser_sync_changed.connect(self._on_browser_sync_changed_from_dialog)
        dlg.redetect_requested.connect(self.redetect_browsers_requested)
        if dlg.exec() == QDialog.Accepted:
            # 批量应用所有更改
            new_disabled = set(dlg.get_disabled_browsers())
            # 对每个状态发生变化的浏览器发出信号
            all_browsers = set(self._browser_cards.keys()) | new_disabled | self._disabled_browsers
            for bt in all_browsers:
                was_disabled = bt in self._disabled_browsers
                is_disabled = bt in new_disabled
                if was_disabled != is_disabled:
                    self.browser_sync_toggle_requested.emit(bt, not is_disabled)
                    if bt in self._browser_cards:
                        self._browser_cards[bt].set_sync_enabled(not is_disabled)
            self._disabled_browsers = new_disabled

    def _on_browser_sync_changed_from_dialog(self, browser_type: str, enabled: bool):
        """对话框内实时点击重新检测时的回调（不等 OK）。"""
        pass  # 仅在 OK 时批量提交，此处留空

    def _on_sync_browser(self, browser_type: str):
        self.sync_browser_requested.emit(browser_type)

    def _on_view_history(self, browser_type: str):
        self.view_history_requested.emit(browser_type)

    def _on_open_browser(self, browser_type: str):
        """Launch the specified browser with improved Windows support"""
        import platform

        system = platform.system().lower()

        # Windows platform: Use multiple strategies for robustness
        if system == "windows":
            # Try method 1: Direct paths from known install locations
            if browser_type in BrowserCard._WINDOWS_BROWSERS:
                for path in BrowserCard._WINDOWS_BROWSERS[browser_type]:
                    expanded_path = os.path.expandvars(path)
                    if Path(expanded_path).exists():
                        try:
                            os.startfile(expanded_path)
                            log.info("Launched %s using direct path: %s", browser_type, expanded_path)
                            return
                        except Exception as e:
                            log.debug("Failed to launch with path %s: %s", expanded_path, e)

            # Try method 2: Windows Registry lookup via webbrowser module
            browser_names_map = {
                "chrome": "chrome",
                "chromium": "chromium",
                "edge": "microsoft-edge",
                "firefox": "firefox",
                "opera": "opera",
                "brave": "brave",
                "brave_beta": "brave-beta",
                "brave_dev": "brave-dev",
                "brave_nightly": "brave-nightly",
                "vivaldi": "vivaldi",
            }

            if browser_type in browser_names_map:
                try:
                    # Try to get specific browser controller
                    browser_name = browser_names_map[browser_type]
                    controller = webbrowser.get(browser_name)
                    controller.open("about:blank")
                    log.info("Launched %s using webbrowser module", browser_type)
                    return
                except Exception as e:
                    log.debug("Failed with webbrowser.get(%s): %s", browser_type, e)

            # Try method 3: Use start command with common executable names
            win_commands = {
                "chrome": ["chrome", "Chrome"],
                "edge": ["msedge", "MicrosoftEdge", "edge"],
                "firefox": ["firefox", "Firefox"],
                "brave": ["brave", "Brave"],
                "brave_beta": ["brave-beta", "brave"],
                "brave_dev": ["brave-dev", "brave"],
                "brave_nightly": ["brave-nightly", "brave"],
                "opera": ["opera", "Opera"],
                "vivaldi": ["vivaldi", "Vivaldi"],
                "chromium": ["chromium", "chrome"],
            }

            commands = win_commands.get(browser_type, [browser_type])
            for cmd in commands:
                try:
                    # Try with start command (uses Windows PATH and App Paths registry)
                    subprocess.run(["cmd", "/c", "start", "", cmd], check=False, capture_output=True)
                    log.info("Launched %s using start command with: %s", browser_type, cmd)
                    return
                except Exception as e:
                    log.debug("Failed with start command %s: %s", cmd, e)

        # macOS platform logic
        elif system == "darwin":
            name_map = {
                "chrome": "Google Chrome",
                "chromium": "Chromium",
                "edge": "Microsoft Edge",
                "brave": "Brave Browser",
                "brave_beta": "Brave Browser Beta",
                "brave_dev": "Brave Browser Dev",
                "brave_nightly": "Brave Browser Nightly",
                "vivaldi": "Vivaldi",
                "opera": "Opera",
                "opera_gx": "Opera GX",
                "arc": "Arc",
                "firefox": "Firefox",
                "librewolf": "LibreWolf",
                "waterfox": "Waterfox",
                "safari": "Safari",
                "tor_browser": "Tor Browser",
            }
            app_name = name_map.get(browser_type)
            if app_name:
                try:
                    subprocess.Popen(["open", "-a", app_name])
                    log.info("Launched %s via macOS 'open -a'", browser_type)
                    return
                except Exception as e:
                    log.warning("Failed to launch %s with 'open -a': %s", browser_type, e)

        # Linux platform logic
        else:
            hints = BrowserCard._LAUNCH_HINTS.get(browser_type, [browser_type])
            for cmd in hints:
                try:
                    subprocess.Popen([cmd])
                    log.info("Launched %s with command: %s", browser_type, cmd)
                    return
                except FileNotFoundError:
                    continue
                except Exception as e:
                    log.warning("Failed to launch %s with %s: %s", browser_type, cmd, e)
                    break

        # Global failure handler
        display_name = (
            self._browser_cards[browser_type]._display_name
            if browser_type in self._browser_cards
            else browser_type.title()
        )
        msg = _("Could not launch {browser}. Please make sure it is installed.").format(browser=display_name)
        log.error(msg)

    # ── Sync progress UI ──────────────────────────────────────

    def on_sync_started(self):
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText(_("Syncing..."))
        self._progress_frame.setVisible(True)
        self._progress_value = 0
        self._progress_bar.setValue(0)
        self._progress_timer.start()

    def on_sync_progress(self, msg: str):
        self._progress_label.setText(msg)
        self._progress_value = min(self._progress_value + 8, 90)
        self._progress_bar.setValue(self._progress_value)

    def on_sync_finished(self, new_count: int):
        self._progress_timer.stop()
        self._progress_bar.setValue(100)
        self._progress_label.setText(_("Sync complete, {count} new records added").format(count=new_count))
        self._sync_btn.setEnabled(True)
        self._sync_btn.setText(_("Sync Now"))
        QTimer.singleShot(3000, lambda: self._progress_frame.setVisible(False))

    def on_sync_error(self, msg: str):
        self._progress_timer.stop()
        self._progress_label.setText(_("Sync failed: {msg}").format(msg=msg))
        self._sync_btn.setEnabled(True)
        self._sync_btn.setText(_("Sync Now"))

    def _tick_progress(self):
        v = self._progress_bar.value()
        if v < self._progress_value:
            self._progress_bar.setValue(v + 2)


def _fmt_time(ts: int | None) -> str:
    if not ts:
        return _("Never")
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return "—"
