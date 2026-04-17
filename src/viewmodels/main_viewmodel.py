# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal, Slot

from src.models.app_config import AppConfig
from src.services.browser_monitor import BrowserMonitor
from src.services.device_manager import ensure_local_device
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
    domain_hidden = Signal(str)  # domain just added to hidden_domains
    records_hidden = Signal(list)  # list of hidden IDs

    # Overlay signal
    open_settings_requested = Signal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._overlay = None  # OverlayWindow, created lazily on first hotkey press

        db_path = config.get_db_path()
        self._db = LocalDatabase(db_path)
        self._local_device_id: int = ensure_local_device(config, self._db)
        self._webdav = WebDavSyncService(config.webdav, db_path)
        self._webdav.set_local_db(self._db)
        self._webdav.set_device_id(self._local_device_id)
        self._em = ExtractorManager(
            self._db,
            disabled_browsers=config.extractor.disabled_browsers,
            blacklisted_domains=config.privacy.blacklisted_domains,
            filtered_url_prefixes=config.privacy.filtered_url_prefixes,
            device_id=self._local_device_id,
        )
        self._favicon_manager = FaviconManager(config, parent=self)
        # Provide the history DB reference so FaviconManager can scope
        # extraction to domains the user has actually visited.
        self._favicon_manager.set_local_db(self._db)

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

        self._refresh_hidden_ids()
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

    def ensure_overlay(self):
        """Return the OverlayWindow, creating it on first call (lazy init).

        Safe to call from the hotkey handler before the window has been
        pre-warmed — first invocation takes ~100ms, subsequent ones are instant.
        Returns None if the overlay feature is disabled.
        """
        if not self._config.overlay.enabled:
            return None
        if self._overlay is None:
            from src.views.overlay_window import OverlayWindow

            self._overlay = OverlayWindow(self._db, self._config, favicon_cache=self._favicon_manager.favicon_cache)
            self._overlay.open_settings_requested.connect(self.open_settings_requested)
        return self._overlay

    # ── Public sync operations ─────────────────────────────────

    def trigger_sync(self) -> None:
        self._scheduler.trigger_now()

    def trigger_sync_browser(self, browser_type: str) -> None:
        """Trigger a sync for a single browser (from dashboard card context menu)."""
        self._scheduler.trigger_browser(browser_type)

    def trigger_full_resync(self, browser_types: list[str] | None = None) -> None:
        """Trigger a full re-extraction, back-filling all historical records.

        This ignores the incremental watermark so that fields added in newer
        versions (e.g. ``visit_count``, ``typed_count``) are populated for
        records that were synced before those fields existed.

        Parameters
        ----------
        browser_types:
            Limit to specific browsers.  ``None`` re-syncs all available browsers.
        """
        self._scheduler.trigger_full_resync(browser_types=browser_types)

    def trigger_backup(self) -> None:
        self._scheduler.trigger_backup_now()

    def set_auto_sync_enabled(self, enabled: bool) -> None:
        """Enable or disable auto-sync and persist to config."""
        self._config.scheduler.auto_sync_enabled = enabled
        self._scheduler.set_auto_sync_enabled(enabled)
        try:
            self._config.save()
        except Exception as exc:
            log.warning("Failed to save sync enabled state: %s", exc)
        log.info("Auto sync set to: %s", enabled)

    def toggle_browser_sync(self, browser_type: str, enabled: bool) -> None:
        """Enable or disable sync for a specific browser by modifying disabled_browsers list."""
        disabled = list(self._config.extractor.disabled_browsers)
        if enabled:
            if browser_type in disabled:
                disabled.remove(browser_type)
        elif browser_type not in disabled:
            disabled.append(browser_type)
        self._config.extractor.disabled_browsers = disabled
        self._em.update_config(
            disabled,
            blacklisted_domains=self._config.privacy.blacklisted_domains,
            filtered_url_prefixes=self._config.privacy.filtered_url_prefixes,
        )
        try:
            self._config.save()
        except Exception as exc:
            log.warning("Failed to save browser sync state: %s", exc)
        log.info("Browser '%s' sync set to: %s", browser_type, "enabled" if enabled else "disabled")
        self._monitor.force_check()

    def reload_extractor_config(self) -> None:
        """Reapply extractor config (disabled_browsers, etc.) after wizard completion."""
        self._em.update_config(
            self._config.extractor.disabled_browsers,
            blacklisted_domains=self._config.privacy.blacklisted_domains,
            filtered_url_prefixes=self._config.privacy.filtered_url_prefixes,
        )
        log.info("Extractor config reloaded after wizard")

    def force_redetect_browsers(self) -> None:
        """Force immediate browser re-detection (triggered by dashboard settings dialog)."""
        self._monitor.force_check()
        log.info("Browser re-detection triggered by user")

    def on_learned_browsers_added(self, browsers: list) -> None:
        """Inject newly discovered browsers into runtime after deep scan completion.

        Process:
        1. Write to in-memory config and call config.save() to persist
        2. Register to global BROWSER_DEF_MAP (ensures next deep scan correctly filters added browsers)
        3. Register extractors to ExtractorManager._registry
        4. Trigger BrowserMonitor to refresh dashboard cards
        """
        from datetime import datetime

        from src.services.browser_defs import create_learned_browser_def, register_learned_browser

        new_entries: dict = {}
        for browser in browsers:
            entry = {
                "display_name": browser.display_name,
                "engine": browser.engine,
                "data_dir": str(browser.data_dir),
                "discovered_at": datetime.now().isoformat(),
                "profiles": browser.profiles,
            }
            new_entries[browser.browser_type] = entry
            # Write to in-memory config
            self._config.extractor.learned_browsers[browser.browser_type] = entry

            # Register to global BROWSER_DEF_MAP
            browser_def = create_learned_browser_def(
                browser_type=browser.browser_type,
                display_name=browser.display_name,
                engine=browser.engine,
                data_dir=browser.data_dir,
            )
            register_learned_browser(browser_def)

        self._config.save()

        self._em.register_new_learned(new_entries)
        self._monitor.force_check()
        log.info("Learned browsers added at runtime: %s", list(new_entries.keys()))

    def on_browser_remove(self, browser_type: str, clear_data: bool) -> None:
        """Handle user request to remove a learned browser from dashboard context menu.

        Process:
        1. Remove from in-memory config (View layer already called config.save())
        2. Unregister extractor from ExtractorManager (if supported)
        3. If clear_data=True, delete all history records for this browser from local DB
        4. Trigger BrowserMonitor to refresh dashboard cards
        """
        # Sync in-memory config (View layer already called config.save())
        self._config.extractor.learned_browsers.pop(browser_type, None)
        if browser_type in self._config.extractor.disabled_browsers:
            self._config.extractor.disabled_browsers.remove(browser_type)

        # Unregister from ExtractorManager (if interface exists)
        if hasattr(self._em, "unregister_browser"):
            self._em.unregister_browser(browser_type)

        # Optional: clear history records from database
        if clear_data:
            try:
                deleted = self._db.delete_records_by_browser(browser_type)
                log.info("Deleted %d history records for removed browser %s", deleted, browser_type)
            except Exception as exc:
                log.warning("Could not delete history for %s: %s", browser_type, exc)

        # Refresh dashboard cards
        self._monitor.force_check()
        log.info("Browser removed from config: %s (clear_data=%s)", browser_type, clear_data)

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
        self._refresh_hidden_ids()
        self.records_hidden.emit(ids)
        log.info("Hidden %d records by ID", len(ids))

    def unhide_records(self, ids: list[int]) -> None:
        """Remove hidden_records entries for the given record IDs and refresh."""
        self._db.unhide_records_by_ids(ids)
        self._refresh_hidden_ids()
        log.info("Unhidden %d records by ID", len(ids))

    def _refresh_hidden_ids(self) -> None:
        """Recompute the combined hidden-ID set (URL-level U domain-level) and
        push it to the history view-model so the table re-filters immediately."""
        self.history_vm.set_hidden_ids(self._db.get_all_hidden_ids())

    # ── Hidden-domain operations ─────────────────────────────

    def hide_domain(self, domain: str, subdomain_only: bool, auto_hide: bool) -> int:
        """Hide all records for *domain*.

        If *auto_hide* is True the domain is persisted to ``hidden_domains``
        so that records arriving in future syncs are automatically filtered.
        If False only the records that exist right now are added to
        ``hidden_records`` (URL-level, no future filtering).

        Returns the approximate count of records that were affected.
        """
        if not domain:
            return 0
        count = self._db.count_records_for_domain(domain, subdomain_only)
        if auto_hide:
            self._db.hide_domain(domain, subdomain_only)
        else:
            self._db.hide_records_by_domain(domain, subdomain_only)
        self._refresh_hidden_ids()
        self.domain_hidden.emit(domain)
        log.info(
            "Domain hidden: '%s' subdomain_only=%s auto_hide=%s (~%d records)",
            domain,
            subdomain_only,
            auto_hide,
            count,
        )
        return count

    def unhide_domain(self, domain: str) -> None:
        """Remove *domain* from hidden_domains and refresh the view."""
        self._db.unhide_domain(domain)
        self._refresh_hidden_ids()
        log.info("Domain unhidden: '%s'", domain)

    def get_hidden_domains(self) -> list[dict]:
        """Return all entries in hidden_domains (newest first)."""
        return self._db.get_hidden_domains()

    def count_records_for_domain(self, domain: str, subdomain_only: bool) -> int:
        """Delegate to DB for the confirmation-dialog preview count."""
        return self._db.count_records_for_domain(domain, subdomain_only)

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

    def get_filtered_url_prefixes(self) -> list[str]:
        return self._config.privacy.filtered_url_prefixes

    def set_filtered_url_prefixes(self, prefixes: list[str]) -> None:
        """Persist and hot-apply a new filtered_url_prefixes list."""
        self._config.privacy.filtered_url_prefixes = list(prefixes)
        self._config.save()
        self._em.set_filtered_url_prefixes(prefixes)
        log.info("filtered_url_prefixes updated (%d entries)", len(prefixes))

    def get_hidden_ids(self) -> set[int]:
        """Return combined URL-level + domain-level hidden record IDs."""
        return self._db.get_all_hidden_ids()

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
            filtered_url_prefixes=config.privacy.filtered_url_prefixes,
        )
        self._favicon_manager.update_config(config)
        self._monitor.force_check()
        # Reload hidden IDs from DB — combine URL-level and domain-level hidden sets.
        self._refresh_hidden_ids()
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
        # Only persist to disk — do not trigger save_config() which would
        # call set_hidden_ids() -> reload() -> beginResetModel() and reset
        # the scroll position after every column resize or theme switch.
        self._config.save()

    def _emit_stats(self):
        self.stats_updated.emit(
            self._db.get_total_count(),
            self._db.get_last_sync_time(),
        )
