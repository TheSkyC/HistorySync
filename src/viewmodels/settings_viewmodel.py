# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from src.models.app_config import AppConfig, WebDavConfig
from src.services.webdav_sync import WebDavSyncService
from src.utils.constants import FAVICON_CACHE_DIR_NAME
from src.utils.i18n import _, lang_manager


class WebDavWorker(QObject):
    finished = Signal(str, bool, str)  # action, success, message
    progress = Signal(str)
    backup_list_ready = Signal(list)  # list of backup dicts
    hash_info_ready = Signal(dict)  # filename -> sha256
    manifest_ready = Signal(dict)  # sync_manifest.json contents

    def __init__(self, action: str, svc: WebDavSyncService, db=None, favicon_cache_dir=None):
        super().__init__()
        self.action = action
        self.svc = svc
        self.db = db
        self.favicon_cache_dir = favicon_cache_dir

    @Slot()
    def run(self):
        try:
            if self.action == "test":
                res = self.svc.test_connection()
                self.finished.emit(self.action, res.success, res.message)

            elif self.action == "backup":
                if self.db is not None:
                    self.svc.set_local_db(self.db)
                res = self.svc.sync(
                    progress_callback=self.progress.emit,
                    favicon_cache_dir=self.favicon_cache_dir,
                )
                if res.hash_info:
                    self.hash_info_ready.emit(res.hash_info)
                self.finished.emit(self.action, res.success, res.message)

            elif self.action == "restore":
                restore_favicons = self.svc._config.backup_favicons
                res = self.svc.restore(
                    progress_callback=self.progress.emit,
                    restore_favicons=restore_favicons,
                    favicon_cache_dir=self.favicon_cache_dir,
                )
                if res.success and res.downloaded_path:
                    self.db.merge_from_db(res.downloaded_path, progress_cb=self.progress.emit)
                    self.db.merge_user_data_from_db(res.downloaded_path, progress_cb=self.progress.emit)
                    try:
                        res.downloaded_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if res.hash_info:
                        self.hash_info_ready.emit(res.hash_info)
                    self.finished.emit(self.action, True, res.message)
                else:
                    self.finished.emit(self.action, False, res.message)

            elif self.action == "fetch_manifest":
                manifest = self.svc.fetch_manifest()
                if manifest is not None:
                    self.manifest_ready.emit(manifest)
                    self.finished.emit(self.action, True, "")
                else:
                    self.finished.emit(self.action, False, "")

            elif self.action == "list_backups":
                backups = self.svc.list_backups()
                self.backup_list_ready.emit(backups)
                msg = _("{n} backup(s) found").format(n=len(backups))
                self.finished.emit(self.action, True, msg)

        except Exception as exc:
            self.finished.emit(self.action, False, str(exc))


class SettingsViewModel(QObject):
    saved = Signal()
    error = Signal(str)

    webdav_action_progress = Signal(str)
    webdav_action_finished = Signal(str, bool, str)  # action, success, message
    webdav_manifest_ready = Signal(dict)  # sync_manifest.json contents
    language_change_requested = Signal(str)

    maintenance_progress = Signal(str)
    maintenance_finished = Signal(str, bool, int)  # operation, success, saved_bytes

    def __init__(self, main_vm, parent=None):
        super().__init__(parent)
        self._main_vm = main_vm
        self._wd_thread: QThread | None = None
        self._wd_worker: WebDavWorker | None = None
        self._last_hash_info: dict | None = None
        self._last_backup_list: list = []
        self._maint_thread: QThread | None = None
        self._maint_worker: DbMaintenanceWorker | None = None

    def get_config(self) -> AppConfig:
        return self._main_vm._config

    def save(self, config: AppConfig) -> None:
        try:
            self._main_vm.save_config(config)
            self.saved.emit()
        except Exception as exc:
            self.error.emit(str(exc))

    def run_webdav_action(self, action: str, wd_config: WebDavConfig) -> None:
        try:
            if self._wd_thread is not None and self._wd_thread.isRunning():
                self.webdav_action_finished.emit(action, False, _("A WebDAV task is already running."))
                return
        except RuntimeError:
            pass

        svc = WebDavSyncService(wd_config, self._main_vm._db.db_path)
        svc.set_local_db(self._main_vm._db)
        _device_id = getattr(self._main_vm, "_local_device_id", None)
        if _device_id is not None:
            svc.set_device_id(_device_id)

        from src.utils.path_helper import get_config_dir

        favicon_cache_dir = get_config_dir() / FAVICON_CACHE_DIR_NAME

        self._wd_thread = QThread()
        self._wd_worker = WebDavWorker(action, svc, self._main_vm._db, favicon_cache_dir)
        self._wd_worker.moveToThread(self._wd_thread)

        self._wd_thread.started.connect(self._wd_worker.run)
        self._wd_worker.progress.connect(self._on_webdav_progress)
        self._wd_worker.finished.connect(self._on_webdav_finished)
        self._wd_worker.hash_info_ready.connect(self._on_hash_info)
        self._wd_worker.backup_list_ready.connect(self._on_backup_list)
        self._wd_worker.manifest_ready.connect(self.webdav_manifest_ready)

        self._wd_worker.finished.connect(self._wd_thread.quit)
        self._wd_thread.finished.connect(self._wd_worker.deleteLater)
        self._wd_thread.finished.connect(self._wd_thread.deleteLater)
        self._wd_thread.finished.connect(self._clear_thread_refs)

        self._wd_thread.start()

    @Slot(str)
    def _on_webdav_progress(self, msg: str):
        self.webdav_action_progress.emit(msg)

    @Slot(str, bool, str)
    def _on_webdav_finished(self, action: str, success: bool, msg: str):
        if action == "restore" and success:
            self._main_vm.history_vm.refresh()
            self._main_vm._emit_stats()
        if action == "backup" and success:
            import time as _time

            self._main_vm._config.last_backup_ts = int(_time.time())
            self._main_vm._config.save()
        self.webdav_action_finished.emit(action, success, msg)

    @Slot(dict)
    def _on_hash_info(self, info: dict):
        self._last_hash_info = info

    @Slot(list)
    def _on_backup_list(self, backups: list):
        self._last_backup_list = backups

    @Slot()
    def _clear_thread_refs(self):
        self._wd_thread = None
        self._wd_worker = None

    # ── DB maintenance ────────────────────────────────────────

    def get_db_stats(self):
        """Return a DbStats snapshot (cheap, synchronous read)."""
        return self._main_vm._db.get_db_stats()

    def run_db_maintenance(self, operation: str) -> None:
        """Launch *operation* ('vacuum' | 'normalize_domains' | 'rebuild_fts') off-thread."""
        if self._wd_thread is not None and self._wd_thread.isRunning():
            self.maintenance_finished.emit(operation, False, 0)
            return

        self._maint_thread = QThread()
        self._maint_worker = DbMaintenanceWorker(operation, self._main_vm._db)
        self._maint_worker.moveToThread(self._maint_thread)

        self._maint_thread.started.connect(self._maint_worker.run)
        self._maint_worker.progress.connect(self.maintenance_progress)
        self._maint_worker.finished.connect(self._on_maint_finished)
        self._maint_worker.finished.connect(self._maint_thread.quit)
        self._maint_thread.finished.connect(self._maint_worker.deleteLater)
        self._maint_thread.finished.connect(self._maint_thread.deleteLater)

        self._maint_thread.start()

    @Slot(str, bool, int)
    def _on_maint_finished(self, operation: str, success: bool, saved: int):
        self.maintenance_finished.emit(operation, success, saved)

    def change_language(self, lang_code: str) -> None:
        cfg = self._main_vm._config
        cfg.language = lang_code
        cfg.save()
        self.language_change_requested.emit(lang_code)

    def get_available_languages(self) -> dict[str, str]:
        return lang_manager.get_available_languages_map()

    def get_current_language(self) -> str:
        return lang_manager.get_current_language()


# ── Database maintenance worker ───────────────────────────────────────────────


class DbMaintenanceWorker(QObject):
    """Off-thread worker for VACUUM, domain normalisation, and FTS rebuild."""

    progress = Signal(str)  # incremental log lines
    finished = Signal(str, bool, int)  # (operation, success, saved_bytes)

    def __init__(self, operation: str, db):
        super().__init__()
        self.operation = operation
        self.db = db

    @Slot()
    def run(self):
        op = self.operation
        try:
            if op == "vacuum":
                before, after = self.db.vacuum_and_analyze(progress_cb=self.progress.emit)
                self.finished.emit(op, True, before - after)

            elif op == "normalize_domains":
                self.db.normalize_domains(progress_cb=self.progress.emit)
                self.finished.emit(op, True, 0)

            elif op == "rebuild_fts":
                self.db.rebuild_fts_index(progress_cb=self.progress.emit)
                self.finished.emit(op, True, 0)

            else:
                self.finished.emit(op, False, 0)

        except Exception as exc:
            self.progress.emit(f"Error: {exc}")
            self.finished.emit(op, False, 0)
