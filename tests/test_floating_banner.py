# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QWidget

from src.views.floating_banner import BannerAction, BannerConfig, BannerLayout, BannerStyle, FloatingBanner
from src.views.settings.update_section import UpdatePreferencesDialog
from src.views.update_banner import UpdateBanner


def _flush_events() -> None:
    app = QApplication.instance()
    assert app is not None
    app.processEvents()


def test_floating_banner_respects_custom_config(qapp):
    anchor = QWidget()
    anchor.resize(900, 600)
    anchor.move(120, 80)
    anchor.show()
    _flush_events()

    banner = FloatingBanner(anchor=anchor)
    triggered: list[str] = []
    dismissed: list[bool] = []
    banner.action_triggered.connect(triggered.append)
    banner.dismissed.connect(lambda: dismissed.append(True))

    config = BannerConfig(
        title="Backup completed",
        message="The latest snapshot has been uploaded successfully.",
        badge_text="Success",
        icon_name="check-circle",
        actions=(
            BannerAction("open_logs", "Open Logs", kind="secondary"),
            BannerAction("done", "Done", kind="primary", auto_dismiss=True),
        ),
        style=BannerStyle(
            tone="success",
            accent_color="#22c55e",
            border_radius=26,
            padding=22,
        ),
        layout=BannerLayout(
            position="bottom-center",
            width=480,
            min_width=360,
            max_width=520,
            margin=24,
            offset_y=-10,
            actions_alignment="left",
        ),
        auto_hide_ms=2500,
    )

    banner.show_banner(config)
    _flush_events()

    assert banner.isVisible()
    assert banner.current_config().layout.position == "bottom-center"
    assert banner.current_config().style.accent_color == "#22c55e"
    assert banner.current_config().auto_hide_ms == 2500
    assert banner.button_for_action("open_logs") is not None
    assert banner.button_for_action("done") is not None
    assert banner.pos().y() > anchor.mapToGlobal(QPoint(0, 0)).y()
    assert banner._auto_hide_timer.isActive() is True
    assert banner._position_sync_timer.isActive() is True

    banner.button_for_action("open_logs").click()
    _flush_events()
    assert triggered == ["open_logs"]
    assert banner.isVisible()

    old_pos = banner.pos()
    anchor.move(200, 140)
    _flush_events()
    _flush_events()
    assert banner.pos() != old_pos

    banner.button_for_action("done").click()
    _flush_events()
    assert triggered == ["open_logs", "done"]
    assert banner._requested_visible is False

    banner._on_fade_out_finished()
    _flush_events()
    assert dismissed == [True]
    assert banner._position_sync_timer.isActive() is False


def test_update_banner_compatibility_wrapper_emits_view_details(qapp, monkeypatch):
    monkeypatch.setattr("src.views.update_banner.UpdateBanner._current_version", staticmethod(lambda: "1.0.0"))

    anchor = QWidget()
    anchor.resize(800, 480)
    anchor.show()
    _flush_events()

    banner = UpdateBanner(anchor)
    banner.set_anchor_widget(anchor)
    requested: list[bool] = []
    dismissed: list[bool] = []
    banner.view_details_requested.connect(lambda: requested.append(True))
    banner.dismissed.connect(lambda: dismissed.append(True))

    banner.show_update_available("1.2.3")
    _flush_events()

    assert banner._banner.isVisible()
    assert banner._banner.current_config().title == "Update Available"
    assert "1.2.3" in banner._banner.current_config().message
    assert "1.0.0" in banner._banner.current_config().message

    primary = banner._banner.button_for_action("view_details")
    assert primary is not None
    primary.click()
    _flush_events()
    assert requested == [True]
    assert banner._banner._requested_visible is False

    later = banner._banner.button_for_action("remind_later")
    assert later is not None
    assert banner._menu_button is not None
    banner.show_update_available("1.2.3")
    _flush_events()
    assert banner._menu_button is not None
    banner._menu_button.clicked.emit()
    _flush_events()
    banner._on_remind_menu_activated(0)
    _flush_events()
    banner._banner._on_fade_out_finished()
    _flush_events()
    assert dismissed == [True]


def test_update_banner_remind_menu_emits_actions(qapp):
    anchor = QWidget()
    anchor.resize(800, 480)
    anchor.show()
    _flush_events()

    banner = UpdateBanner(anchor)
    banner.set_anchor_widget(anchor)
    reminded: list[bool] = []
    skipped: list[bool] = []
    opened: list[bool] = []
    banner.remind_later_requested.connect(lambda: reminded.append(True))
    banner.skip_version_requested.connect(lambda: skipped.append(True))
    banner.open_preferences_requested.connect(lambda: opened.append(True))

    banner.show_update_available("1.2.3")
    _flush_events()

    assert banner._menu_button is not None
    banner._on_remind_menu_activated(0)
    banner._on_remind_menu_activated(1)
    banner._on_remind_menu_activated(2)

    assert reminded == [True]
    assert skipped == [True]
    assert opened == [True]


def test_update_banner_checking_state_disables_action(qapp):
    anchor = QWidget()
    anchor.resize(640, 360)
    anchor.show()
    _flush_events()

    banner = UpdateBanner(anchor)
    banner.set_anchor_widget(anchor)
    banner.show_checking()
    _flush_events()

    checking = banner._banner.button_for_action("checking")
    assert checking is not None
    assert checking.isEnabled() is False
    assert banner._banner.current_config().layout.position == "top-right"
    assert banner._banner.current_config().style.tone == "neutral"


def test_floating_banner_hides_when_anchor_window_inactive(qapp):
    anchor = QWidget()
    anchor.resize(640, 360)
    anchor.show()
    _flush_events()

    banner = FloatingBanner(anchor=anchor)
    banner.show_banner(
        BannerConfig(
            title="Info",
            message="A banner tied to the active main window.",
            layout=BannerLayout(position="top-right", hide_when_anchor_inactive=True),
        )
    )
    _flush_events()
    assert banner.isVisible()

    banner.eventFilter(anchor.window(), QEvent(QEvent.WindowDeactivate))
    _flush_events()
    assert banner.isVisible() is False


def test_floating_banner_has_soft_shadow_and_no_focus_buttons(qapp):
    anchor = QWidget()
    anchor.resize(640, 360)
    anchor.show()
    _flush_events()

    banner = FloatingBanner(anchor=anchor)
    banner.show_banner(BannerConfig(title="Soft", message="Low contrast shadow."))
    _flush_events()

    assert banner._shadow.blurRadius() == 16
    assert banner._shadow.offset().y() == 3
    assert banner.focusPolicy() == Qt.NoFocus
    assert banner._card.focusPolicy() == Qt.NoFocus
    assert banner._close_btn.focusPolicy() == Qt.NoFocus
    assert banner.button_for_action("missing") is None


def test_update_preferences_dialog_exposes_reminder_controls(qapp):
    class _Updater:
        auto_check_enabled = True
        policy = "notify_download"
        prefer_mirror = "auto"
        channel = "stable"
        reminder_frequency = "weekly"
        skipped_version = "1.2.3"

    dlg = UpdatePreferencesDialog()
    dlg.load(_Updater())

    assert dlg.get_reminder_frequency() == "weekly"
    assert dlg.should_reset_skip_version() is False
    assert dlg._reset_skip_btn.isEnabled() is True

    dlg._reset_skip_version()
    assert dlg.should_reset_skip_version() is True
