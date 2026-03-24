# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from src.services.extractor_manager import ExtractorManager
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
    # 信号传递字典：{ browser_type: status_name_str }
    statuses_changed = Signal(dict)

    def __init__(self, em: ExtractorManager, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._em = em
        self._db = db
        self._current_statuses: dict[str, str] = {}
        self._syncing_browsers: set[str] = set()

        self._timer = QTimer(self)
        self._timer.setInterval(3000)  # 每 3 秒检测一次
        self._timer.timeout.connect(self._check_statuses)

    def start(self):
        self._check_statuses()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_syncing(self, browser_type: str, is_syncing: bool):
        """外部通知某浏览器正在提取中。"""
        if is_syncing:
            self._syncing_browsers.add(browser_type)
        else:
            self._syncing_browsers.discard(browser_type)
        self._check_statuses()

    def clear_syncing(self):
        """清除所有正在同步状态（例如同步发生错误时重置）。"""
        self._syncing_browsers.clear()
        self._check_statuses()

    def force_check(self):
        """强制立刻检测一次（如设置页修改了配置后调用）。"""
        self._check_statuses()

    def _get_max_mtime(self, db_path: Path) -> float:
        """获取数据库及 WAL/SHM 的最大修改时间，解决 SQLite 的延迟落盘问题。"""
        max_mtime = 0.0
        for suffix in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix)
            if p.exists():
                try:
                    max_mtime = max(max_mtime, p.stat().st_mtime)
                except OSError:
                    pass
        return max_mtime

    def _check_statuses(self):
        new_statuses: dict[str, str] = {}

        stats = self._db.get_all_backup_stats()
        # Map: (browser_type, profile_name) -> last_backup_time
        last_sync_map = {(s.browser_type, s.profile_name): s.last_backup_time for s in stats}

        for bt, extractor in self._em.iter_all_extractors():
            if self._em.is_browser_disabled(bt):
                new_statuses[bt] = BrowserSyncStatus.NOT_FOUND.name
                continue

            # 最高优先级：正在同步中
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

            # Profile 状态向上冒泡
            for profile_name, db_path in paths:
                if not db_path.exists():
                    continue

                last_sync = last_sync_map.get((bt, profile_name), 0)
                if last_sync == 0:
                    has_unsynced = True
                    break  # 只要有一个未同步，整体即为未同步

                mtime = self._get_max_mtime(db_path)
                # 加 2 秒缓冲时间以抵消文件系统的时间戳精度截断问题
                if mtime > last_sync + 2:
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
