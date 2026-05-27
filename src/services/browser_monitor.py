# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QObject, QTimer, Signal

from src.services.extractor_manager import ExtractorManager
from src.services.extractors.base_extractor import get_db_max_mtime
from src.services.local_db import LocalDatabase
from src.utils.logger import get_logger

log = get_logger("browser_monitor")


class BrowserSyncStatus(Enum):
    NOT_FOUND = auto()
    NOT_SYNCED = auto()
    NEEDS_SYNC = auto()
    UP_TO_DATE = auto()
    SYNCING = auto()


class BrowserMonitor(QObject):
    # Signal payload dictionary: { browser_type: status_name_str }
    statuses_changed = Signal(dict)

    def __init__(self, em: ExtractorManager, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._em = em
        self._db = db
        self._current_statuses: dict[str, str] = {}
        self._syncing_browsers: set[str] = set()

        self._timer = QTimer(self)
        self._timer.setInterval(30_000)  # Check every 30 s
        self._timer.timeout.connect(self._check_statuses)

    def start(self):
        self._check_statuses()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_syncing(self, browser_type: str, is_syncing: bool):
        """Externally notifies that a browser is currently being extracted."""
        if is_syncing:
            self._syncing_browsers.add(browser_type)
        else:
            self._syncing_browsers.discard(browser_type)
        self._check_statuses()

    def clear_syncing(self):
        """Clears all syncing states (e.g., reset when a sync error occurs)."""
        self._syncing_browsers.clear()
        self._check_statuses()

    def force_check(self):
        """Forces an immediate check (e.g., called after configuration changes in settings)."""
        self._check_statuses()

    def _check_statuses(self):
        new_statuses: dict[str, str] = {}

        stats = self._db.get_all_backup_stats()
        # Map: (browser_type, profile_name) -> BackupStats
        stat_map = {(s.browser_type, s.profile_name): s for s in stats}

        for bt, extractor in self._em.iter_all_extractors():
            if self._em.is_browser_disabled(bt):
                new_statuses[bt] = BrowserSyncStatus.NOT_FOUND.name
                continue

            # Highest priority: currently syncing
            if bt in self._syncing_browsers:
                new_statuses[bt] = BrowserSyncStatus.SYNCING.name
                continue

            if not extractor.is_available():
                new_statuses[bt] = BrowserSyncStatus.NOT_FOUND.name
                continue

            paths = extractor.get_all_db_paths()
            if not paths:
                new_statuses[bt] = BrowserSyncStatus.NOT_FOUND.name
                continue

            has_unsynced = False
            has_needs_sync = False

            # Bubble up profile status
            for profile_name, db_path in paths:
                if not db_path.exists():
                    continue

                stat = stat_map.get((bt, profile_name))
                if stat is None or stat.last_backup_time == 0:
                    has_unsynced = True
                    break  # If any profile is unsynced, the entire browser is considered unsynced

                mtime = get_db_max_mtime(db_path)
                if stat.last_db_mtime > 0:
                    # Compare against the mtime snapshot taken at extraction time
                    if mtime > stat.last_db_mtime + 2:
                        has_needs_sync = True
                # Fallback for rows written before last_db_mtime was introduced
                elif mtime > stat.last_backup_time + 2:
                    has_needs_sync = True

            if has_unsynced:
                new_statuses[bt] = BrowserSyncStatus.NOT_SYNCED.name
            elif has_needs_sync:
                new_statuses[bt] = BrowserSyncStatus.NEEDS_SYNC.name
            else:
                new_statuses[bt] = BrowserSyncStatus.UP_TO_DATE.name

        if new_statuses != self._current_statuses:
            self._current_statuses = new_statuses
            self.statuses_changed.emit(new_statuses)
