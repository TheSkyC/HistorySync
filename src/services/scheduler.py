# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from src.models.app_config import SchedulerConfig
from src.utils.constants import APP_NAME, BUNDLE_ID, FAVICON_CACHE_DIR_NAME
from src.utils.logger import get_logger

log = get_logger("scheduler")


# ── Worker thread ────────────────────────────────────────────


class SyncWorker(QObject):
    """在后台线程中执行提取 + 可选 WebDAV 同步。"""

    finished = Signal(dict)  # {browser_type: inserted_count}
    progress = Signal(str, str, int)  # browser_type, status, count
    error = Signal(str)

    def __init__(
        self,
        extractor_manager,
        webdav_service=None,
        browser_types: list[str] | None = None,
        favicon_cache_dir: Path | None = None,
        force_full: bool = False,
    ):
        super().__init__()
        self._em = extractor_manager
        self._wdav = webdav_service
        self._browser_types = browser_types  # None = all browsers
        self._favicon_cache_dir = favicon_cache_dir
        self._force_full = force_full
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        results: dict[str, int] = {}
        exc_msg: str | None = None
        try:
            log.info("Sync worker started")

            def cb(bt: str, status: str, count: int) -> None:
                if not self._cancelled:
                    self.progress.emit(bt, status, count)

            results = self._em.run_extraction(
                browser_types=self._browser_types,
                progress_callback=cb,
                force_full=self._force_full,
            )
            if not self._cancelled and self._wdav and self._wdav.is_configured() and self._wdav._config.auto_backup:
                self._wdav.sync(favicon_cache_dir=self._favicon_cache_dir)
        except Exception as exc:
            log.error("Sync worker unhandled exception: %s", exc, exc_info=True)
            exc_msg = str(exc)
        finally:
            if self._cancelled:
                log.info("Sync worker: cancelled, skipping result signals")
            elif exc_msg is not None:
                self.error.emit(exc_msg)
            else:
                self.finished.emit(results)


class BackupWorker(QObject):
    """Dedicated worker for scheduled WebDAV backup (independent of extraction)."""

    finished = Signal(bool, str)  # success, message
    progress = Signal(str)

    def __init__(self, webdav_service, favicon_cache_dir: Path | None = None):
        super().__init__()
        self._wdav = webdav_service
        self._favicon_cache_dir = favicon_cache_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        if self._cancelled:
            return
        try:
            res = self._wdav.sync(
                progress_callback=self.progress.emit,
                favicon_cache_dir=self._favicon_cache_dir,
            )
            if not self._cancelled:
                self.finished.emit(res.success, res.message)
        except Exception as exc:
            if not self._cancelled:
                self.finished.emit(False, str(exc))


# ── Scheduler ────────────────────────────────────────────────


class Scheduler(QObject):
    """
    主线程定时器，将 I/O 工作派发到 QThread。
    """

    sync_started = Signal()
    sync_finished = Signal(dict)
    sync_progress = Signal(str, str, int)
    sync_error = Signal(str)

    backup_started = Signal()
    backup_finished = Signal(bool, str)  # success, message

    def __init__(self, extractor_manager, webdav_service=None, parent=None):
        super().__init__(parent)
        self._em = extractor_manager
        self._wdav = webdav_service

        # Sync timer
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._on_sync_timer)
        self._running = False
        self._last_sync: int | None = None
        self._worker_thread: QThread | None = None
        self._worker = None

        # Auto-backup timer (independent of sync)
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._on_backup_timer)
        self._backup_running = False
        self._backup_thread: QThread | None = None
        self._backup_worker = None

        from src.utils.path_helper import get_app_data_dir

        self._favicon_cache_dir = get_app_data_dir() / FAVICON_CACHE_DIR_NAME

    def configure(self, config: SchedulerConfig, last_sync_ts: int = 0, last_backup_ts: int = 0) -> None:
        """Apply (or re-apply) scheduler configuration.

        Parameters
        ----------
        config         : scheduler-specific settings
        last_sync_ts   : epoch seconds of the last successful sync (0 = never)
        last_backup_ts : epoch seconds of the last successful backup (0 = never)
        """
        # Sync timer
        self._sync_timer.stop()
        if config.auto_sync_enabled and config.sync_interval_hours > 0:
            interval_ms = config.sync_interval_hours * 3600 * 1000
            sync_ts = last_sync_ts if last_sync_ts > 0 else None
            first_ms = self._calc_first_interval_ms(interval_ms, sync_ts)
            if first_ms <= 0:
                self._sync_timer.setInterval(interval_ms)
                from PySide6.QtCore import QTimer as _QTimer

                _QTimer.singleShot(0, self._on_sync_timer)
                log.info("Sync timer: overdue, firing now; repeat every %d hours", config.sync_interval_hours)
            else:
                # Use a one-shot lead-in, then switch to the repeating cadence.
                self._sync_timer.setInterval(interval_ms)
                from PySide6.QtCore import QTimer as _QTimer

                _QTimer.singleShot(first_ms, self._start_repeating_sync_timer)
                log.info(
                    "Sync timer: first fire in %.1f min, then every %d hours",
                    first_ms / 60000,
                    config.sync_interval_hours,
                )

        # Backup timer
        self._backup_timer.stop()
        if config.auto_backup_enabled and config.auto_backup_interval_hours > 0:
            backup_interval_ms = config.auto_backup_interval_hours * 3600 * 1000
            backup_ts = last_backup_ts if last_backup_ts > 0 else None
            first_backup_ms = self._calc_first_interval_ms(backup_interval_ms, backup_ts)
            if first_backup_ms <= 0:
                self._backup_timer.setInterval(backup_interval_ms)
                from PySide6.QtCore import QTimer as _QTimer

                _QTimer.singleShot(0, self._on_backup_timer)
                log.info("Backup timer: overdue, firing now; repeat every %d hours", config.auto_backup_interval_hours)
            else:
                self._backup_timer.setInterval(backup_interval_ms)
                from PySide6.QtCore import QTimer as _QTimer

                _QTimer.singleShot(first_backup_ms, self._start_repeating_backup_timer)
                log.info(
                    "Backup timer: first fire in %.1f min, then every %d hours",
                    first_backup_ms / 60000,
                    config.auto_backup_interval_hours,
                )

    # ── Timer helpers ─────────────────────────────────────────

    def _calc_first_interval_ms(self, interval_ms: int, last_ts: int | None) -> int:
        if last_ts is None:
            # Never ran — wait one full interval before the first auto-sync.
            # This avoids an unwanted immediate sync on first launch while the
            # user is still going through the setup wizard.
            return interval_ms
        elapsed_ms = int((time.time() - last_ts) * 1000)
        return interval_ms - elapsed_ms

    @Slot()
    def _start_repeating_sync_timer(self) -> None:
        """Called once by the lead-in singleShot; fires the sync and arms the repeating timer."""
        self._on_sync_timer()
        if not self._sync_timer.isActive():
            self._sync_timer.start()

    @Slot()
    def _start_repeating_backup_timer(self) -> None:
        """Called once by the lead-in singleShot; fires the backup and arms the repeating timer."""
        self._on_backup_timer()
        if not self._backup_timer.isActive():
            self._backup_timer.start()

    def start(self, config: SchedulerConfig, last_sync_ts: int = 0, last_backup_ts: int = 0) -> None:
        self.configure(config, last_sync_ts=last_sync_ts, last_backup_ts=last_backup_ts)
        log.info("Scheduler started")

    def stop(self) -> None:
        self._sync_timer.stop()
        self._backup_timer.stop()
        log.info("Scheduler stopped")

    def set_auto_sync_enabled(self, enabled: bool) -> None:
        """Pause or resume the auto-sync timer without touching the backup timer."""
        if enabled:
            if not self._sync_timer.isActive():
                self._sync_timer.start()
                log.info("Auto sync resumed")
        else:
            self._sync_timer.stop()
            log.info("Auto sync paused")

    def trigger_now(self) -> None:
        if self._running:
            log.info("Sync already running, skipping trigger")
            return
        self._run_sync()

    def trigger_browser(self, browser_type: str) -> None:
        """Trigger a sync for a single browser only."""
        if self._running:
            log.info("Sync already running, skipping single-browser trigger")
            return
        self._run_sync(browser_types=[browser_type])

    def trigger_full_resync(self, browser_types: list[str] | None = None) -> None:
        """Trigger a full re-extraction of all (or specified) browsers.

        Unlike the normal incremental sync, this ignores the visit-time
        watermark and re-reads every record from the browser databases, then
        upserts them.  Use this when a new field (e.g. ``visit_count``) was
        added and you want to back-fill historical data.

        Parameters
        ----------
        browser_types:
            Limit the resync to these browser types.  ``None`` means all
            available browsers.
        """
        if self._running:
            log.info("Sync already running, skipping full-resync trigger")
            return
        log.info("Full resync triggered (browsers=%s)", browser_types or "all")
        self._run_sync(browser_types=browser_types, force_full=True)

    def trigger_backup_now(self) -> None:
        if self._backup_running:
            log.info("Backup already running, skipping")
            return
        self._run_backup()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_sync(self) -> int | None:
        return self._last_sync

    # ── Shutdown ──────────────────────────────────────────────

    def shutdown(self, timeout_ms: int = 8000) -> None:
        self._sync_timer.stop()
        self._backup_timer.stop()
        for thread, worker in [
            (self._worker_thread, self._worker),
            (self._backup_thread, self._backup_worker),
        ]:
            if thread is None or not thread.isRunning():
                continue
            if worker is not None:
                worker.cancel()
            log.info("Scheduler: waiting for thread to finish...")
            if not thread.wait(timeout_ms):
                log.warning("Thread did not finish in time, forcing quit")
                thread.quit()
                thread.wait(2000)

    # ── Internal sync ─────────────────────────────────────────

    def _on_sync_timer(self) -> None:
        if not self._running:
            self._run_sync()

    def _run_sync(self, browser_types: list[str] | None = None, force_full: bool = False) -> None:
        self._running = True
        self.sync_started.emit()

        thread = QThread()
        worker = SyncWorker(
            self._em,
            self._wdav,
            browser_types=browser_types,
            favicon_cache_dir=self._favicon_cache_dir,
            force_full=force_full,
        )
        self._worker = worker
        self._worker_thread = thread
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_sync_finished, Qt.DirectConnection)
        worker.progress.connect(self.sync_progress)
        worker.error.connect(self._on_sync_error, Qt.DirectConnection)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_sync_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        thread.start()

    @Slot(dict)
    def _on_sync_finished(self, results: dict) -> None:
        self._running = False
        self._last_sync = int(time.time())
        self.sync_finished.emit(results)
        log.info("Sync finished: %s", results)

    @Slot(str)
    def _on_sync_error(self, msg: str) -> None:
        self._running = False
        self.sync_error.emit(msg)

    @Slot()
    def _on_sync_thread_finished(self) -> None:
        if self._running:
            log.warning("Sync thread finished but _running was still True... resetting.")
            self._running = False
        self._worker_thread = None
        self._worker = None

    # ── Internal backup ───────────────────────────────────────

    def _on_backup_timer(self) -> None:
        if not self._backup_running:
            self._run_backup()

    def _run_backup(self) -> None:
        if not self._wdav or not self._wdav.is_configured():
            log.info("Backup timer fired but WebDAV not configured")
            return
        self._backup_running = True
        self.backup_started.emit()
        log.info("Scheduled backup starting")

        thread = QThread()
        worker = BackupWorker(self._wdav, self._favicon_cache_dir)
        self._backup_worker = worker
        self._backup_thread = thread
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_backup_finished, Qt.DirectConnection)
        worker.finished.connect(thread.quit)

        thread.finished.connect(self._on_backup_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        thread.start()

    @Slot(bool, str)
    def _on_backup_finished(self, success: bool, msg: str) -> None:
        self._backup_running = False
        self.backup_finished.emit(success, msg)
        log.info("Scheduled backup %s: %s", "OK" if success else "FAILED", msg)

    @Slot()
    def _on_backup_thread_finished(self) -> None:
        self._backup_running = False
        self._backup_thread = None
        self._backup_worker = None


# ── Cross-platform startup ────────────────────────────────────


class StartupManager:
    """跨平台开机自启管理。"""

    @classmethod
    def enable(cls, executable_path: str) -> bool:
        try:
            if sys.platform == "win32":
                return cls._enable_windows(executable_path)
            if sys.platform == "darwin":
                return cls._enable_macos(executable_path)
            return cls._enable_linux(executable_path)
        except Exception as exc:
            log.error("Failed to enable startup: %s", exc)
            return False

    @classmethod
    def disable(cls) -> bool:
        try:
            if sys.platform == "win32":
                return cls._disable_windows()
            if sys.platform == "darwin":
                return cls._disable_macos()
            return cls._disable_linux()
        except Exception as exc:
            log.error("Failed to disable startup: %s", exc)
            return False

    @classmethod
    def is_enabled(cls) -> bool:
        try:
            if sys.platform == "win32":
                return cls._check_windows()
            if sys.platform == "darwin":
                return cls._check_macos()
            return cls._check_linux()
        except Exception:
            return False

    @classmethod
    def _enable_windows(cls, exe_path: str) -> bool:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
            winreg.CloseKey(key)
            log.info("Windows startup enabled: %s", exe_path)
            return True
        except OSError as exc:
            log.error("Windows startup enable failed: %s", exc)
            return False

    @classmethod
    def _disable_windows(cls) -> bool:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, APP_NAME)
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        return True

    @classmethod
    def _check_windows(cls) -> bool:
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False

    @classmethod
    def _plist_path(cls) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"

    @classmethod
    def _enable_macos(cls, exe_path: str) -> bool:
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{BUNDLE_ID}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
        <string>--minimized</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
        p = cls._plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        log.info("macOS LaunchAgent created: %s", p)
        return True

    @classmethod
    def _disable_macos(cls) -> bool:
        p = cls._plist_path()
        if p.exists():
            p.unlink()
        return True

    @classmethod
    def _check_macos(cls) -> bool:
        return cls._plist_path().exists()

    @classmethod
    def _autostart_path(cls) -> Path:
        return Path.home() / ".config" / "autostart" / f"{APP_NAME.lower()}.desktop"

    @classmethod
    def _enable_linux(cls, exe_path: str) -> bool:
        desktop = (
            f"[Desktop Entry]\n"
            f"Type=Application\n"
            f"Name={APP_NAME}\n"
            f"Exec={exe_path} --minimized\n"
            f"Hidden=false\n"
            f"NoDisplay=false\n"
            f"X-GNOME-Autostart-enabled=true\n"
        )
        p = cls._autostart_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(desktop, encoding="utf-8")
        return True

    @classmethod
    def _disable_linux(cls) -> bool:
        p = cls._autostart_path()
        if p.exists():
            p.unlink()
        return True

    @classmethod
    def _check_linux(cls) -> bool:
        return cls._autostart_path().exists()
