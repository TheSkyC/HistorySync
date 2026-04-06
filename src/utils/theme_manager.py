# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import re
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from src.utils.logger import get_logger

log = get_logger("utils.theme_manager")

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_SYSTEM = "system"

_VALID_THEMES = {THEME_DARK, THEME_LIGHT, THEME_SYSTEM}

_BASE = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent.parent
_RES_DIR = _BASE / "resources"


def _detect_system_theme() -> str:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return THEME_DARK
        if scheme == Qt.ColorScheme.Light:
            return THEME_LIGHT
    except Exception:
        pass
    return THEME_DARK


def _load_qss(theme: str) -> str:
    qss_path = _RES_DIR / "styles" / f"{theme}.qss"
    if not qss_path.is_file():
        log.warning("QSS file not found for theme '%s': %s", theme, qss_path)
        return ""
    res_dir_fwd = str(_RES_DIR).replace("\\", "/")
    with qss_path.open(encoding="utf-8") as f:
        return f.read().replace("@RES@", res_dir_fwd)


def _recolor_svg_bytes(svg_path: str, color: str) -> bytes:
    try:
        with Path(svg_path).open(encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{color}"', content)
        content = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{color}"', content)
        return content.encode("utf-8")
    except Exception as exc:
        log.warning("Failed to recolor SVG %s: %s", svg_path, exc)
        return b""


class ThemeManager(QObject):
    """Global theme manager."""

    # Emits resolved "dark" | "light"
    theme_changed = Signal(str)

    _instance: ThemeManager | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current: str = THEME_DARK
        self._raw: str = THEME_DARK
        self._pending: str | None = None
        self._pending_app: QApplication | None = None
        self._applied: str | None = None
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(0)
        self._apply_timer.timeout.connect(self._on_timer_fire)

    @classmethod
    def instance(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────

    @property
    def current(self) -> str:
        """Currently applied theme: 'dark' or 'light'."""
        return self._current

    @property
    def raw(self) -> str:
        """Original value set by the user: 'dark' | 'light' | 'system'."""
        return self._raw

    def apply(self, app: QApplication, theme: str) -> None:
        """
        Applies the theme asynchronously: defers setStyleSheet until the event loop is idle.
        """
        if theme not in _VALID_THEMES:
            log.warning("Unknown theme '%s', falling back to dark", theme)
            theme = THEME_DARK

        resolved = _detect_system_theme() if theme == THEME_SYSTEM else theme

        # Update state immediately
        self._raw = theme
        self._current = resolved
        self._pending = resolved
        self._pending_app = app

        self._apply_timer.stop()
        self._apply_timer.start()

    def _on_timer_fire(self) -> None:
        if self._pending is not None and self._pending_app is not None:
            self._do_apply(self._pending_app, self._pending)

    def apply_sync(self, app: QApplication, theme: str) -> None:
        """Applies the theme synchronously immediately — for use during application startup only."""
        if theme not in _VALID_THEMES:
            theme = THEME_DARK
        resolved = _detect_system_theme() if theme == THEME_SYSTEM else theme
        self._raw = theme
        self._current = resolved
        self._pending = resolved
        self._pending_app = app
        self._apply_timer.stop()
        self._do_apply(app, resolved)

    def _do_apply(self, app: QApplication, resolved: str) -> None:
        if self._pending != resolved:
            log.debug("Theme apply skipped (superseded): %s", resolved)
            return

        if resolved == self._applied:
            log.debug("Theme apply skipped (no change): %s", resolved)
            self._pending = None
            self.theme_changed.emit(resolved)
            return

        try:
            from src.utils.icon_helper import _load_svg_icon

            _load_svg_icon.cache_clear()
            log.debug("Icon LRU cache cleared for theme '%s'", resolved)
        except Exception as exc:
            log.warning("Failed to clear icon cache: %s", exc)

        qss = _load_qss(resolved)
        if qss:
            from PySide6.QtWidgets import (
                QHeaderView,
                QListView,
                QListWidget,
                QTableView,
                QTableWidget,
                QTreeView,
                QTreeWidget,
            )

            _SAFE_VIEW_TYPES = (QTableView, QTreeView, QListView)
            _EXCLUDED_TYPES = (QListWidget, QTableWidget, QTreeWidget)
            heavy_widgets = [
                w
                for w in app.allWidgets()
                if isinstance(w, _SAFE_VIEW_TYPES) and not isinstance(w, _EXCLUDED_TYPES) and w.model() is not None
            ]

            saved_state: list[tuple] = []
            for w in heavy_widgets:
                hh = w.horizontalHeader() if hasattr(w, "horizontalHeader") else None
                if hh is not None and hh.count() > 0:
                    col_info = [(hh.sectionSize(i), hh.sectionResizeMode(i)) for i in range(hh.count())]
                else:
                    col_info = []
                vbar = w.verticalScrollBar()
                hbar = w.horizontalScrollBar()
                scroll_v = vbar.value() if vbar is not None else 0
                scroll_h = hbar.value() if hbar is not None else 0
                saved_state.append((w, w.model(), col_info, scroll_v, scroll_h))
                w.setModel(None)

            # Suppress all repaints on every top-level window before applying the
            # stylesheet.  When Qt processes app.setStyleSheet() it sends a
            # QEvent::StyleChange to every widget in the application and each one
            # responds by scheduling a repaint via update().  With many widgets
            # alive (e.g. hundreds of bookmark-card children that persist in the
            # widget tree even when the bookmarks page is not visible), this
            # produces O(n) paint-event work that causes a multi-second freeze.
            #
            # setUpdatesEnabled(False) on a top-level widget propagates the
            # WA_UpdatesDisabled flag to all its descendants, turning every
            # update() call into a no-op.  After the stylesheet is applied and
            # the model-state is restored we re-enable updates and issue a single
            # update() per top-level, so Qt coalesces all pending repaints into
            # one pass instead of n individual passes.
            top_levels = [w for w in app.topLevelWidgets() if w.isVisible()]
            for w in top_levels:
                w.setUpdatesEnabled(False)

            try:
                app.setStyleSheet(qss)

                deferred_hscroll: list[tuple] = []  # (hbar, scroll_h) Deferred restoration of horizontal scrolling

                for w, model, col_info, scroll_v, scroll_h in saved_state:
                    hbar = w.horizontalScrollBar()
                    if hbar is not None and scroll_h:
                        hbar.setUpdatesEnabled(False)
                        deferred_hscroll.append((hbar, scroll_h))

                    w.setModel(model)
                    if col_info:
                        hh = w.horizontalHeader()
                        for i, (width, mode) in enumerate(col_info):
                            if i < hh.count():
                                hh.setSectionResizeMode(i, mode)
                                if mode in (QHeaderView.Interactive, QHeaderView.Fixed):
                                    hh.resizeSection(i, width)
                    vbar = w.verticalScrollBar()
                    if vbar is not None:
                        vbar.setValue(scroll_v)
            finally:
                # Re-enable updates unconditionally so a mid-apply exception can
                # never leave the UI permanently frozen.
                for w in top_levels:
                    w.setUpdatesEnabled(True)
                    w.update()

            if deferred_hscroll:

                def _restore_hscroll(items=deferred_hscroll):
                    for hbar, val in items:
                        hbar.setValue(val)
                        hbar.setUpdatesEnabled(True)

                QTimer.singleShot(0, _restore_hscroll)

            self._applied = resolved
        else:
            log.error("Could not load QSS for resolved theme '%s'", resolved)

        self._pending = None
        self.theme_changed.emit(resolved)
        log.info("Theme applied: raw=%s resolved=%s", self._raw, resolved)

    # ── Helpers ───────────────────────────────────────────────

    def recolor_svg(self, svg_path: str) -> bytes:
        color = "#a0a8b8" if self._current == THEME_DARK else "#6b7280"
        return _recolor_svg_bytes(svg_path, color)

    def icon_default_color(self) -> str:
        return "#a0a8b8" if self._current == THEME_DARK else "#6b7280"

    def icon_active_color(self) -> str:
        return "#5b9cf6" if self._current == THEME_DARK else "#2563eb"
