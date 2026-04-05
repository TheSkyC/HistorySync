# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import subprocess
import sys
from typing import TYPE_CHECKING
import webbrowser

from PySide6.QtCore import (
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_browser_pixmap, get_icon
from src.views.floating_tooltip import FloatingTooltip

if TYPE_CHECKING:
    from src.models.app_config import AppConfig
    from src.models.history_record import HistoryRecord
    from src.services.local_db import LocalDatabase

log = logging.getLogger(__name__)

_OVERLAY_WIDTH = 520
_MAX_RESULTS = 8
_INCREMENTAL_BATCH = 8  # rows fetched per incremental load
_INCREMENTAL_TRIGGER = 2  # load more when within this many rows of the bottom
_SEARCH_DEBOUNCE_MS = 80
_CORNER_RADIUS = 12


def _get_active_browser_type() -> str | None:
    """Return the browser_type of the current foreground window, or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        import psutil

        # Hardcoded exe → browser_type for the most common browsers
        _EXE_MAP = {
            "chrome.exe": "chrome",
            "msedge.exe": "edge",
            "firefox.exe": "firefox",
            "brave.exe": "brave",
            "opera.exe": "opera",
            "vivaldi.exe": "vivaldi",
            "arc.exe": "arc",
            "chromium.exe": "chromium",
            "waterfox.exe": "waterfox",
            "librewolf.exe": "librewolf",
            "palemoon.exe": "pale_moon",
            "basilisk.exe": "basilisk",
            "seamonkey.exe": "seamonkey",
            "yandex.exe": "yandex",
            "whale.exe": "whale",
            "coccoc.exe": "coccoc",
            "thorium.exe": "thorium",
        }

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None
        name = psutil.Process(pid.value).name().lower()
        return _EXE_MAP.get(name)
    except Exception:
        return None


def _open_url_in_browser(url: str, browser_type: str | None) -> None:
    """Open url in the specified browser, or the system default if None/auto."""
    if not browser_type or browser_type in ("auto", "all"):
        webbrowser.open(url)
        return

    system = sys.platform
    if system == "win32":
        _WIN_CMDS = {
            "chrome": "chrome",
            "edge": "msedge",
            "firefox": "firefox",
            "brave": "brave",
            "opera": "opera",
            "vivaldi": "vivaldi",
            "chromium": "chromium",
        }
        cmd = _WIN_CMDS.get(browser_type)
        if cmd:
            try:
                subprocess.run(["cmd", "/c", "start", "", cmd, url], check=False, capture_output=True)
                return
            except Exception:
                pass
    elif system == "darwin":
        _MAC_NAMES = {
            "chrome": "Google Chrome",
            "edge": "Microsoft Edge",
            "firefox": "Firefox",
            "brave": "Brave Browser",
            "safari": "Safari",
            "opera": "Opera",
            "vivaldi": "Vivaldi",
            "arc": "Arc",
        }
        app = _MAC_NAMES.get(browser_type)
        if app:
            try:
                subprocess.Popen(["open", "-a", app, url])
                return
            except Exception:
                pass
    webbrowser.open(url)


class _SearchInput(QWidget):
    """Search bar row: [browser badge] [text input] [gear button]."""

    text_changed = Signal(str)
    settings_clicked = Signal()
    # Emitted when Ctrl+C is pressed but the input has no selected text,
    # meaning the user intends to copy the currently highlighted result URL.
    copy_url_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._badge = QLabel()
        self._badge.setFixedSize(20, 20)
        self._badge.hide()
        layout.addWidget(self._badge)

        from PySide6.QtWidgets import QLineEdit

        self._input = QLineEdit()
        self._input.setPlaceholderText(_("Search history…"))
        self._input.setFrame(False)
        self._input.setStyleSheet("background: transparent; font-size: 16px;")
        self._input.textChanged.connect(self.text_changed)
        # Intercept Ctrl+C on the line-edit so we can apply the two-tier logic:
        # selected text in the box → normal copy; no selection → copy result URL.
        self._input.installEventFilter(self)
        layout.addWidget(self._input, 1)

        self._gear = QToolButton()
        self._gear.setIcon(get_icon("settings", 16))
        self._gear.setFixedSize(24, 24)
        self._gear.setToolTip("")  # native tooltip cleared; FloatingTooltip used instead
        self._gear.setStyleSheet("QToolButton { border: none; opacity: 0.5; }QToolButton:hover { opacity: 1.0; }")
        self._gear.clicked.connect(self.settings_clicked)
        layout.addWidget(self._gear)

    # ── Event filter ──────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        """Two-tier Ctrl+C on the search input.

        • Input has a text selection  → let QLineEdit copy it normally.
        • Input has no text selection → emit copy_url_requested so the overlay
          copies the URL of the highlighted result instead.
        """
        from PySide6.QtCore import QEvent

        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
                if not self._input.hasSelectedText():
                    self.copy_url_requested.emit()
                    return True  # consumed — do NOT let QLineEdit handle it
        return super().eventFilter(obj, event)

    def set_browser_badge(self, browser_type: str | None) -> None:
        if browser_type:
            px = get_browser_pixmap(browser_type, 20)
            self._badge.setPixmap(px)
            self._badge.show()
        else:
            self._badge.hide()

    def text(self) -> str:
        return self._input.text()

    def clear(self) -> None:
        self._input.clear()

    def set_focus(self) -> None:
        self._input.setFocus()


class _ResultItem(QListWidgetItem):
    def __init__(self, record: HistoryRecord, favicon_cache=None) -> None:
        super().__init__()
        self.record = record
        title = record.title or record.url
        self.setText(title)

        icon = None
        # Try favicon cache first (website icon), fall back to browser icon
        if favicon_cache is not None:
            try:
                from PySide6.QtGui import QIcon, QPixmap

                from src.utils.url_utils import extract_display_domain

                domain = extract_display_domain(record.url)
                if domain:
                    fav = favicon_cache.get(domain)
                    if fav and fav.data:
                        px = QPixmap()
                        px.loadFromData(fav.data)
                        if not px.isNull():
                            icon = QIcon(
                                px.scaled(
                                    16,
                                    16,
                                    Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation,
                                )
                            )
            except Exception:
                pass

        if icon is None:
            from PySide6.QtGui import QIcon

            icon = QIcon(get_browser_pixmap(record.browser_type, 16))

        self.setIcon(icon)
        self.setData(Qt.UserRole, record.url)


class _HintBar(QWidget):
    """Bottom hint strip showing keyboard shortcuts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(20)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)

        def _hint(key: str, desc: str) -> None:
            key_lbl = QLabel(key)
            key_lbl.setStyleSheet(
                "background: rgba(128,128,128,0.2); border-radius: 2px;padding: 0px 3px; font-size: 10px;"
            )
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("font-size: 10px; color: rgba(150,150,150,0.9);")
            layout.addWidget(key_lbl)
            layout.addWidget(desc_lbl)

        _hint("↑↓", _("navigate"))
        _hint("↵", _("open"))
        _hint("Ctrl+C", _("copy"))
        _hint("Esc", _("close"))
        layout.addStretch()


class _SettingsPanel(QWidget):
    """Inline minimal settings panel shown when gear is clicked."""

    back_clicked = Signal()
    advanced_clicked = Signal()
    config_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Header row
        header = QHBoxLayout()
        back_btn = QToolButton()
        back_btn.setIcon(get_icon("search", 16))
        back_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        back_btn.setText(_("Search"))
        back_btn.setStyleSheet(
            "QToolButton { border: none; font-size: 13px; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { background: rgba(128,128,128,0.15); }"
        )
        back_btn.clicked.connect(self.back_clicked)
        header.addWidget(back_btn)
        header.addStretch()
        title = QLabel(_("Settings"))
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        header.addWidget(title)
        layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(128,128,128,0.3);")
        layout.addWidget(sep)

        # Filter browsers
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(_("Filter browsers")))
        row1.addStretch()
        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(160)
        row1.addWidget(self._filter_combo)
        layout.addLayout(row1)

        # Open with
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(_("Open with")))
        row2.addStretch()
        self._open_combo = QComboBox()
        self._open_combo.setMinimumWidth(160)
        row2.addWidget(self._open_combo)
        layout.addLayout(row2)

        layout.addStretch()

        # Advanced link
        adv_btn = QPushButton(_("Advanced Settings"))
        adv_btn.setIcon(get_icon("settings", 14))
        adv_btn.setStyleSheet(
            "QPushButton { border: 1px solid rgba(128,128,128,0.3); border-radius: 5px;"
            " font-size: 12px; padding: 4px 10px; background: transparent; }"
            "QPushButton:hover { background: rgba(128,128,128,0.15); border-color: rgba(128,128,128,0.5); }"
        )
        adv_btn.clicked.connect(self.advanced_clicked)
        layout.addWidget(adv_btn, alignment=Qt.AlignRight)

        self._filter_combo.currentIndexChanged.connect(self.config_changed)
        self._open_combo.currentIndexChanged.connect(self.config_changed)

    def populate(self, browsers: list[tuple[str, str]], active_browser: str | None) -> None:
        """Populate dropdowns with available browsers."""
        self._filter_combo.blockSignals(True)
        self._open_combo.blockSignals(True)

        self._filter_combo.clear()
        self._open_combo.clear()

        self._filter_combo.addItem(_("Auto (Active / All)"), "auto")
        self._filter_combo.addItem(_("All"), "all")
        self._open_combo.addItem(_("Auto"), "auto")

        for bt, display in browsers:
            self._filter_combo.addItem(display, bt)
            self._open_combo.addItem(display, bt)

        self._filter_combo.blockSignals(False)
        self._open_combo.blockSignals(False)

    def load(self, filter_browsers: str, open_with: str) -> None:
        for i in range(self._filter_combo.count()):
            if self._filter_combo.itemData(i) == filter_browsers:
                self._filter_combo.setCurrentIndex(i)
                break
        for i in range(self._open_combo.count()):
            if self._open_combo.itemData(i) == open_with:
                self._open_combo.setCurrentIndex(i)
                break

    def get_filter_browsers(self) -> str:
        return self._filter_combo.currentData() or "auto"

    def get_open_with(self) -> str:
        return self._open_combo.currentData() or "auto"

    def apply_theme(self, is_dark: bool) -> None:
        combo_bg = "#20232c" if is_dark else "#f9fafb"
        combo_border = "#303540" if is_dark else "#d1d5db"
        combo_hover = "#404858" if is_dark else "#9ca3af"
        combo_text = "#c0c8d8" if is_dark else "#1c1c1e"
        popup_sel_bg = "#1e2840" if is_dark else "#dbeafe"
        popup_sel_text = "#7ab4ff" if is_dark else "#1d4ed8"
        combo_style = f"""
            QComboBox {{
                background-color: {combo_bg};
                color: {combo_text};
                border: 1px solid {combo_border};
                border-radius: 6px;
                padding: 5px 24px 5px 10px;
                min-width: 120px;
            }}
            QComboBox:hover {{
                border-color: {combo_hover};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {combo_bg};
                color: {combo_text};
                border: 1px solid {combo_border};
                border-radius: 6px;
                outline: none;
                padding: 3px;
                selection-background-color: {popup_sel_bg};
                selection-color: {popup_sel_text};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 5px 10px;
                border-radius: 4px;
                min-height: 22px;
            }}
        """
        for combo in (self._filter_combo, self._open_combo):
            combo.setStyleSheet(combo_style)


class OverlayWindow(QWidget):
    """Frameless Spotlight-style search overlay."""

    open_settings_requested = Signal()

    def __init__(self, db: LocalDatabase, config: AppConfig, favicon_cache=None, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._db = db
        self._config = config
        self._favicon_cache = favicon_cache
        self._active_browser: str | None = None
        self._drag_pos: QPoint | None = None

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(_OVERLAY_WIDTH)
        self.setStyleSheet("background: transparent;")

        self._build_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._do_search)

        # Incremental search state
        self._search_offset: int = 0  # how many rows already loaded
        self._search_has_more: bool = False  # whether more rows may exist
        self._incremental_loading: bool = False  # guard against re-entrancy
        self._row_height: int = 0  # computed once from first real row

        # Trigger incremental load when the scrollbar reaches the bottom
        self._results.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self._results.installEventFilter(self)

        # Cooldown timer: prevents wheel-triggered loads from firing back-to-back
        # when all results still fit in the viewport (sb.maximum() stays 0).
        self._load_cooldown = QTimer(self)
        self._load_cooldown.setSingleShot(True)
        self._load_cooldown.setInterval(300)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.setSizeConstraint(QVBoxLayout.SetFixedSize)

        # Card container — no extra frame border, background handled by stylesheet
        self._card = QFrame()
        self._card.setObjectName("overlayCard")
        self._card.setFrameShape(QFrame.NoFrame)
        # stylesheet applied dynamically in showEvent to pick up the actual theme color
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Stacked: search view vs settings panel
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        # Page 0 — search view
        search_page = QWidget()
        search_page.setStyleSheet("background: transparent;")
        search_page.setAttribute(Qt.WA_TranslucentBackground)
        sp_layout = QVBoxLayout(search_page)
        sp_layout.setContentsMargins(0, 0, 0, 0)
        sp_layout.setSpacing(0)
        sp_layout.setAlignment(Qt.AlignTop)
        self._search_input = _SearchInput()
        self._search_input.text_changed.connect(self._on_text_changed)
        self._search_input.settings_clicked.connect(self._show_settings_panel)
        self._search_input.copy_url_requested.connect(self._copy_selected)
        self._search_input._gear.installEventFilter(self)
        sp_layout.addWidget(self._search_input)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(128,128,128,0.2);")
        sp_layout.addWidget(sep)

        self._results = QListWidget()
        self._results.setFrameShape(QFrame.NoFrame)
        self._results.setStyleSheet("QListWidget { background: transparent; outline: none; }")
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._results.hide()
        self._results.itemActivated.connect(self._open_selected)
        sp_layout.addWidget(self._results)

        self._hint_bar = _HintBar()
        self._hint_bar.setStyleSheet("background: transparent;")
        sp_layout.addWidget(self._hint_bar)

        self._stack.addWidget(search_page)

        # Page 1 — settings panel
        self._settings_panel = _SettingsPanel()
        self._settings_panel.back_clicked.connect(self._show_search_view)
        self._settings_panel.advanced_clicked.connect(self._on_advanced_settings)
        self._settings_panel.config_changed.connect(self._on_panel_config_changed)
        self._stack.addWidget(self._settings_panel)

        from PySide6.QtWidgets import QSizePolicy

        self._settings_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        card_layout.addWidget(self._stack)
        outer.addWidget(self._card)

    # ── Visibility ────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        try:
            from src.utils.theme_manager import ThemeManager

            is_dark = ThemeManager.instance().current == "dark"
        except Exception:
            is_dark = True
        bg = "#1a1d23" if is_dark else "#f5f5f7"
        border = "rgba(255,255,255,0.08)" if is_dark else "rgba(0,0,0,0.10)"
        sel_bg = "rgba(255,255,255,0.08)" if is_dark else "rgba(0,0,0,0.07)"
        sel_border = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.15)"
        text_color = "#e8eaf0" if is_dark else "#1c1c1e"
        self._card.setStyleSheet(
            f"#overlayCard {{ background: {bg}; border-radius: 12px; border: 1px solid {border}; }}"
        )
        self._results.setStyleSheet(
            f"""
            QListWidget {{
                background: transparent;
                outline: none;
            }}
            QListWidget::item {{
                color: {text_color};
                border-radius: 6px;
                margin: 1px 6px;
                padding: 2px 4px;
            }}
            QListWidget::item:selected {{
                background: {sel_bg};
                border: 1px solid {sel_border};
                color: {text_color};
            }}
            QListWidget::item:hover:!selected {{
                background: {"rgba(255,255,255,0.04)" if is_dark else "rgba(0,0,0,0.04)"};
                border: 1px solid transparent;
            }}
            """
        )

        self._settings_panel.apply_theme(is_dark)

    def showEvent(self, event) -> None:
        self._apply_theme()
        super().showEvent(event)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self._show_overlay()

    def _show_overlay(self) -> None:
        self._active_browser = _get_active_browser_type()
        self._search_input.set_browser_badge(self._active_browser)
        self._search_input.clear()
        self._stack.setCurrentIndex(0)
        self._position_on_screen()
        self.show()

        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.winId())
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        self.activateWindow()
        self.raise_()
        self._search_input.set_focus()
        # Show recent history immediately on open
        self._do_search()

    def _position_on_screen(self) -> None:
        # Use cursor position to determine target screen, correctly supporting multi-monitor scenarios.
        # The old approach screenAt(primaryScreen().geometry().center()) always returns the primary screen.
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        cx = sg.center().x() + self._config.overlay.pos_offset_x
        cy = sg.center().y() + self._config.overlay.pos_offset_y
        self.adjustSize()
        self.move(cx - self.width() // 2, cy - self.height() // 2)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.hide()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._open_selected()
        elif key == Qt.Key_Up:
            self._move_selection(-1)
        elif key == Qt.Key_Down:
            self._move_selection(1)
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            # Hide when focus moves away (but not when settings panel opens a dialog)
            self.hide()
        super().changeEvent(event)

    def hide(self) -> None:
        self._save_config()
        super().hide()

    def closeEvent(self, event) -> None:
        self._save_config()
        super().closeEvent(event)

    def _save_config(self) -> None:
        try:
            self._config.save()
        except Exception:
            log.warning("overlay: failed to save config", exc_info=True)

    # ── Drag to reposition ────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            sg = screen.availableGeometry()
            cx = sg.center().x()
            cy = sg.center().y()
            center = self.geometry().center()
            self._config.overlay.pos_offset_x = center.x() - cx
            self._config.overlay.pos_offset_y = center.y() - cy
            self._drag_pos = None

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        self._debounce.start()

    def _do_search(self, *, append: bool = False) -> None:
        """Run a search query.

        When *append* is False (default) the result list is cleared and offset
        is reset to 0 — this is the normal fresh-search path.
        When *append* is True the next batch is fetched at the current offset
        and appended to the existing list — this is the incremental-load path.
        """
        keyword = self._search_input.text().strip()
        filter_bt = self._config.overlay.filter_browsers
        if filter_bt == "auto":
            filter_bt = self._active_browser  # None means all
        elif filter_bt == "all":
            filter_bt = None

        if not append:
            # Fresh search — reset incremental state
            self._search_offset = 0
            self._search_has_more = False

        offset = self._search_offset
        # Fetch one extra row to detect whether more results exist
        fetch_limit = _INCREMENTAL_BATCH + 1
        try:
            records = self._db.search_quick(
                keyword,
                browser_type=filter_bt,
                limit=fetch_limit,
                offset=offset,
            )
        except TypeError:
            # Fallback: search_quick may not support offset yet
            try:
                records = self._db.search_quick(keyword, browser_type=filter_bt, limit=fetch_limit)
            except Exception as exc:
                log.warning("overlay search_quick failed: %s", exc)
                records = []
        except Exception as exc:
            log.warning("overlay search_quick failed: %s", exc)
            records = []

        # Determine whether a next page exists
        if len(records) > _INCREMENTAL_BATCH:
            self._search_has_more = True
            records = records[:_INCREMENTAL_BATCH]
        else:
            self._search_has_more = False

        if not append:
            self._results.clear()

        prev_row = self._results.currentRow()  # keep selection stable on append
        for r in records:
            self._results.addItem(_ResultItem(r, favicon_cache=self._favicon_cache))

        self._search_offset = offset + len(records)

        total = self._results.count()
        was_visible = self._results.isVisible()
        visible = total > 0

        # Compute row height once from the first real row.
        if visible and self._row_height == 0:
            self._row_height = self._results.sizeHintForRow(0) + 2

        # Always resize the list to fit the actual number of rows (capped at
        # _MAX_RESULTS), so the window shrinks/grows as results change.
        if visible and self._row_height > 0:
            capped = min(total, _MAX_RESULTS)
            self._results.setFixedHeight(self._row_height * capped)
        elif not visible:
            self._results.setFixedHeight(0)

        if visible != was_visible:
            self._results.setVisible(visible)

        old_pos = self.pos()
        self.adjustSize()
        self.move(old_pos)

        if visible:
            if not append:
                self._results.setCurrentRow(0)
            else:
                # Restore selection — don't jump to a newly appended row
                self._results.setCurrentRow(prev_row)

    def _move_selection(self, delta: int) -> None:
        count = self._results.count()
        if count == 0:
            return
        cur = self._results.currentRow()
        # Clamp at the last row — no wrap — so rows_from_bottom stays
        # small and the incremental-load trigger fires correctly.
        new_row = min(cur + delta, count - 1) if delta > 0 else max(cur + delta, 0)
        self._results.setCurrentRow(new_row)
        # Trigger incremental load when within _INCREMENTAL_TRIGGER rows of bottom
        if delta > 0 and self._search_has_more and not self._incremental_loading:
            rows_from_bottom = count - 1 - new_row
            if rows_from_bottom < _INCREMENTAL_TRIGGER:
                self._load_more()

    def _open_selected(self) -> None:
        item = self._results.currentItem()
        if item is None:
            return
        url = item.data(Qt.UserRole)
        open_with = self._config.overlay.open_with
        if open_with == "auto":
            open_with = self._active_browser  # None → system default
        _open_url_in_browser(url, open_with)
        self.hide()

    def _copy_selected(self) -> None:
        item = self._results.currentItem()
        if item is None:
            return
        url = item.data(Qt.UserRole)
        QApplication.clipboard().setText(url)
        self.hide()

    # ── Incremental load ──────────────────────────────────────────────────────

    def _on_scroll_value_changed(self, value: int) -> None:
        """Trigger incremental load when the list is scrolled to the bottom."""
        if not self._search_has_more or self._incremental_loading:
            return
        sb = self._results.verticalScrollBar()
        # Fire when within one page-step of the very bottom.
        # The `maximum() > 0` guard is intentionally absent here: once the
        # list contains more rows than the fixed viewport can display the
        # scrollbar will be active and this check is sufficient.
        if value >= sb.maximum() - sb.pageStep() // 2:
            self._load_more()

    def _load_more(self) -> None:
        """Append the next batch of results to the list."""
        if self._incremental_loading or not self._search_has_more or self._load_cooldown.isActive():
            return
        self._incremental_loading = True
        try:
            self._do_search(append=True)
        finally:
            self._incremental_loading = False
            self._load_cooldown.start()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        # ── Gear button: custom tooltip ───────────────────────────────────────
        if obj is self._search_input._gear:
            if event.type() == QEvent.ToolTip:
                FloatingTooltip.show_at(_("Overlay settings"), event.globalPos())
                return True
            if event.type() == QEvent.Leave:
                FloatingTooltip.cancel_global()
                return False

        # ── Result list: item tooltip + incremental wheel load ────────────────
        if hasattr(self, "_results") and obj is self._results:
            if event.type() == QEvent.ToolTip:
                item = self._results.itemAt(event.pos())
                url = item.data(Qt.UserRole) if item else None
                if url:
                    FloatingTooltip.show_at(url, event.globalPos())
                else:
                    FloatingTooltip.cancel_global()
                return True
            if event.type() == QEvent.Leave:
                FloatingTooltip.cancel_global()
                return False
            if event.type() == QEvent.Wheel:
                if event.angleDelta().y() < 0 and self._search_has_more and not self._incremental_loading:
                    sb = self._results.verticalScrollBar()
                    # Trigger when at the bottom (scrollbar active) or when all
                    # results fit in the viewport (max == 0). The cooldown in
                    # _load_more prevents rapid-fire loads in the latter case.
                    if sb.maximum() == 0 or sb.value() >= sb.maximum():
                        self._load_more()

        return super().eventFilter(obj, event)

    # ── Settings panel ────────────────────────────────────────────────────────

    def _show_settings_panel(self) -> None:
        try:
            browsers = self._db.get_available_browsers()
        except Exception:
            browsers = []
        self._settings_panel.populate(browsers, self._active_browser)
        self._settings_panel.load(
            self._config.overlay.filter_browsers,
            self._config.overlay.open_with,
        )
        from PySide6.QtWidgets import QSizePolicy

        self._settings_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self._stack.setCurrentIndex(1)
        self.adjustSize()  # Recommended: adjust window size to fit settings panel

    def _show_search_view(self) -> None:
        # Ignore settings panel size again when switching back to search view
        from PySide6.QtWidgets import QSizePolicy

        self._settings_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self._stack.setCurrentIndex(0)
        self.adjustSize()
        self._search_input.set_focus()

    def _on_panel_config_changed(self) -> None:
        self._config.overlay.filter_browsers = self._settings_panel.get_filter_browsers()
        self._config.overlay.open_with = self._settings_panel.get_open_with()

    def _on_advanced_settings(self) -> None:
        self.hide()
        self.open_settings_requested.emit()
