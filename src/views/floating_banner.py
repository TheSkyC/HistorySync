# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ctypes as _ctypes
from dataclasses import dataclass, field
from typing import Literal

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.icon_helper import get_icon

BannerPosition = Literal[
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]
BannerActionKind = Literal["primary", "secondary", "ghost"]
BannerActionsAlignment = Literal["left", "right"]
BannerTone = Literal["info", "success", "warning", "danger", "neutral"]

_OUTER_MARGIN = 18
_FADE_IN_MS = 180
_FADE_OUT_MS = 120
_POSITION_SYNC_MS = 24
_WM_MOUSEACTIVATE = 0x0021
_MA_NOACTIVATE = 3


class _WinMSG(_ctypes.Structure):
    _fields_ = [
        ("hwnd", _ctypes.c_void_p),
        ("message", _ctypes.c_uint),
        ("wParam", _ctypes.c_size_t),
        ("lParam", _ctypes.c_size_t),
        ("time", _ctypes.c_uint),
        ("pt_x", _ctypes.c_long),
        ("pt_y", _ctypes.c_long),
    ]


def _rgba(color: str, alpha: float) -> str:
    qcolor = QColor(color)
    alpha_channel = max(0, min(255, int(alpha * 255)))
    return f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, {alpha_channel})"


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    a = QColor(color_a)
    b = QColor(color_b)
    ratio = max(0.0, min(1.0, ratio))
    red = round(a.red() * (1.0 - ratio) + b.red() * ratio)
    green = round(a.green() * (1.0 - ratio) + b.green() * ratio)
    blue = round(a.blue() * (1.0 - ratio) + b.blue() * ratio)
    return QColor(red, green, blue).name()


def _lighter(color: str, factor: int = 112) -> str:
    return QColor(color).lighter(factor).name()


def _darker(color: str, factor: int = 112) -> str:
    return QColor(color).darker(factor).name()


@dataclass(slots=True, frozen=True)
class BannerAction:
    action_id: str
    text: str
    kind: BannerActionKind = "secondary"
    icon_name: str | None = None
    enabled: bool = True
    auto_dismiss: bool = False


@dataclass(slots=True)
class BannerStyle:
    tone: BannerTone = "info"
    accent_color: str | None = None
    background_color: str | None = None
    background_color_alt: str | None = None
    border_color: str | None = None
    title_color: str | None = None
    text_color: str | None = None
    badge_background_color: str | None = None
    badge_text_color: str | None = None
    shadow_color: str | None = None
    border_radius: int = 20
    padding: int = 18
    custom_stylesheet: str = ""


@dataclass(slots=True)
class BannerLayout:
    position: BannerPosition = "top-right"
    width: int = 420
    min_width: int = 320
    max_width: int = 560
    margin: int = 20
    offset_x: int = 0
    offset_y: int = 0
    show_close: bool = True
    actions_alignment: BannerActionsAlignment = "right"
    hide_when_anchor_inactive: bool = True


@dataclass(slots=True)
class BannerConfig:
    title: str = ""
    message: str = ""
    badge_text: str = ""
    icon_name: str | None = "info"
    icon_size: int = 18
    rich_text: bool = False
    actions: tuple[BannerAction, ...] = field(default_factory=tuple)
    style: BannerStyle = field(default_factory=BannerStyle)
    layout: BannerLayout = field(default_factory=BannerLayout)
    auto_hide_ms: int = 0


@dataclass(slots=True, frozen=True)
class _ResolvedBannerPalette:
    accent: str
    background_start: str
    background_end: str
    border: str
    title: str
    text: str
    badge_background: str
    badge_text: str
    close_icon: str
    shadow: str


class FloatingBanner(QWidget):
    """Independent, theme-aware floating banner window."""

    action_triggered = Signal(str)
    dismissed = Signal()

    def __init__(self, anchor: QWidget | None = None) -> None:
        super().__init__(
            anchor,
            Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_X11DoNotAcceptFocus, True)
        self.setObjectName("floating_banner_window")
        self.setStyleSheet("#floating_banner_window { background: transparent; }")
        self.setFocusPolicy(Qt.NoFocus)

        self._anchor_widget: QWidget | None = None
        self._anchor_marked_inactive = False
        self._requested_visible = False
        self._pending_dismiss_signal = False
        self._cached_theme = "dark"
        self._config = BannerConfig()
        self._action_buttons: dict[str, QPushButton] = {}

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.dismiss_banner)

        self._position_sync_timer = QTimer(self)
        self._position_sync_timer.setInterval(_POSITION_SYNC_MS)
        self._position_sync_timer.timeout.connect(lambda: self._sync_visibility(animate=False))

        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(_FADE_IN_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(_FADE_OUT_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_finished)

        self._build_ui()
        self._setup_theme_listener()
        self.set_anchor_widget(anchor)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN, _OUTER_MARGIN)
        outer.setSpacing(0)

        self._card = QFrame()
        self._card.setObjectName("floating_banner_card")
        self._card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._card.setAttribute(Qt.WA_StyledBackground, True)
        self._card.setFocusPolicy(Qt.NoFocus)
        outer.addWidget(self._card)

        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        self._card.setGraphicsEffect(shadow)
        self._shadow = shadow

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        card_layout.addLayout(header_layout)

        self._icon_lbl = QLabel()
        self._icon_lbl.setObjectName("floating_banner_icon")
        self._icon_lbl.setFixedSize(18, 18)
        header_layout.addWidget(self._icon_lbl, 0, Qt.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        header_layout.addLayout(title_col, 1)

        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(6)
        title_col.addLayout(meta_layout)

        self._badge_lbl = QLabel()
        self._badge_lbl.setObjectName("floating_banner_badge")
        meta_layout.addWidget(self._badge_lbl, 0, Qt.AlignVCenter)

        self._title_lbl = QLabel()
        self._title_lbl.setObjectName("floating_banner_title")
        self._title_lbl.setWordWrap(True)
        meta_layout.addWidget(self._title_lbl, 1, Qt.AlignVCenter)

        self._close_btn = QPushButton()
        self._close_btn.setObjectName("floating_banner_close")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setFocusPolicy(Qt.NoFocus)
        self._close_btn.clicked.connect(self.dismiss_banner)
        header_layout.addWidget(self._close_btn, 0, Qt.AlignVCenter)

        self._message_lbl = QLabel()
        self._message_lbl.setObjectName("floating_banner_message")
        self._message_lbl.setWordWrap(True)
        self._message_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._message_lbl.setOpenExternalLinks(True)
        card_layout.addWidget(self._message_lbl)

        self._actions_wrap = QWidget()
        self._actions_wrap.setObjectName("floating_banner_actions_wrap")
        self._actions_wrap.setAutoFillBackground(False)
        self._actions_layout = QHBoxLayout(self._actions_wrap)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(10)
        card_layout.addWidget(self._actions_wrap)

    def _setup_theme_listener(self) -> None:
        try:
            from src.utils.theme_manager import ThemeManager

            manager = ThemeManager.instance()
            self._cached_theme = manager.current
            manager.theme_changed.connect(self._on_theme_changed)
        except Exception:
            self._cached_theme = "dark"

    def _on_theme_changed(self, theme: str) -> None:
        self._cached_theme = theme
        self._apply_theme()

    @staticmethod
    def _is_valid_widget(widget: QWidget | None) -> bool:
        if widget is None:
            return False
        try:
            widget.objectName()
        except RuntimeError:
            return False
        return True

    def _clear_anchor_if_matches(self, watched) -> None:
        if not self._is_valid_widget(self._anchor_widget):
            self._anchor_widget = None
            return
        try:
            anchor_window = self._anchor_widget.window()
        except RuntimeError:
            self._anchor_widget = None
            return
        if watched is self._anchor_widget or watched is anchor_window:
            self._anchor_widget = None

    def set_anchor_widget(self, anchor: QWidget | None) -> None:
        previous_anchor = self._anchor_widget if self._is_valid_widget(self._anchor_widget) else None
        previous_window = None
        if previous_anchor is not None:
            try:
                previous_window = previous_anchor.window()
            except RuntimeError:
                previous_window = None
        if previous_window is not None:
            try:
                previous_window.removeEventFilter(self)
            except RuntimeError:
                pass
        if previous_anchor is not None and previous_anchor is not previous_window:
            try:
                previous_anchor.removeEventFilter(self)
            except RuntimeError:
                pass

        self._anchor_widget = anchor
        self._anchor_marked_inactive = False
        if self._is_valid_widget(anchor):
            anchor.installEventFilter(self)
            anchor.destroyed.connect(lambda _obj=None, watched=anchor: self._clear_anchor_if_matches(watched))
            try:
                anchor_window = anchor.window()
                anchor_window.installEventFilter(self)
                anchor_window.destroyed.connect(
                    lambda _obj=None, watched=anchor_window: self._clear_anchor_if_matches(watched)
                )
            except RuntimeError:
                self._anchor_widget = None

        self._sync_visibility(animate=False)

    def _anchor_window(self) -> QWidget | None:
        if not self._is_valid_widget(self._anchor_widget):
            self._anchor_widget = None
            return None
        try:
            return self._anchor_widget.window()
        except RuntimeError:
            self._anchor_widget = None
            return None

    @staticmethod
    def _supports_window_activation() -> bool:
        """Whether the current Qt platform plugin reports activation reliably."""
        app = QGuiApplication.instance()
        if app is None:
            return True
        try:
            platform_name = (app.platformName() or "").lower()
        except RuntimeError:
            return True
        return platform_name not in {"offscreen", "minimal"}

    def _is_anchor_window_active(self) -> bool:
        anchor_window = self._anchor_window()
        if anchor_window is None:
            return True
        if not self._supports_window_activation():
            return True
        try:
            return anchor_window.isActiveWindow()
        except RuntimeError:
            self._anchor_widget = None
            return True

    def nativeEvent(self, event_type: bytes, message) -> tuple[bool, int]:
        if event_type == b"windows_generic_MSG":
            msg = _WinMSG.from_address(int(message))
            if msg.message == _WM_MOUSEACTIVATE:
                return True, _MA_NOACTIVATE
        return super().nativeEvent(event_type, message)

    def eventFilter(self, watched, event) -> bool:
        anchor_window = self._anchor_window()
        if anchor_window is None:
            return super().eventFilter(watched, event)

        if watched in {self._anchor_widget, anchor_window}:
            if event.type() in {
                QEvent.Move,
                QEvent.Resize,
                QEvent.Show,
                QEvent.Hide,
                QEvent.WindowStateChange,
                QEvent.WindowActivate,
            }:
                if event.type() in {QEvent.Show, QEvent.WindowActivate}:
                    self._anchor_marked_inactive = False
                QTimer.singleShot(0, lambda: self._sync_visibility(animate=False))
            elif event.type() == QEvent.WindowDeactivate:
                if self._config.layout.hide_when_anchor_inactive and (
                    self._supports_window_activation() or not event.spontaneous()
                ):
                    self._anchor_marked_inactive = True
                    self.hide()
        return super().eventFilter(watched, event)

    def current_config(self) -> BannerConfig:
        return self._config

    def button_for_action(self, action_id: str) -> QPushButton | None:
        return self._action_buttons.get(action_id)

    def show_banner(self, config: BannerConfig) -> None:
        self._config = config
        self._anchor_marked_inactive = False
        self._requested_visible = True
        self._pending_dismiss_signal = False
        self._apply_config()
        self._sync_visibility(animate=not self.isVisible())

    def hide_banner(self) -> None:
        self._requested_visible = False
        self._pending_dismiss_signal = False
        self._position_sync_timer.stop()
        self._auto_hide_timer.stop()
        self._fade_in.stop()
        self._fade_out.stop()
        self.hide()

    def dismiss_banner(self) -> None:
        self._requested_visible = False
        self._pending_dismiss_signal = True
        self._position_sync_timer.stop()
        self._auto_hide_timer.stop()
        self._fade_in.stop()
        if self.isVisible():
            self._fade_out.stop()
            self._fade_out.start()
        else:
            self._on_fade_out_finished()

    def _on_fade_out_finished(self) -> None:
        self._position_sync_timer.stop()
        self.hide()
        self.setWindowOpacity(1.0)
        if self._pending_dismiss_signal:
            self._pending_dismiss_signal = False
            self.dismissed.emit()

    def _apply_config(self) -> None:
        config = self._config
        layout = config.layout
        width = max(layout.min_width, min(layout.width, layout.max_width))
        self._card.setFixedWidth(width)

        self._title_lbl.setVisible(bool(config.title))
        self._title_lbl.setText(config.title)

        self._badge_lbl.setVisible(bool(config.badge_text))
        self._badge_lbl.setText(config.badge_text)

        self._message_lbl.setTextFormat(Qt.RichText if config.rich_text else Qt.PlainText)
        self._message_lbl.setText(config.message)

        if config.icon_name:
            palette = self._resolve_palette()
            pixmap = get_icon(config.icon_name, config.icon_size, palette.accent).pixmap(
                config.icon_size,
                config.icon_size,
            )
            self._icon_lbl.setPixmap(pixmap)
            self._icon_lbl.setVisible(not pixmap.isNull())
        else:
            self._icon_lbl.clear()
            self._icon_lbl.hide()

        self._close_btn.setVisible(layout.show_close)
        self._rebuild_actions()
        self._apply_theme()
        self.adjustSize()

    def _rebuild_actions(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._action_buttons.clear()
        actions = self._config.actions
        self._actions_wrap.setVisible(bool(actions))
        if not actions:
            return

        if self._config.layout.actions_alignment == "right":
            self._actions_layout.addStretch(1)

        for action in actions:
            button = QPushButton(action.text)
            button.setObjectName(f"floating_banner_action_{action.action_id}")
            button.setCursor(Qt.PointingHandCursor)
            button.setEnabled(action.enabled)
            button.setMinimumHeight(30)
            button.setFocusPolicy(Qt.NoFocus)
            if action.icon_name:
                button.setIcon(get_icon(action.icon_name, 14))
            button.clicked.connect(
                lambda checked=False, action_id=action.action_id, auto=action.auto_dismiss: self._on_action_clicked(
                    action_id,
                    auto,
                )
            )
            self._actions_layout.addWidget(button, 0)
            self._action_buttons[action.action_id] = button

        if self._config.layout.actions_alignment == "left":
            self._actions_layout.addStretch(1)

    def _on_action_clicked(self, action_id: str, auto_dismiss: bool) -> None:
        self.action_triggered.emit(action_id)
        if auto_dismiss:
            self.dismiss_banner()

    def _apply_theme(self) -> None:
        palette = self._resolve_palette()
        style = self._config.style

        self._card.setStyleSheet(
            f"""
            #floating_banner_card {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 {palette.background_start},
                    stop: 1 {palette.background_end}
                );
                border: 1px solid {palette.border};
                border-radius: {style.border_radius}px;
            }}
            #floating_banner_actions_wrap {{
                background: transparent;
            }}
            {style.custom_stylesheet}
            """
        )
        self._shadow.setColor(QColor(palette.shadow))
        self._card.layout().setContentsMargins(style.padding, style.padding, style.padding, style.padding)

        self._title_lbl.setStyleSheet(
            f"color: {palette.title}; font-size: 14px; font-weight: 700; background: transparent;"
        )
        self._message_lbl.setStyleSheet(
            f"color: {palette.text}; font-size: 12px; line-height: 1.35; background: transparent;"
        )
        self._badge_lbl.setStyleSheet(
            "QLabel {"
            f"color: {palette.badge_text};"
            f"background: {palette.badge_background};"
            "border: none;"
            "border-radius: 8px;"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 2px 7px;"
            "}"
        )

        self._close_btn.setIcon(get_icon("x-circle", 16, palette.close_icon))
        self._close_btn.setStyleSheet(
            "QPushButton {"
            "border: none;"
            "background: transparent;"
            "border-radius: 15px;"
            "}"
            f"QPushButton:hover {{ background: {_rgba(palette.accent, 0.12)}; }}"
            f"QPushButton:pressed {{ background: {_rgba(palette.accent, 0.18)}; }}"
        )

        for action in self._config.actions:
            button = self._action_buttons.get(action.action_id)
            if button is None:
                continue
            button.setStyleSheet(self._button_stylesheet(action.kind, palette))

    def _button_stylesheet(self, kind: BannerActionKind, palette: _ResolvedBannerPalette) -> str:
        if kind == "primary":
            hover = _lighter(palette.accent, 108) if self._cached_theme == "dark" else _darker(palette.accent, 104)
            pressed = _darker(palette.accent, 110)
            border = palette.accent
            text = "#f8fbff" if QColor(palette.accent).lightness() < 150 else "#0f172a"
            background = palette.accent
        elif kind == "ghost":
            hover = _rgba(palette.accent, 0.08)
            pressed = _rgba(palette.accent, 0.14)
            border = "transparent"
            text = palette.text
            background = "transparent"
        else:
            hover = _rgba(palette.accent, 0.10)
            pressed = _rgba(palette.accent, 0.16)
            border = _rgba(palette.accent, 0.22)
            text = palette.accent
            background = _rgba(palette.accent, 0.05)

        disabled_bg = _rgba(palette.text, 0.06)
        disabled_fg = _rgba(palette.text, 0.45)
        disabled_border = _rgba(palette.text, 0.12)

        return (
            "QPushButton {"
            f"background: {background};"
            f"color: {text};"
            f"border: 1px solid {border};"
            "border-radius: 9px;"
            "padding: 6px 12px;"
            "font-size: 11px;"
            "font-weight: 600;"
            "}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {pressed}; }}"
            "QPushButton:disabled {"
            f"background: {disabled_bg};"
            f"color: {disabled_fg};"
            f"border-color: {disabled_border};"
            "}"
        )

    def _resolve_palette(self) -> _ResolvedBannerPalette:
        style = self._config.style
        is_dark = self._cached_theme == "dark"
        tone_defaults: dict[BannerTone, str] = {
            "info": "#4f8ef7" if is_dark else "#2563eb",
            "success": "#2fbf8c" if is_dark else "#0f766e",
            "warning": "#f59e0b" if is_dark else "#d97706",
            "danger": "#fb7185" if is_dark else "#dc2626",
            "neutral": "#94a3b8" if is_dark else "#64748b",
        }

        accent = style.accent_color or tone_defaults[style.tone]
        base = "#0f172a" if is_dark else "#ffffff"
        base_alt = "#162033" if is_dark else "#f8fafc"
        text = "#e8eef8" if is_dark else "#1e293b"
        title = "#f8fbff" if is_dark else "#0f172a"
        border = _rgba(accent, 0.22 if is_dark else 0.18)
        bg_start = _mix(base, accent, 0.12 if is_dark else 0.05)
        bg_end = _mix(base_alt, accent, 0.2 if is_dark else 0.08)
        badge_bg = _rgba(accent, 0.18 if is_dark else 0.1)
        badge_text = _lighter(accent, 130) if is_dark else _darker(accent, 118)
        shadow = _rgba(style.shadow_color or accent, 0.14 if is_dark else 0.08)
        close_icon = _mix(text, accent, 0.25 if is_dark else 0.18)

        return _ResolvedBannerPalette(
            accent=accent,
            background_start=style.background_color or bg_start,
            background_end=style.background_color_alt or bg_end,
            border=style.border_color or border,
            title=style.title_color or title,
            text=style.text_color or text,
            badge_background=style.badge_background_color or badge_bg,
            badge_text=style.badge_text_color or badge_text,
            close_icon=close_icon,
            shadow=shadow,
        )

    def _sync_visibility(self, *, animate: bool) -> None:
        if not self._requested_visible or not self._can_present():
            self._position_sync_timer.stop()
            self._auto_hide_timer.stop()
            self._fade_in.stop()
            self._fade_out.stop()
            self.hide()
            return

        self.adjustSize()
        self.move(self._calculate_position())

        if not self.isVisible():
            self.setWindowOpacity(0.0 if animate else 1.0)
            self.show()
            self.raise_()
            if animate:
                self._fade_out.stop()
                self._fade_in.stop()
                self._fade_in.start()
        else:
            self.raise_()

        if self._anchor_window() is not None and not self._position_sync_timer.isActive():
            self._position_sync_timer.start()

        if self._config.auto_hide_ms > 0:
            self._auto_hide_timer.start(self._config.auto_hide_ms)
        else:
            self._auto_hide_timer.stop()

    def _can_present(self) -> bool:
        anchor_window = self._anchor_window()
        if anchor_window is None:
            return True
        if not self._anchor_widget.isVisible():
            return False
        if not anchor_window.isVisible() or anchor_window.isMinimized():
            return False
        if self._config.layout.hide_when_anchor_inactive and self._anchor_marked_inactive:
            return False
        return not (self._config.layout.hide_when_anchor_inactive and not self._is_anchor_window_active())

    def _calculate_position(self) -> QPoint:
        screen = None
        rect_top_left = QPoint(0, 0)
        rect_width = 0
        rect_height = 0

        if self._is_valid_widget(self._anchor_widget):
            try:
                rect_top_left = self._anchor_widget.mapToGlobal(QPoint(0, 0))
                rect_width = self._anchor_widget.width()
                rect_height = self._anchor_widget.height()
                screen = QGuiApplication.screenAt(rect_top_left + QPoint(rect_width // 2, rect_height // 2))
            except RuntimeError:
                self._anchor_widget = None

        screen = screen or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if rect_width == 0 or rect_height == 0:
            if available is None:
                return QPoint(0, 0)
            rect_top_left = available.topLeft()
            rect_width = available.width()
            rect_height = available.height()

        layout = self._config.layout
        width = self.width()
        height = self.height()

        if layout.position.endswith("left"):
            x = rect_top_left.x() + layout.margin
        elif layout.position.endswith("center"):
            x = rect_top_left.x() + (rect_width - width) // 2
        else:
            x = rect_top_left.x() + rect_width - width - layout.margin

        if layout.position.startswith("bottom"):
            y = rect_top_left.y() + rect_height - height - layout.margin
        else:
            y = rect_top_left.y() + layout.margin

        x += layout.offset_x
        y += layout.offset_y

        if available is not None:
            x = max(available.left() + 8, min(x, available.right() - width - 8))
            y = max(available.top() + 8, min(y, available.bottom() - height - 8))

        return QPoint(x, y)
