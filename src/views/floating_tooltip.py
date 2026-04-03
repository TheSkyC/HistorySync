# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""floating_tooltip.py — theme-aware floating tooltip widget.

A drop-in replacement for QToolTip that draws a properly themed card with:
- Semi-transparent background (95% opacity)
- Smooth fade-in/fade-out animations (150ms in, 100ms out)
- Configurable hover delay (default 500ms, like standard tooltips)

QToolTip is an OS-level top-level window; its background is not reliably
styled by Qt stylesheets on all platforms, falling back to solid black.
This widget draws its own rounded-rect card and always matches the app theme.

Usage (singleton API — no instance management needed by callers):

    FloatingTooltip.show_at(text, global_pos, delay_ms=500, auto_hide_ms=4000)
    FloatingTooltip.hide_global()    # fade out and hide
    FloatingTooltip.cancel_global()  # stop all timers and hide

To integrate: in the host widget's eventFilter, intercept QEvent.ToolTip and
QEvent.Leave, then call the static methods above. Return True from the
ToolTip branch to suppress the native QToolTip.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# ── Style constants ───────────────────────────────────────────────────────────
_OPACITY = 0.96
_FADE_IN_DURATION = 200
_FADE_OUT_DURATION = 120
_DEFAULT_DELAY = 300
_DEFAULT_AUTO_HIDE = 4000
_MAX_WIDTH = 420
_MAX_HEIGHT = 300  # Maximum height before content becomes scrollable
_BORDER_RADIUS = 8
_PADDING = "8px 12px"
_FONT_SIZE = 13
_LINE_HEIGHT = 1.5

# Position offsets
_OFFSET_X = 14
_OFFSET_Y_ABOVE = -8
_OFFSET_Y_BELOW = 20
_SCREEN_MARGIN = 4


class FloatingTooltip(QWidget):
    """Theme-aware frameless tooltip card (singleton, reusable across views)."""

    _instance: FloatingTooltip | None = None

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(_MAX_WIDTH)
        self._label.setMaximumHeight(_MAX_HEIGHT)
        layout.addWidget(self._label)

        # Hover delay timer — waits before showing tooltip
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._do_show)
        self._pending_text = ""
        self._pending_pos = QPoint()
        self._pending_auto_hide_ms = _DEFAULT_AUTO_HIDE
        self._pending_rich_text = False

        # Auto-hide timer — hides tooltip after it's been visible for a while
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade_out)

        # Fade-in animation (0.0 → 0.96 opacity, 200ms)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(_FADE_IN_DURATION)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(_OPACITY)
        self._fade_in.setEasingCurve(QEasingCurve.OutQuad)

        # Fade-out animation (0.96 → 0.0 opacity, 120ms)
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(_FADE_OUT_DURATION)
        self._fade_out.setStartValue(_OPACITY)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InQuad)
        self._fade_out.finished.connect(self.hide)

        # Theme cache — updated on theme change or first show
        self._cached_theme = "dark"
        self._cached_widget_style = ""
        self._cached_label_style = ""
        self._setup_theme_listener()

    # ── Singleton factory ─────────────────────────────────────────────────────

    @classmethod
    def _get(cls) -> FloatingTooltip:
        if cls._instance is None:
            cls._instance = FloatingTooltip()
        return cls._instance

    # ── Theme management ──────────────────────────────────────────────────────

    def _setup_theme_listener(self) -> None:
        """Connect to theme manager's theme_changed signal if available."""
        try:
            from src.utils.theme_manager import ThemeManager

            tm = ThemeManager.instance()
            self._cached_theme = tm.current
            tm.theme_changed.connect(self._on_theme_changed)
            self._update_cached_styles()
        except Exception:
            # Fallback to dark theme if ThemeManager unavailable
            self._cached_theme = "dark"
            self._update_cached_styles()

    def _on_theme_changed(self, theme: str) -> None:
        """Handle theme change event — update cache and apply if visible."""
        self._cached_theme = theme
        self._update_cached_styles()
        if self.isVisible():
            self.setStyleSheet(self._cached_widget_style)
            self._label.setStyleSheet(self._cached_label_style)

    def _update_cached_styles(self) -> None:
        """Pre-build and cache stylesheet strings for current theme."""
        is_dark = self._cached_theme == "dark"
        # Modern color palette with better contrast
        bg = f"rgba(40, 44, 52, {_OPACITY})" if is_dark else f"rgba(255, 255, 255, {_OPACITY})"
        fg = "#e6e8f0" if is_dark else "#2c2c2e"
        border = "rgba(255,255,255,0.08)" if is_dark else "rgba(0,0,0,0.12)"

        self._cached_widget_style = (
            f"background: {bg}; border: 1px solid {border}; border-radius: {_BORDER_RADIUS}px; padding: {_PADDING};"
        )
        self._cached_label_style = f"color: {fg}; font-size: {_FONT_SIZE}px; line-height: {_LINE_HEIGHT}; padding: 0;"

    # ── Public static API ─────────────────────────────────────────────────────

    @staticmethod
    def show_at(
        text: str,
        global_pos: QPoint,
        *,
        delay_ms: int = _DEFAULT_DELAY,
        auto_hide_ms: int = _DEFAULT_AUTO_HIDE,
        rich_text: bool = False,
    ) -> None:
        """Show the global singleton tooltip with *text* near *global_pos*.

        Args:
            text: Tooltip content to display.
            global_pos: Global screen coordinates (e.g., from QEvent.globalPos()).
            delay_ms: Hover delay before showing (default 300ms). Set to 0 for instant.
            auto_hide_ms: Duration to keep tooltip visible (default 4000ms).
            rich_text: If True, interpret text as HTML/rich text (default False).
        """
        inst = FloatingTooltip._get()

        # Content deduplication: if same text is already visible at same position,
        # just reset the auto-hide timer instead of re-animating
        if inst.isVisible() and inst._label.text() == text:
            # Check if position would be the same (within a small tolerance)
            target_pos = inst._calculate_position(global_pos)
            if abs(inst.pos().x() - target_pos.x()) < 5 and abs(inst.pos().y() - target_pos.y()) < 5:
                # Same content, same position — just extend visibility
                inst._hide_timer.start(auto_hide_ms)
                return

        # Stop any ongoing animations/timers to avoid state conflicts
        inst._show_timer.stop()
        inst._fade_in.stop()
        inst._fade_out.stop()
        inst._hide_timer.stop()

        # Store pending show request
        inst._pending_text = text
        inst._pending_pos = global_pos
        inst._pending_auto_hide_ms = auto_hide_ms
        inst._pending_rich_text = rich_text

        if delay_ms > 0:
            # Delayed show (standard tooltip behavior)
            inst._show_timer.start(delay_ms)
        else:
            # Instant show (no delay)
            inst._do_show()

    @staticmethod
    def hide_global() -> None:
        """Immediately hide the singleton tooltip with fade-out animation."""
        inst = FloatingTooltip._instance
        if inst is not None:
            inst._show_timer.stop()
            inst._hide_timer.stop()
            inst._fade_in.stop()
            if inst.isVisible() and inst.windowOpacity() > 0:
                inst._start_fade_out()
            else:
                inst.hide()

    @staticmethod
    def cancel_global() -> None:
        """Stop all timers and hide immediately (used when mouse leaves)."""
        FloatingTooltip.hide_global()

    @classmethod
    def cleanup(cls) -> None:
        """Clean up singleton instance (call on application exit).

        Stops all timers, disconnects signals, and releases the singleton.
        This is optional but recommended for clean shutdown.
        """
        if cls._instance is not None:
            inst = cls._instance
            inst._show_timer.stop()
            inst._hide_timer.stop()
            inst._fade_in.stop()
            inst._fade_out.stop()

            # Disconnect theme listener if connected
            try:
                from src.utils.theme_manager import ThemeManager

                tm = ThemeManager.instance()
                tm.theme_changed.disconnect(inst._on_theme_changed)
            except Exception:
                pass

            inst.deleteLater()
            cls._instance = None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _calculate_position(self, global_pos: QPoint) -> QPoint:
        """Calculate optimal tooltip position near the given global position.

        Tries four directions in order: above → below → right → left.
        Chooses the first direction with enough space.
        """
        # Update size based on current content
        self._label.setText(self._pending_text)
        self.adjustSize()

        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        w, h = self.width(), self.height()

        # Try above first (preferred)
        x_above = global_pos.x() + _OFFSET_X
        y_above = global_pos.y() + _OFFSET_Y_ABOVE - h
        if y_above >= sg.top() and x_above + w <= sg.right() - _SCREEN_MARGIN:
            return QPoint(x_above, y_above)

        # Try below
        x_below = global_pos.x() + _OFFSET_X
        y_below = global_pos.y() + _OFFSET_Y_BELOW
        if y_below + h <= sg.bottom() and x_below + w <= sg.right() - _SCREEN_MARGIN:
            return QPoint(x_below, y_below)

        # Try right side
        x_right = global_pos.x() + _OFFSET_Y_BELOW
        y_right = global_pos.y() - h // 2
        if x_right + w <= sg.right() - _SCREEN_MARGIN and y_right >= sg.top() and y_right + h <= sg.bottom():
            return QPoint(x_right, y_right)

        # Try left side
        x_left = global_pos.x() - w - abs(_OFFSET_X)
        y_left = global_pos.y() - h // 2
        if x_left >= sg.left() + _SCREEN_MARGIN and y_left >= sg.top() and y_left + h <= sg.bottom():
            return QPoint(x_left, y_left)

        # Fallback: clamp to screen bounds (force fit)
        x = max(sg.left() + _SCREEN_MARGIN, min(global_pos.x() + _OFFSET_X, sg.right() - w - _SCREEN_MARGIN))
        y = max(sg.top() + _SCREEN_MARGIN, min(global_pos.y() + _OFFSET_Y_BELOW, sg.bottom() - h - _SCREEN_MARGIN))
        return QPoint(x, y)

    def _do_show(self) -> None:
        """Actually show the tooltip (called after delay timer or immediately)."""
        # Apply cached styles (no theme detection or string building needed)
        self.setStyleSheet(self._cached_widget_style)
        self._label.setStyleSheet(self._cached_label_style)

        # Set text format based on rich_text flag
        if self._pending_rich_text:
            self._label.setTextFormat(Qt.RichText)
        else:
            self._label.setTextFormat(Qt.PlainText)

        self._label.setText(self._pending_text)
        self.adjustSize()

        # Calculate and apply position
        pos = self._calculate_position(self._pending_pos)
        self.move(pos)

        # Fade in from 0.0 to 0.95 opacity
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_in.start()

        # Start auto-hide timer
        self._hide_timer.start(self._pending_auto_hide_ms)

    def _start_fade_out(self) -> None:
        """Start fade-out animation (hides widget when animation finishes)."""
        if self.isVisible():
            self._fade_out.start()
