# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.styled_combobox import StyledComboBox
from src.views.floating_banner import BannerAction, BannerConfig, BannerLayout, BannerStyle, FloatingBanner


class _BannerMenuButton(QWidget):
    clicked = Signal()

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        self._text_label = QLabel(text, self)
        self._text_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._text_label, 0, Qt.AlignVCenter)

        self._icon_label = QLabel(self)
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._icon_label, 0, Qt.AlignVCenter)
        self._set_arrow_color()

    def setText(self, text: str) -> None:
        self._text_label.setText(text)

    def setStyleSheet(self, style: str) -> None:
        super().setStyleSheet(style)
        self._text_label.setStyleSheet("background: transparent;")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _set_arrow_color(self) -> None:
        self._icon_label.setPixmap(get_icon("chevron-down", 12).pixmap(12, 12))


class UpdateBanner(QWidget):
    """Compatibility wrapper that exposes the old update-banner API on top of FloatingBanner."""

    view_details_requested = Signal()
    remind_later_requested = Signal()
    skip_version_requested = Signal()
    open_preferences_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._banner = FloatingBanner(anchor=parent)
        self._banner.action_triggered.connect(self._on_action_triggered)
        self._banner.dismissed.connect(self.dismissed)
        self._pending_action_id = "view_details"
        self._menu_button: _BannerMenuButton | None = None
        self._remind_menu = StyledComboBox()
        self._remind_menu.hide()
        self._remind_menu.addItem(_("Do Not Remind This Week"), "week")
        self._remind_menu.addItem(_("Do Not Remind For This Version"), "skip_version")
        self._remind_menu.addItem(_("Reminder Settings..."), "preferences")
        self._remind_menu.itemActivated.connect(self._on_remind_menu_activated)

    def set_anchor_widget(self, anchor: QWidget | None) -> None:
        self._banner.set_anchor_widget(anchor)

    def show_banner(self, config: BannerConfig) -> None:
        self._pending_action_id = config.actions[0].action_id if config.actions else ""
        self._menu_button = None
        self._banner.show_banner(config)
        self._install_menu_button_if_needed()

    def hide_banner(self) -> None:
        self._banner.hide_banner()

    def dismiss_banner(self) -> None:
        self._banner.dismiss_banner()

    def show_update_available(self, version: str) -> None:
        self.show_banner(
            BannerConfig(
                title=_("Update Available"),
                message=_("HistorySync {version} is available. You are currently running {current}.").format(
                    version=version,
                    current=self._current_version(),
                ),
                badge_text=_("New Version"),
                icon_name="arrow-up",
                actions=(
                    BannerAction("view_details", _("View Details"), kind="primary", auto_dismiss=True),
                    BannerAction("remind_later", _("Remind Later"), kind="ghost"),
                ),
                style=BannerStyle(tone="info", border_radius=20, padding=14),
                layout=BannerLayout(
                    position="top-right", width=380, min_width=340, max_width=460, margin=14, show_close=True
                ),
                auto_hide_ms=15000,
            )
        )

    def show_update_ready(self, version: str) -> None:
        self.show_banner(
            BannerConfig(
                title=_("Ready To Install"),
                message=_("HistorySync {version} has been downloaded and is ready to install.").format(version=version),
                badge_text=_("Downloaded"),
                icon_name="download",
                actions=(
                    BannerAction("view_details", _("Install Now"), kind="primary", auto_dismiss=True),
                    BannerAction("remind_later", _("Remind Later"), kind="ghost"),
                ),
                style=BannerStyle(tone="success", border_radius=20, padding=14),
                layout=BannerLayout(
                    position="top-right", width=380, min_width=340, max_width=460, margin=14, show_close=True
                ),
                auto_hide_ms=20000,
            )
        )

    def show_checking(self) -> None:
        self.show_banner(
            BannerConfig(
                title=_("Checking For Updates"),
                message=_("Looking for the latest release information..."),
                badge_text=_("Please Wait"),
                icon_name="refresh",
                actions=(BannerAction("checking", _("Checking..."), kind="secondary", enabled=False),),
                style=BannerStyle(tone="neutral", border_radius=20, padding=14),
                layout=BannerLayout(
                    position="top-right", width=360, min_width=320, max_width=420, margin=14, show_close=True
                ),
                auto_hide_ms=0,
            )
        )

    def _on_action_triggered(self, action_id: str) -> None:
        if action_id == "remind_later":
            self._show_remind_menu()
            return
        if action_id == self._pending_action_id:
            self.view_details_requested.emit()

    def request_skip_version(self) -> None:
        self.skip_version_requested.emit()

    def request_open_preferences(self) -> None:
        self.open_preferences_requested.emit()

    def _install_menu_button_if_needed(self) -> None:
        action_button = self._banner.button_for_action("remind_later")
        if action_button is None:
            self._menu_button = None
            return
        parent = action_button.parentWidget()
        layout = parent.layout() if parent is not None else None
        if parent is None or layout is None:
            return

        menu_button = _BannerMenuButton(action_button.text(), parent)
        menu_button.setStyleSheet(action_button.styleSheet())
        menu_button.setMinimumHeight(action_button.minimumHeight())
        menu_button.setMinimumWidth(max(action_button.minimumWidth(), action_button.sizeHint().width() + 18))
        menu_button.clicked.connect(self._show_remind_menu)

        for index in range(layout.count()):
            if layout.itemAt(index).widget() is action_button:
                layout.insertWidget(index, menu_button, 0)
                layout.removeWidget(action_button)
                action_button.hide()
                action_button.deleteLater()
                self._menu_button = menu_button
                return

    def _show_remind_menu(self) -> None:
        if self._menu_button is None:
            self.remind_later_requested.emit()
            return
        menu_width = max(self._menu_button.width() + 54, 220)
        global_pos = self._menu_button.mapToGlobal(QPoint(0, self._menu_button.height() + 6))
        self._remind_menu.showPopupAt(global_pos, menu_width)

    def _on_remind_menu_activated(self, index: int) -> None:
        action = self._remind_menu.itemData(index)
        if action == "week":
            self.remind_later_requested.emit()
            self.dismiss_banner()
            return
        if action == "skip_version":
            self.request_skip_version()
            self.dismiss_banner()
            return
        if action == "preferences":
            self.request_open_preferences()
            self.dismiss_banner()

    @staticmethod
    def _current_version() -> str:
        from src.services.update_debug import effective_current_version

        return effective_current_version()
