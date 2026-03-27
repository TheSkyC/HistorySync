# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal, Slot

from src.models.app_config import AppConfig
from src.services.browser_monitor import BrowserMonitor
from src.services.extractor_manager import ExtractorManager
from src.services.favicon_manager import FaviconManager
from src.services.local_db import LocalDatabase
from src.services.scheduler import Scheduler, StartupManager
from src.services.webdav_sync import SyncStatus, WebDavSyncService
from src.utils.i18n import _
from src.utils.logger import get_logger
from src.viewmodels.history_viewmodel import HistoryViewModel

log = get_logger("viewmodel.main")


class MainViewModel(QObject):
    sync_started = Signal()
    sync_finished = Signal(int)  # total new records this run
    sync_progress = Signal(str)  # human-readable progress text
    sync_error = Signal(str)

    stats_updated = Signal(int, object)  # total_count, last_sync_time
    browser_status_changed = Signal(dict, dict)
    startup_status_changed = Signal(bool)
    backup_finished = Signal(bool, str)  # success, message

    # Privacy signals
    records_deleted = Signal(int)  # n records deleted
    domain_blacklisted = Signal(str)  # domain just blacklisted
    records_hidden = Signal(list)  # list of hidden IDs

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        db_path = config.get_db_path()
        self._db = LocalDatabase(db_path)
        self._webdav = WebDavSyncService(config.webdav, db_path)
        self._webdav.set_local_db(self._db)
        self._em = ExtractorManager(
            self._db,
            disabled_browsers=config.extractor.disabled_browsers,
            blacklisted_domains=config.privacy.blacklisted_domains,
        )
        self._favicon_manager = FaviconManager(config, parent=self)

        self._scheduler = Scheduler(self._em, self._webdav, parent=self)
        self._scheduler.sync_started.connect(self._on_sync_started)
        self._scheduler.sync_finished.connect(self._on_sync_finished)
        self._scheduler.sync_progress.connect(self._on_sync_progress)
        self._scheduler.sync_error.connect(self._on_sync_error)
        self._scheduler.backup_finished.connect(self._on_backup_finished)

        self._monitor = BrowserMonitor(self._em, self._db, parent=self)
        self._monitor.statuses_changed.connect(self._on_monitor_statuses_changed)

        visible_columns = config.ui.visible_columns if hasattr(config, "ui") else None
        self.history_vm = HistoryViewModel(self._db, self._favicon_manager, visible_columns, parent=self)
        self.history_vm.ui_config_changed.connect(self._on_history_ui_config_changed)

    def start(self) -> None:
        """Start all subsystems.  On first-run, call start_ui() now and
        defer start_scheduler() until after the setup wizard finishes."""
        self.start_ui()
        self.start_scheduler()

    def start_ui(self) -> None:
        """Start UI-facing subsystems (history, monitor, stats) without
        arming the sync/backup scheduler.  Call this on first-run so the
        dashboard is responsive while the wizard is open."""
        from PySide6.QtCore import QTimer

        self.history_vm.set_hidden_ids(self._db.get_hidden_ids())
        QTimer.singleShot(1000, self._monitor.start)
        self._emit_stats()

    def start_scheduler(self) -> None:
        """Arm the sync/backup scheduler.  Safe to call more than once —
        Scheduler.start() stops any running timers before re-configuring."""
        self._scheduler.start(
            self._config.scheduler,
            last_sync_ts=self._config.last_sync_ts,
            last_backup_ts=self._config.last_backup_ts,
        )

    # ── Public sync operations ─────────────────────────────────

    def trigger_sync(self) -> None:
        self._scheduler.trigger_now()

    def trigger_sync_browser(self, browser_type: str) -> None:
        """Trigger a sync for a single browser (from dashboard card context menu)."""
        self._scheduler.trigger_browser(browser_type)

    def trigger_backup(self) -> None:
        self._scheduler.trigger_backup_now()

    def set_auto_sync_enabled(self, enabled: bool) -> None:
        """启用或暂停自动同步（持久化到 config）。"""
        self._config.scheduler.auto_sync_enabled = enabled
        self._scheduler.set_auto_sync_enabled(enabled)
        try:
            self._config.save()
        except Exception as exc:
            log.warning("Failed to save sync enabled state: %s", exc)
        log.info("Auto sync set to: %s", enabled)

    def toggle_browser_sync(self, browser_type: str, enabled: bool) -> None:
        """启用或禁用某个浏览器的同步（修改 disabled_browsers 列表）。"""
        disabled = list(self._config.extractor.disabled_browsers)
        if enabled:
            if browser_type in disabled:
                disabled.remove(browser_type)
        elif browser_type not in disabled:
            disabled.append(browser_type)
        self._config.extractor.disabled_browsers = disabled
        self._em.update_config(disabled, blacklisted_domains=self._config.privacy.blacklisted_domains)
        try:
            self._config.save()
        except Exception as exc:
            log.warning("Failed to save browser sync state: %s", exc)
        log.info("Browser '%s' sync set to: %s", browser_type, "enabled" if enabled else "disabled")

    def reload_extractor_config(self) -> None:
        """向导完成后重新应用 extractor 配置（disabled_browsers 等）。"""
        self._em.update_config(
            self._config.extractor.disabled_browsers,
            blacklisted_domains=self._config.privacy.blacklisted_domains,
        )
        log.info("Extractor config reloaded after wizard")

    def force_redetect_browsers(self) -> None:
        """强制立即重新检测浏览器（由仪表板设置对话框触发）。"""
        self._monitor.force_check()
        log.info("Browser re-detection triggered by user")

    def get_total_count(self) -> int:
        return self._db.get_total_count()

    def get_last_sync_time(self) -> int | None:
        return self._db.get_last_sync_time()

    def get_webdav_status(self) -> str:
        if not self._config.webdav.enabled:
            return _("Not enabled")
        status = self._webdav.status
        mapping = {
            SyncStatus.IDLE: _("Idle"),
            SyncStatus.CONNECTING: _("Connecting..."),
            SyncStatus.UPLOADING: _("Uploading..."),
            SyncStatus.CLEANING: _("Cleaning up..."),
            SyncStatus.SUCCESS: _("Synced"),
            SyncStatus.FAILED: _("Sync error"),
            SyncStatus.DISABLED: _("Not enabled"),
        }
        return mapping.get(status, _("Unknown"))

    def get_available_browsers(self) -> list[str]:
        return self._em.get_available_browsers()

    def is_sync_running(self) -> bool:
        return self._scheduler.is_running

    # ── Privacy operations ─────────────────────────────────────

    def delete_records(self, ids: list[int]) -> int:
        if not ids:
            return 0
        deleted = self._db.delete_records_by_ids(ids)
        self.history_vm.refresh()
        self._emit_stats()
        self.records_deleted.emit(deleted)
        log.info("Deleted %d records (ids: %s...)", deleted, ids[:5])
        return deleted

    def hide_records(self, ids: list[int]) -> None:
        self._db.hide_records_by_ids(ids)
        hidden = self._db.get_hidden_ids()
        self.records_hidden.emit(ids)
        self.history_vm.set_hidden_ids(hidden)
        log.info("Hidden %d records; total hidden: %d", len(ids), len(hidden))

    def blacklist_domain(self, domain: str) -> int:
        if not domain:
            return 0
        if domain not in self._config.privacy.blacklisted_domains:
            self._config.privacy.blacklisted_domains.append(domain)
            self._config.save()
        self._em.set_blacklisted_domains(self._config.privacy.blacklisted_domains)
        deleted = self._db.delete_records_by_domain(domain)
        self.history_vm.refresh()
        self._emit_stats()
        self.domain_blacklisted.emit(domain)
        log.info("Blacklisted '%s', deleted %d records", domain, deleted)
        return deleted

    def get_blacklisted_domains(self) -> list[str]:
        return self._config.privacy.blacklisted_domains

    def get_hidden_ids(self) -> set[int]:
        return self._db.get_hidden_ids()

    # ── Settings ────────────────────────────────────────────────

    def save_config(self, config: AppConfig) -> None:
        self._config = config
        config.save()
        self._scheduler.configure(
            config.scheduler,
            last_sync_ts=config.last_sync_ts,
            last_backup_ts=config.last_backup_ts,
        )
        self._webdav.update_config(config.webdav)
        self._em.update_config(
            config.extractor.disabled_browsers,
            blacklisted_domains=config.privacy.blacklisted_domains,
        )
        self._favicon_manager.update_config(config)
        self._monitor.force_check()
        # Reload hidden IDs from DB (source of truth is now the hidden_records table)
        self.history_vm.set_hidden_ids(self._db.get_hidden_ids())
        log.info("Config saved and applied")

    def set_launch_on_startup(self, enabled: bool) -> bool:
        exe = sys.executable
        ok = StartupManager.enable(exe) if enabled else StartupManager.disable()
        if ok:
            self._config.scheduler.launch_on_startup = enabled
            self._config.save()
            self.startup_status_changed.emit(enabled)
        return ok

    def get_startup_enabled(self) -> bool:
        return StartupManager.is_enabled()

    # ── Internal slots ─────────────────────────────────────────

    @Slot()
    def _on_sync_started(self):
        self.sync_started.emit()
        self.sync_progress.emit(_("Extracting browser history..."))

    @Slot(dict)
    def _on_sync_finished(self, results: dict):
        import time as _time

        total_new = sum(results.values())
        self._monitor.clear_syncing()
        self._config.last_sync_ts = int(_time.time())
        self._config.save()
        self.history_vm.refresh()
        self._emit_stats()
        self.sync_finished.emit(total_new)
        log.info("Sync done, %d new records", total_new)
        synced_browsers = list(results.keys()) if results else None
        self._favicon_manager.schedule_extraction(target_browsers=synced_browsers)

    @Slot(str, str, int)
    def _on_sync_progress(self, browser_type: str, status: str, count: int):
        if status == "extracting":
            self._monitor.set_syncing(browser_type, True)
        elif status in ("done", "error"):
            self._monitor.set_syncing(browser_type, False)
        msg_map = {
            "extracting": _("Reading {browser} history...").format(browser=browser_type),
            "saving": _("Saving {browser} ({count} records)...").format(browser=browser_type, count=count),
            "done": _("{browser} done — {count} new records").format(browser=browser_type, count=count),
            "error": _("{browser} extraction failed").format(browser=browser_type),
        }
        self.sync_progress.emit(msg_map.get(status, status))

    @Slot(str)
    def _on_sync_error(self, msg: str):
        self._monitor.clear_syncing()
        self.sync_error.emit(msg)

    @Slot(bool, str)
    def _on_backup_finished(self, success: bool, msg: str):
        if success:
            import time as _time

            self._config.last_backup_ts = int(_time.time())
            self._config.save()
        self.backup_finished.emit(success, msg)
        log.info("Scheduled backup result: %s — %s", "OK" if success else "FAIL", msg)

    @Slot(dict)
    def _on_monitor_statuses_changed(self, statuses: dict):
        display_names = self._em.get_all_registered()
        self.browser_status_changed.emit(statuses, display_names)

    @Slot(list, dict)
    def _on_history_ui_config_changed(self, visible_columns: list, column_widths: dict):
        self._config.ui.visible_columns = visible_columns
        self._config.ui.column_widths = column_widths
        self.save_config(self._config)

    def _emit_stats(self):
        self.stats_updated.emit(
            self._db.get_total_count(),
            self._db.get_last_sync_time(),
        )
