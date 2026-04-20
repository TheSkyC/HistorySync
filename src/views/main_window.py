# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import APP_NAME
from src.utils.i18n import _
from src.utils.icon_helper import get_app_icon
from src.utils.logger import get_logger
from src.utils.path_helper import get_log_dir
from src.utils.theme_manager import ThemeManager
from src.viewmodels.main_viewmodel import MainViewModel
from src.viewmodels.settings_viewmodel import SettingsViewModel
from src.views.dashboard_page import DashboardPage
from src.views.nav_widgets import NavButton, ThemeButton

log = get_logger("view.main_window")

PAGE_DASHBOARD = 0
PAGE_HISTORY = 1
PAGE_BOOKMARKS = 2
PAGE_SETTINGS = 3
PAGE_LOGS = 4
PAGE_STATS = 5


class MainWindow(QMainWindow):
    close_to_tray = Signal()

    def __init__(self, main_vm: MainViewModel):
        super().__init__()
        self._vm = main_vm
        self._settings_vm = SettingsViewModel(main_vm, parent=self)
        self._history_initialized = False

        if getattr(main_vm._config, "_fresh", False):
            self.setWindowTitle(f"{APP_NAME}  {_('[Fresh Mode]')}")
        else:
            self.setWindowTitle(APP_NAME)
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(900, 600)
        self.resize(main_vm._config.window_width, main_vm._config.window_height)
        if main_vm._config.window_x >= 0 and main_vm._config.window_y >= 0:
            self.move(main_vm._config.window_x, main_vm._config.window_y)

        self._init_ui()
        self._connect_vm()
        self._setup_global_shortcuts()

        self._theme_btn.set_theme(main_vm._config.theme)

    # ── UI construction ───────────────────────────────────────

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_sidebar())
        main_layout.addWidget(self._build_page_stack(), 1)

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(_("Ready"))

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("muted")
        self._status_bar.addPermanentWidget(self._progress_label)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(56)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)
        sb_layout.setAlignment(Qt.AlignTop)

        # Nav buttons
        self._nav_dashboard = NavButton("home", _("Overview"))
        self._nav_history = NavButton("list", _("History"))
        self._nav_bookmarks = NavButton("bookmark", _("Bookmarks"))
        self._nav_settings = NavButton("settings", _("Settings"))
        self._nav_logs = NavButton("file-text", _("Log Viewer"))
        self._nav_stats = NavButton("bar-chart-2", _("Statistics"))
        self._nav_buttons = [
            self._nav_dashboard,
            self._nav_history,
            self._nav_bookmarks,
            self._nav_settings,
            self._nav_logs,
            self._nav_stats,
        ]
        for btn in self._nav_buttons:
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Theme toggle
        self._theme_btn = ThemeButton()
        self._theme_btn.theme_cycle_requested.connect(self._on_theme_selected)
        sb_layout.addWidget(self._theme_btn, alignment=Qt.AlignHCenter)
        sb_layout.addSpacing(8)

        return sidebar

    def _build_page_stack(self) -> QStackedWidget:
        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")

        # Only the first-visible page is built eagerly; the rest use cheap
        # placeholder QWidgets so Qt has no widget tree to polish at show().
        self._page_dashboard = DashboardPage()
        self._stack.addWidget(self._page_dashboard)  # index 0

        # Placeholders occupy the correct stack indices until first access.
        for _ in range(5):
            self._stack.addWidget(QWidget())  # indices 1, 2, 3, 4, 5

        # Lazy page references — None until the user navigates there.
        self._page_history = None
        self._page_bookmarks = None
        self._page_settings = None
        self._page_logs = None
        self._page_stats = None

        self._nav_dashboard.clicked.connect(lambda: self._switch_page(PAGE_DASHBOARD))
        self._nav_history.clicked.connect(lambda: self._switch_page(PAGE_HISTORY))
        self._nav_bookmarks.clicked.connect(lambda: self._switch_page(PAGE_BOOKMARKS))
        self._nav_settings.clicked.connect(lambda: self._switch_page(PAGE_SETTINGS))
        self._nav_logs.clicked.connect(lambda: self._switch_page(PAGE_LOGS))
        self._nav_stats.clicked.connect(lambda: self._switch_page(PAGE_STATS))
        self._switch_page(PAGE_DASHBOARD)

        return self._stack

    # ── Lazy page construction ─────────────────────────────────

    def _replace_placeholder(self, index: int, new_widget: QWidget) -> None:
        """Swap the placeholder at *index* for the real page widget."""
        old = self._stack.widget(index)
        self._stack.removeWidget(old)
        self._stack.insertWidget(index, new_widget)
        old.deleteLater()

    def _setup_global_shortcuts(self):
        kb = self._vm._config.keybindings.app
        self._shortcuts: dict[str, QShortcut] = {}

        def _bind(action: str, slot):
            seq = kb.get(action, "")
            if seq:
                sc = QShortcut(QKeySequence(seq), self)
                sc.activated.connect(slot)
                self._shortcuts[action] = sc

        _bind("trigger_sync", self._vm.trigger_sync)
        _bind("goto_dashboard", lambda: self._switch_page(PAGE_DASHBOARD))
        _bind("goto_history", lambda: self._switch_page(PAGE_HISTORY))
        _bind("goto_bookmarks", lambda: self._switch_page(PAGE_BOOKMARKS))
        _bind("goto_settings", lambda: self._switch_page(PAGE_SETTINGS))
        _bind("goto_logs", lambda: self._switch_page(PAGE_LOGS))
        _bind("goto_stats", lambda: self._switch_page(PAGE_STATS))
        _bind("focus_search", self._focus_history_search)

    def apply_keybindings(self) -> None:
        """Re-apply keyboard shortcuts from config (called after settings save)."""
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
        self._setup_global_shortcuts()
        if self._page_history is not None:
            self._page_history.apply_keybindings()

    def _connect_vm(self):
        vm = self._vm
        vm.sync_started.connect(self._on_sync_started)
        vm.sync_finished.connect(self._on_sync_finished)
        vm.sync_progress.connect(self._on_sync_progress)
        vm.sync_error.connect(self._on_sync_error)
        vm.stats_updated.connect(self._on_stats_updated)
        vm.browser_status_changed.connect(self._on_browser_status_changed)
        vm.records_deleted.connect(self._on_records_deleted)
        vm.domain_blacklisted.connect(self._on_domain_blacklisted)
        # backup_finished → settings page is guarded in _on_backup_finished
        vm.backup_finished.connect(self._on_backup_finished)
        vm.open_settings_requested.connect(lambda: (self.show_and_raise(), self._switch_page(PAGE_SETTINGS)))

        # DashboardPage is always eager — connect directly.
        self._page_dashboard.sync_requested.connect(vm.trigger_sync)
        self._page_dashboard.sync_browser_requested.connect(vm.trigger_sync_browser)
        self._page_dashboard.browser_sync_toggle_requested.connect(vm.toggle_browser_sync)
        self._page_dashboard.redetect_browsers_requested.connect(vm.force_redetect_browsers)
        self._page_dashboard.learned_browsers_added.connect(vm.on_learned_browsers_added)
        self._page_dashboard.browser_remove_requested.connect(vm.on_browser_remove)
        self._page_dashboard.view_history_requested.connect(self._on_view_browser_history)
        # HistoryPage / SettingsPage / LogViewerPage signals are wired up in
        # _switch_page() the first time those pages are created.

        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ── Theme ─────────────────────────────────────────────────

    def _on_theme_selected(self, new_theme: str):
        self._theme_btn.set_theme(new_theme)
        ThemeManager.instance().apply(QApplication.instance(), new_theme)
        self._vm._config.theme = new_theme
        try:
            self._vm._config.save()
        except Exception as exc:
            log.warning("Failed to save theme: %s", exc)

    def _on_theme_changed(self, _resolved_theme: str):
        for btn in self._nav_buttons:
            btn.refresh_icon()
        self._theme_btn.refresh_icon()

    # ── Page switching ────────────────────────────────────────

    def _switch_page(self, index: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

        # ── Lazy page construction ─────────────────────────────
        if index == PAGE_HISTORY and self._page_history is None:
            from src.views.history_page import HistoryPage

            self._page_history = HistoryPage(self._vm.history_vm, self._vm._config)
            self._replace_placeholder(PAGE_HISTORY, self._page_history)
            # Wire up signals now that the page exists.
            self._page_history.delete_records_requested.connect(self._on_delete_records)
            self._page_history.hide_records_requested.connect(self._on_hide_records)
            self._page_history.hide_domain_requested.connect(self._on_hide_domain)
            self._page_history.blacklist_domain_requested.connect(self._on_blacklist_domain)
            self._page_history.unhide_records_requested.connect(self._on_unhide_records)
            self._page_history.bookmark_changed.connect(self._on_bookmark_changed)

        elif index == PAGE_BOOKMARKS and self._page_bookmarks is None:
            from src.views.bookmarks_page import BookmarksPage

            self._page_bookmarks = BookmarksPage(self._vm._db)
            self._replace_placeholder(PAGE_BOOKMARKS, self._page_bookmarks)
            self._page_bookmarks.navigate_to_history.connect(self._navigate_to_history_url)
            self._page_bookmarks.navigate_to_history_hidden.connect(self._on_bookmarks_locate_hidden)
            self._page_bookmarks.bookmark_changed.connect(self._on_bookmark_changed)

        elif index == PAGE_SETTINGS and self._page_settings is None:
            from src.views.settings_page import SettingsPage

            self._page_settings = SettingsPage(self._settings_vm)
            self._replace_placeholder(PAGE_SETTINGS, self._page_settings)
            self._page_settings.saved.connect(self._on_settings_saved)

        elif index == PAGE_LOGS and self._page_logs is None:
            from src.views.log_viewer_page import LogViewerPage

            self._page_logs = LogViewerPage(get_log_dir())
            self._replace_placeholder(PAGE_LOGS, self._page_logs)

        elif index == PAGE_STATS and self._page_stats is None:
            from src.views.stats_page import StatsPage

            self._page_stats = StatsPage(self._vm._db, favicon_manager=self._vm._favicon_manager)
            self._replace_placeholder(PAGE_STATS, self._page_stats)
            self._page_stats.navigate_to_date.connect(self._navigate_to_history_date)

        self._stack.setCurrentIndex(index)

        if index == PAGE_HISTORY and not self._history_initialized:
            self._history_initialized = True
            QTimer.singleShot(0, self._vm.history_vm.initialize)

        # ── Hidden-mode sync ───────────────────────────────────
        # When navigating away from history, bookmarks page inherits the current
        # hidden-mode state so both pages stay consistent.
        if index == PAGE_BOOKMARKS and self._page_bookmarks is not None and self._page_history is not None:
            self._page_bookmarks.set_hidden_mode(self._page_history.hidden_mode)

        # Leaving the bookmarks page back to history resets bookmarks to normal
        # mode — the user controls hidden mode via the history page's toggle only.
        if index == PAGE_HISTORY and self._page_bookmarks is not None:
            self._page_bookmarks.leave_hidden_mode()

    def _focus_history_search(self):
        self._switch_page(PAGE_HISTORY)  # creates page if needed
        self._page_history._focus_search()

    def _navigate_to_history_date(self, date_str: str):
        """Switch to history page and filter by the given date (from stats heatmap)."""
        self._switch_page(PAGE_HISTORY)
        self._page_history.filter_by_date(date_str)

    def _navigate_to_history_url(self, url: str):
        """Switch to history page and filter by the given URL (from bookmarks 'Locate in History')."""
        self._switch_page(PAGE_HISTORY)  # creates page if needed
        self._page_history.filter_by_url(url)

    def _on_bookmarks_locate_hidden(self):
        """Called when 'Locate in History' is triggered from the bookmarks hidden-mode view.

        Ensures the history page is in hidden mode before filtering so the
        record is actually visible (it would be hidden in normal mode).
        """
        if self._page_history is not None and not self._page_history.hidden_mode:
            self._page_history.set_hidden_mode(True)

    # ── VM signal handlers ────────────────────────────────────

    def _on_sync_started(self):
        self._page_dashboard.on_sync_started()
        self._status_bar.showMessage(_("Syncing browser history…"))
        self._progress_label.setText(_("Starting…"))

    def _on_sync_progress(self, msg: str):
        # Dashboard no longer has a progress widget — show detail only in status bar
        self._status_bar.showMessage(msg)
        self._progress_label.setText(msg)

    def _on_sync_finished(self, new_count: int):
        import time as _time

        self._page_dashboard.on_sync_finished(new_count)
        if self._page_history is not None:
            self._page_history.refresh()
        self._status_bar.showMessage(_("Sync complete — {count} new records added").format(count=new_count), 6000)
        self._progress_label.setText("")
        if self._page_settings is not None:
            self._page_settings.notify_sync_happened(int(_time.time()))

    def _on_backup_finished(self, ok: bool, _msg: str):
        if self._page_settings is not None:
            self._page_settings.notify_backup_happened(ok)

    def _on_sync_error(self, msg: str):
        self._page_dashboard.on_sync_error(msg)
        self._status_bar.showMessage(_("Sync failed: {error}").format(error=msg), 8000)
        self._progress_label.setText("")

    def _on_stats_updated(self, total: int, last_sync):
        self._page_dashboard.update_stats(
            total_count=total,
            last_sync_time=last_sync,
            webdav_status=self._vm.get_webdav_status(),
        )

    def _on_browser_status_changed(self, statuses: dict, display_names: dict):
        if not self.isVisible():
            return
        self._page_dashboard.update_browser_statuses(
            statuses,
            display_names,
            disabled_browsers=self._vm._config.extractor.disabled_browsers,
        )

    def _on_settings_saved(self):
        self._status_bar.showMessage(_("Settings saved"), 3000)
        self._vm.history_vm.set_hidden_ids(self._vm.get_hidden_ids())

    def _on_view_browser_history(self, browser_type: str):
        self._switch_page(PAGE_HISTORY)  # creates page if needed
        self._page_history.filter_by_browser(browser_type)

    def _on_delete_records(self, ids: list[int]):
        n = self._vm.delete_records(ids)
        self._status_bar.showMessage(_("Deleted {n} record(s)").format(n=n), 4000)

    def _on_hide_records(self, ids: list[int]):
        self._vm.hide_records(ids)
        self._status_bar.showMessage(
            _("Hidden {n} record(s). Unhide anytime in Settings → Privacy.").format(n=len(ids)), 5000
        )

    def _on_unhide_records(self, ids: list[int]):
        self._vm.unhide_records(ids)
        self._status_bar.showMessage(_("Restored {n} record(s).").format(n=len(ids)), 5000)

    def _on_hide_domain(self, domain: str, subdomain_only: bool, auto_hide: bool) -> None:
        """Handle hide_domain_requested from history page."""
        hidden_count = self._vm.hide_domain(domain, subdomain_only, auto_hide)
        if auto_hide:
            msg = _("'{domain}' hidden ({n} record(s) affected). Manage hidden domains in Settings → Privacy.").format(
                domain=domain, n=hidden_count
            )
        else:
            msg = _("Hidden {n} record(s) from '{domain}'.").format(domain=domain, n=hidden_count)
        self._status_bar.showMessage(msg, 6000)

    def _on_blacklist_domain(self, domain: str):
        deleted = self._vm.blacklist_domain(domain)
        self._status_bar.showMessage(
            _("'{domain}' blacklisted — {n} record(s) deleted").format(domain=domain, n=deleted), 6000
        )
        if self._page_settings is not None:
            self._page_settings.add_blacklist_domain(domain)

    def _on_records_deleted(self, n: int):
        log.info("Deleted %d records via privacy action", n)

    def _on_domain_blacklisted(self, domain: str):
        log.info("Domain blacklisted: %s", domain)

    def _on_bookmark_changed(self):
        """Refresh history badge cache and bookmarks page when bookmarks are modified."""
        if self._page_history is not None:
            self._page_history._vm.table_model.invalidate_badge_cache(self._page_history._table)
            self._page_history._vm._refresh_tag_list()
        if self._page_bookmarks is not None:
            self._page_bookmarks.refresh()

    # ── Window events ─────────────────────────────────────────

    def show_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._vm.force_monitor_check()

    def showEvent(self, event: QShowEvent):
        """Flush deferred post-sync state the first time the window becomes visible.

        Covers both the normal (non-minimised) startup path where main.py
        calls window.show() directly, and the minimised path where the user
        later opens the window via the system tray.  Subsequent show events
        (e.g. un-minimising) are no-ops because notify_window_shown() guards
        itself with _window_ever_shown.
        """
        super().showEvent(event)
        self._vm.notify_window_shown()

    def closeEvent(self, event: QCloseEvent):
        self._save_geometry()
        # Auto-exit hidden-records mode so next open shows normal history/bookmarks
        if self._page_history is not None:
            self._page_history.leave_hidden_mode()
        if self._page_bookmarks is not None:
            self._page_bookmarks.leave_hidden_mode()
        event.ignore()
        self.hide()
        self.close_to_tray.emit()

    def _save_geometry(self):
        cfg = self._vm._config
        cfg.window_width = self.width()
        cfg.window_height = self.height()
        cfg.window_x = self.x()
        cfg.window_y = self.y()
        try:
            cfg.save()
        except Exception:
            pass

    @property
    def page_settings(self):
        return self._page_settings
