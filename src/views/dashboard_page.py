# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import N_, _
from src.utils.icon_helper import get_browser_pixmap, get_icon
from src.utils.logger import get_logger
from src.utils.theme_manager import ThemeManager

log = get_logger("view.dashboard")


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

    _LAUNCH_HINTS: dict[str, list[str]] = {
        "chrome": ["google-chrome", "chrome", "chromium-browser", "chromium"],
        "chromium": ["chromium-browser", "chromium", "google-chrome"],
        "edge": ["microsoft-edge", "msedge"],
        "brave": ["brave-browser", "brave"],
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

        view_history_action = menu.addAction(get_icon("list", 14), _("View History"))
        view_history_action.triggered.connect(lambda: self.view_history_requested.emit(self._browser_type))

        menu.addSeparator()

        open_action = menu.addAction(get_icon("globe", 14), _("Open Browser"))
        open_action.triggered.connect(lambda: self.open_browser_requested.emit(self._browser_type))

        copy_action = menu.addAction(get_icon("copy", 14), _("Copy Browser Name"))
        copy_action.triggered.connect(self._copy_name)

        menu.exec(QCursor.pos())

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

        icon_lbl = QLabel("🔍")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")

        text_lbl = QLabel(_("No browsers detected"))
        text_lbl.setObjectName("muted")
        text_lbl.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon_lbl)
        layout.addSpacing(6)
        layout.addWidget(text_lbl)


# ── Dashboard page ─────────────────────────────────────────────────────────────


class DashboardPage(QWidget):
    sync_requested = Signal()
    sync_browser_requested = Signal(str)
    view_history_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(40)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_value = 0
        self._browser_cards: dict[str, BrowserCard] = {}

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

        section_header = QLabel(_("Browser Detection Status"))
        section_header.setObjectName("stat_label")
        d_layout.addWidget(section_header)
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

    def update_browser_statuses(self, statuses: dict, display_names: dict):
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
                self._browser_cards[bt] = card
            self._browser_cards[bt].update_status(status_name)

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

    def _on_sync_browser(self, browser_type: str):
        self.sync_browser_requested.emit(browser_type)

    def _on_view_history(self, browser_type: str):
        self.view_history_requested.emit(browser_type)

    def _on_open_browser(self, browser_type: str):
        hints = BrowserCard._LAUNCH_HINTS.get(browser_type, [browser_type])
        if sys.platform == "darwin":
            name_map = {
                "chrome": "Google Chrome",
                "chromium": "Chromium",
                "edge": "Microsoft Edge",
                "brave": "Brave Browser",
                "firefox": "Firefox",
                "safari": "Safari",
                "arc": "Arc",
            }
            app_name = name_map.get(browser_type)
            if app_name:
                try:
                    subprocess.Popen(["open", "-a", app_name])
                    return
                except Exception:
                    pass
        for cmd in hints:
            try:
                subprocess.Popen([cmd])
                return
            except FileNotFoundError:
                continue
            except Exception as e:
                log.warning("Failed to launch %s: %s", cmd, e)
                return
        log.warning("Could not find executable for browser: %s", browser_type)

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
