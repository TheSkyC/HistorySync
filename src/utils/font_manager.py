# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""FontManager — applies custom font settings globally.

Usage
-----
At startup (after QApplication and ThemeManager are ready)::

    from src.utils.font_manager import FontManager
    FontManager.instance().apply(config.font, app)

When the user saves updated font settings::

    FontManager.instance().apply(new_font_config, QApplication.instance())

To revert to built-in defaults::

    FontManager.instance().reset(QApplication.instance())

Architecture
------------
Two layers are written:

1. **Qt application font** — ``QApplication.setFont()`` controls the default
   font for all widgets that do not set their own.  We use ``pt`` units here
   to match what Qt's font system expects.

2. **QSS font override** — A compact stylesheet fragment is *appended* to the
   application stylesheet after every ThemeManager theme_changed signal.  This
   ensures the override survives theme switches.  The fragment targets:

   * ``*``  — overrides the base font-family / font-size set by the QSS file
   * ``QPlainTextEdit#log_viewer``  — monospace override for the log viewer

   Font sizes in QSS are expressed in ``px`` to match the existing QSS
   convention; the ``ui_size`` / ``mono_size`` values stored in ``FontConfig``
   are therefore in pixels.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from src.utils.logger import get_logger

log = get_logger("utils.font_manager")

# CSS families string → quoted list suitable for font-family property
# e.g. 'Segoe UI, Arial' → '"Segoe UI", "Arial"'


def _to_css_families(raw: str) -> str:
    """Convert a comma-separated family string into a properly-quoted CSS value."""
    parts = []
    for raw_token in raw.split(","):
        token = raw_token.strip().strip("'\"")
        if not token:
            continue
        # Generic keywords (sans-serif, serif, monospace, cursive, fantasy) must NOT be quoted
        if token.lower() in ("sans-serif", "serif", "monospace", "cursive", "fantasy"):
            parts.append(token)
        else:
            parts.append(f'"{token}"')
    return ", ".join(parts) if parts else '"Segoe UI", sans-serif'


def _primary_family(raw: str) -> str:
    """Return just the first font family name (for QFont.setFamily)."""
    for raw_token in raw.split(","):
        token = raw_token.strip().strip("'\"")
        if token:
            return token
    return "Segoe UI"


def _all_families(raw: str) -> list[str]:
    """Return a list of family names (for QFont.setFamilies)."""
    result = []
    for raw_token in raw.split(","):
        token = raw_token.strip().strip("'\"")
        if token:
            result.append(token)
    return result or ["Segoe UI"]


# ── Theme font-size scaling table ────────────────────────────────────────────
# The QSS theme hardcodes font-size on specific selectors. Because those rules
# have higher specificity than `*`, a bare `* { font-size: Xpx }` override
# cannot beat them. We therefore enumerate every selector that carries a
# hardcoded font-size and regenerate it proportionally scaled.
#
# Format: (selector, base_px_in_theme)
# Theme base = 13 px.  Sizes are scaled as: round(base_px * user_px / 13).
_THEME_BASE_PX = 13

_SCALED_SELECTORS: list[tuple[str, int]] = [
    # General input / interactive widgets
    ("QPushButton", 13),
    ("QLineEdit", 13),
    ("QLineEdit#search_box", 13),
    ("QPlainTextEdit#search_box", 13),
    # Navigation
    ("QPushButton#nav_btn", 20),
    # Page headings
    ("QLabel#page_title", 20),
    ("QLabel#page_subtitle", 12),
    # Dashboard stat cards
    ("QLabel#stat_value", 28),
    ("QLabel#stat_label", 11),
    ("QLabel#settings_stat_value", 13),
    # Status dots (small icon-like labels)
    ("QLabel#status_dot_ok", 9),
    ("QLabel#status_dot_warn", 9),
    ("QLabel#status_dot_err", 9),
    # Table header & status bar
    ("QHeaderView::section", 11),
    ("QStatusBar", 11),
    # Muted / secondary text labels
    ("QLabel#muted", 12),
    ("QLabel#note_text", 12),
    ("QLabel#muted_small", 11),
    ("QLabel#inline_tag", 11),
    ("QLabel#sidebar_section_title", 11),
    ("QLabel#footer_label", 11),
    # Browser card
    ("QLabel#browser_card_name", 13),
    # Tooltip
    ("QToolTip", 12),
    # Search / filter chips
    ("QPushButton#filter_chip", 11),
    ("QPushButton#operator_chip", 11),
]

# Selectors whose QSS also hard-codes min-height AND max-height (locking the box
# size independent of font).  FontManager must emit scaled height overrides for
# these so the box grows together with the font.
#
# Format: (selector, base_min_px, base_max_px)
# Both values come from the theme QSS at _THEME_BASE_PX (13 px).
_SCALED_HEIGHT_SELECTORS: list[tuple[str, int, int]] = [
    # nav_btn: QSS sets min-height:40px / max-height:40px at font-size 20px
    ("QPushButton#nav_btn", 40, 40),
    # operator_chip: QSS sets min-height:20px / max-height:20px at font-size 11px
    ("QPushButton#operator_chip", 20, 20),
    # status bar: QSS sets min-height:26px; font-size is scaled so height must follow
    ("QStatusBar", 26, 26),
    # table rows: QSS sets min-height:36px; large fonts will be clipped without this
    ("QTableView::item", 36, 36),
    # combobox popup items: QSS sets min-height:24px
    ("QComboBox QAbstractItemView::item", 24, 24),
]


class FontManager(QObject):
    """Singleton that manages global font overrides."""

    _instance: FontManager | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._qss_fragment = ""
        self._theme_connected = False  # tracks whether we're wired to ThemeManager
        # Debounce timer so rapid theme_changed signals don't spam setStyleSheet
        self._reapply_timer = QTimer(self)
        self._reapply_timer.setSingleShot(True)
        self._reapply_timer.setInterval(0)
        self._reapply_timer.timeout.connect(self._reapply_qss)

    @classmethod
    def instance(cls) -> FontManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────────────────────

    def apply(self, font_cfg, app: QApplication | None = None) -> None:
        """Apply *font_cfg* (a ``FontConfig`` instance) globally.

        Safe to call from any thread as long as the Qt event loop is running
        (uses a zero-interval timer for the QSS part).
        """
        if app is None:
            app = QApplication.instance()
        if app is None:
            log.warning("FontManager.apply called before QApplication was created")
            return

        self._enabled = font_cfg.enabled

        if not font_cfg.enabled:
            self._reset_app_font(app)
            self._qss_fragment = ""
            self._reapply_timer.start()
            self._disconnect_theme_signal()
            log.debug("Custom fonts disabled — reverted to defaults")
            return

        # ── 1. Application font (Qt pt units) ───────────────────────────────
        # Convert px → pt (approximate; 96 DPI screen → 1 pt ≈ 1.333 px)
        ui_pt = max(6, round(font_cfg.ui_size * 72 / 96))
        qfont = QFont()
        families = _all_families(font_cfg.ui_family)
        qfont.setFamilies(families)
        qfont.setPointSize(ui_pt)
        app.setFont(qfont)
        log.debug(
            "App font set: families=%s size=%dpt (%dpx)",
            families,
            ui_pt,
            font_cfg.ui_size,
        )

        # ── 2. QSS override fragment ─────────────────────────────────────────
        # Append AFTER the theme stylesheet so same-specificity rules win.
        # We explicitly repeat every selector that the theme hardcodes a
        # font-size on (they beat `*` via higher specificity); our copies
        # appear later in the sheet and therefore override them.
        ui_css_families = _to_css_families(font_cfg.ui_family)
        mono_css_families = _to_css_families(font_cfg.mono_family)
        ui_px = font_cfg.ui_size

        lines: list[str] = ["\n/* ── FontManager override ── */"]

        # Base rule covers widgets that inherit and don't have explicit rules
        lines.append(f"* {{ font-family: {ui_css_families}; font-size: {ui_px}px; }}")

        # Per-selector overrides, proportionally scaled from the theme's base
        for selector, base_px in _SCALED_SELECTORS:
            scaled_px = max(8, round(base_px * ui_px / _THEME_BASE_PX))
            lines.append(f"{selector} {{ font-family: {ui_css_families}; font-size: {scaled_px}px; }}")

        # Height overrides for selectors whose QSS also hard-codes min/max-height.
        # Without these the font grows but the box stays at the theme's original
        # pixel value, clipping the text at larger font sizes.
        for selector, base_min_px, base_max_px in _SCALED_HEIGHT_SELECTORS:
            scaled_min = max(base_min_px, round(base_min_px * ui_px / _THEME_BASE_PX))
            scaled_max = max(base_max_px, round(base_max_px * ui_px / _THEME_BASE_PX))
            lines.append(f"{selector} {{ min-height: {scaled_min}px; max-height: {scaled_max}px; }}")

        # Monospace font for log viewer (separate control)
        lines.append(
            f"QPlainTextEdit#log_viewer {{ font-family: {mono_css_families}; font-size: {font_cfg.mono_size}px; }}"
        )

        self._qss_fragment = "\n".join(lines) + "\n"

        self._reapply_timer.start()
        self._connect_theme_signal()
        log.info(
            "Custom fonts applied: ui=%r %dpx  mono=%r %dpx",
            font_cfg.ui_family,
            font_cfg.ui_size,
            font_cfg.mono_family,
            font_cfg.mono_size,
        )

    def reset(self, app: QApplication | None = None) -> None:
        """Revert to built-in defaults (disables the override)."""
        if app is None:
            app = QApplication.instance()
        self._enabled = False
        self._qss_fragment = ""
        if app is not None:
            self._reset_app_font(app)
        self._reapply_timer.start()
        log.debug("FontManager reset to defaults")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect_theme_signal(self) -> None:
        """Connect to ThemeManager.theme_changed (idempotent, no-warning)."""
        if self._theme_connected:
            return
        try:
            from src.utils.theme_manager import ThemeManager

            tm = ThemeManager.instance()
            tm.theme_changed.connect(self._on_theme_changed)
            self._theme_connected = True
        except Exception as exc:
            log.warning("Could not connect to ThemeManager: %s", exc)

    def _disconnect_theme_signal(self) -> None:
        """Disconnect from ThemeManager.theme_changed (safe to call when not connected)."""
        if not self._theme_connected:
            return
        try:
            from src.utils.theme_manager import ThemeManager

            tm = ThemeManager.instance()
            tm.theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, Exception):
            pass
        self._theme_connected = False

    def _on_theme_changed(self, _resolved: str) -> None:
        """Re-apply QSS fragment after every theme switch."""
        # Always retrigger so stale fragments are stripped even if _qss_fragment is empty
        self._reapply_timer.start()

    def _reapply_qss(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        current = app.styleSheet()
        # Strip any previously injected fragment to avoid duplicates
        clean = re.sub(
            r"\n/\* ── FontManager override ── \*/.*",
            "",
            current,
            flags=re.DOTALL,
        )
        app.setStyleSheet(clean + self._qss_fragment)
        log.debug("FontManager QSS fragment (re)applied")

    @staticmethod
    def _reset_app_font(app: QApplication) -> None:
        """Restore the original default font defined in constants."""
        from src.utils.constants import DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE

        font = QFont()
        font.setFamily(DEFAULT_FONT_FAMILY)
        font.setPointSize(DEFAULT_FONT_SIZE)
        app.setFont(font)

    # ── Utility: available system fonts ──────────────────────────────────────

    @staticmethod
    def available_families() -> list[str]:
        """Return sorted list of font families available on this system."""
        return sorted(QFontDatabase.families())
