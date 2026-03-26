# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLayout, QLayoutItem, QPushButton, QSizePolicy, QWidget

# ── Flow Layout ───────────────────────────────────────────────────────────────


class FlowLayout(QLayout):
    """
    A layout that arranges items left-to-right and wraps to the next row
    when the available width is exhausted.

    Parameters
    ----------
    h_spacing : int
        Horizontal gap between items (px). Defaults to 6.
    v_spacing : int
        Vertical gap between rows (px). Defaults to 6.
    """

    def __init__(self, parent=None, h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    # ── QLayout interface ─────────────────────────────────────────────────────

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, dry_run=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    # ── Layout engine ─────────────────────────────────────────────────────────

    def _do_layout(self, rect: QRect, *, dry_run: bool) -> int:
        """
        Arrange items inside *rect*.

        When *dry_run* is ``True`` only the required height is returned
        (no geometry is applied), which is needed for ``heightForWidth``.
        """
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        row_height = 0
        right_limit = rect.right() - margins.right()

        for item in self._items:
            item_size = item.sizeHint()
            w, h = item_size.width(), item_size.height()

            next_x = x + w
            if x > rect.x() + margins.left() and next_x > right_limit + 1:
                x = rect.x() + margins.left()
                y += row_height + self._v_spacing
                row_height = 0

            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x += w + self._h_spacing
            row_height = max(row_height, h)

        bottom_margin = margins.bottom()
        return y + row_height - rect.y() + bottom_margin


# ── OptionButton ──────────────────────────────────────────────────────────────


class OptionButton(QPushButton):
    """
    An animated toggle button that adapts to the active theme.

    The accent colour is derived from ThemeManager so all buttons share a
    single, unified look that automatically updates on theme changes.

    Parameters
    ----------
    key : str
        Internal identifier (maps to a column key, etc.).
    label : str
        Visible button text.
    """

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setText(label)

        # Animated state values
        self._bg_opacity: float = 0.0
        self._border_opacity: float = 0.0
        self._animation_group: QParallelAnimationGroup | None = None

        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._update_style()
        self.toggled.connect(self._on_toggled)

    # ── Theme helpers ──────────────────────────────────────────────────────────

    def _theme_colors(self) -> dict:
        """Return a palette dict for the current theme."""
        try:
            from src.utils.theme_manager import ThemeManager

            is_dark = ThemeManager.instance().current == "dark"
        except Exception:
            is_dark = True

        if is_dark:
            return {
                "accent": "#5b9cf6",
                "text_muted": "#a0a8b8",
                "bg_unchecked": "#2a2d35",
                "bg_hover_unchecked": "#32363f",
            }
        return {
            "accent": "#2563eb",
            "text_muted": "#6b7280",
            "bg_unchecked": "#f0f2f5",
            "bg_hover_unchecked": "#e5e7eb",
        }

    def refresh_theme(self) -> None:
        """Force a full style refresh — call after a theme change."""
        self._update_style()

    # ── Animation ─────────────────────────────────────────────────────────────

    def _on_toggled(self, checked: bool) -> None:
        if self._animation_group:
            self._animation_group.stop()

        self._animation_group = QParallelAnimationGroup(self)

        bg_anim = QPropertyAnimation(self, b"bg_opacity")
        bg_anim.setDuration(250)
        bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        bg_anim.setStartValue(self._bg_opacity)
        bg_anim.setEndValue(0.15 if checked else 0.0)

        border_anim = QPropertyAnimation(self, b"border_opacity")
        border_anim.setDuration(250)
        border_anim.setEasingCurve(QEasingCurve.OutCubic)
        border_anim.setStartValue(self._border_opacity)
        border_anim.setEndValue(1.0 if checked else 0.0)

        self._animation_group.addAnimation(bg_anim)
        self._animation_group.addAnimation(border_anim)
        self._animation_group.start()

    # ── Qt Properties ─────────────────────────────────────────────────────────

    def get_bg_opacity(self) -> float:
        return self._bg_opacity

    def set_bg_opacity(self, value: float) -> None:
        self._bg_opacity = value
        self._update_style()

    bg_opacity = Property(float, get_bg_opacity, set_bg_opacity)

    def get_border_opacity(self) -> float:
        return self._border_opacity

    def set_border_opacity(self, value: float) -> None:
        self._border_opacity = value
        self._update_style()

    border_opacity = Property(float, get_border_opacity, set_border_opacity)

    # ── Styling ───────────────────────────────────────────────────────────────

    def _update_style(self) -> None:
        palette = self._theme_colors()
        accent = QColor(palette["accent"])
        text_muted = QColor(palette["text_muted"])
        bg_unchecked = palette["bg_unchecked"]
        bg_hover_unchecked = palette["bg_hover_unchecked"]

        # Background — tinted with accent at current opacity
        checked_bg = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._bg_opacity})"

        # Border — accent at current opacity
        border_color = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {self._border_opacity})"

        # Text — interpolated from muted → accent as checked animation progresses
        if self.isChecked():
            f = self._border_opacity
            r = int(text_muted.red() + (accent.red() - text_muted.red()) * f)
            g = int(text_muted.green() + (accent.green() - text_muted.green()) * f)
            b = int(text_muted.blue() + (accent.blue() - text_muted.blue()) * f)
            text_color = QColor(r, g, b).name()
        else:
            text_color = text_muted.name()

        css = f"""
            QPushButton {{
                background-color: {checked_bg if self.isChecked() else bg_unchecked};
                border: 1px solid {border_color if self.isChecked() else "transparent"};
                border-radius: 12px;
                padding: 4px 10px;
                color: {text_color};
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {checked_bg if self.isChecked() else bg_hover_unchecked};
            }}
            QPushButton:disabled {{
                opacity: 0.4;
            }}
        """
        self.setStyleSheet(css)


# ── OptionSelector ────────────────────────────────────────────────────────────


class OptionSelector(QWidget):
    """
    A wrapping strip of animated toggle buttons.

    Buttons flow left-to-right and automatically wrap onto new rows when the
    widget is too narrow to fit them all in one line.

    Parameters
    ----------
    options : list[tuple[str, str]]
        Each entry is ``(key, label)``.
    h_spacing : int
        Horizontal gap between buttons (px). Default 6.
    v_spacing : int
        Vertical gap between rows (px). Default 6.
    """

    selectionChanged = Signal(list)  # emits list[str] of selected keys

    def __init__(
        self,
        options: list,
        parent=None,
        *,
        h_spacing: int = 6,
        v_spacing: int = 6,
    ):
        super().__init__(parent)
        self._buttons: dict[str, OptionButton] = {}
        self._options_config = options
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._setup_ui()
        self._connect_theme()

    def _setup_ui(self) -> None:
        layout = FlowLayout(self, h_spacing=self._h_spacing, v_spacing=self._v_spacing)
        layout.setContentsMargins(0, 0, 0, 0)

        for option in self._options_config:
            key = option[0]
            label = option[1]
            btn = OptionButton(key, label)
            btn.toggled.connect(self._on_button_toggled)
            layout.addWidget(btn)
            self._buttons[key] = btn

    def _connect_theme(self) -> None:
        """Subscribe to ThemeManager so buttons refresh on theme changes."""
        try:
            from src.utils.theme_manager import ThemeManager

            ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        except Exception:
            pass

    def _on_theme_changed(self, _theme: str) -> None:
        for btn in self._buttons.values():
            btn.refresh_theme()

    # ── Signals ───────────────────────────────────────────────────────────────

    def _on_button_toggled(self) -> None:
        self.selectionChanged.emit(self.get_selection())

    # ── Public API ────────────────────────────────────────────────────────────

    def get_selection(self) -> list[str]:
        """Return the list of currently selected keys."""
        return [key for key, btn in self._buttons.items() if btn.isChecked()]

    def set_selection(self, keys: list[str] | None) -> None:
        """Set which keys are checked (others are unchecked)."""
        self.blockSignals(True)
        for key, btn in self._buttons.items():
            btn.setChecked(key in (keys or []))
        self.blockSignals(False)

    def select_all(self) -> None:
        self.set_selection(list(self._buttons.keys()))
        self.selectionChanged.emit(self.get_selection())

    def select_none(self) -> None:
        self.set_selection([])
        self.selectionChanged.emit(self.get_selection())

    def set_option_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a specific option button.

        When a button is disabled it is also unchecked, and ``selectionChanged``
        is emitted so callers can react (e.g. refresh a record count).
        """
        if key not in self._buttons:
            return
        btn = self._buttons[key]
        was_checked = btn.isChecked()
        btn.setEnabled(enabled)
        if not enabled and was_checked:
            btn.setChecked(False)
            self.selectionChanged.emit(self.get_selection())
