# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from src.services.db_importer import DatabaseImporter, DbType
from src.utils.i18n import _
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.services.local_db import LocalDatabase

log = get_logger("viewmodel.import")


@dataclass
class ImportTask:
    """描述单个文件的导入配置"""

    file_path: Path
    db_type: DbType
    browser_type: str  # 写入记录时使用的 browser_type 标识
    profile_name: str  # 写入记录时使用的 profile_name


@dataclass
class TaskResult:
    """单个文件的导入结果"""

    file_path: Path
    extracted: int
    inserted: int
    skipped: int
    elapsed_sec: float
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class ImportWorker(QObject):
    """
    实际执行导入的 Worker，通过 moveToThread 移入子线程。

    Signals:
        progress(current_idx, total, filename, status_msg)
        task_done(TaskResult)
        finished(total_extracted, total_inserted)
        error(message)
    """

    progress = Signal(int, int, str, str)  # current, total, filename, msg
    task_done = Signal(object)  # TaskResult
    finished = Signal(int, int)  # total_extracted, total_inserted
    error = Signal(str)

    def __init__(self, tasks: list[ImportTask], db: LocalDatabase):
        super().__init__()
        self._tasks = tasks
        self._db = db
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @Slot()
    def run(self):
        total_extracted = 0
        total_inserted = 0
        total = len(self._tasks)

        try:
            for idx, task in enumerate(self._tasks):
                if self._cancelled:
                    break

                self.progress.emit(idx, total, task.file_path.name, _("Extracting…"))
                t0 = time.monotonic()

                try:
                    importer = DatabaseImporter(self._db)
                    records = importer._extract_records(
                        task.file_path,
                        task.db_type,
                        task.browser_type,
                        task.profile_name,
                    )
                except Exception as exc:
                    log.error("[Worker] Extraction failed for %s: %s", task.file_path, exc)
                    self.task_done.emit(
                        TaskResult(
                            file_path=task.file_path,
                            extracted=0,
                            inserted=0,
                            skipped=0,
                            elapsed_sec=time.monotonic() - t0,
                            error=str(exc),
                        )
                    )
                    continue

                if self._cancelled:
                    break

                self.progress.emit(
                    idx, total, task.file_path.name, _("Saving {n} records…").format(n=f"{len(records):,}")
                )

                try:
                    inserted = self._db.upsert_records(records) if records else 0
                except Exception as exc:
                    log.error("[Worker] DB write failed for %s: %s", task.file_path, exc)
                    self.task_done.emit(
                        TaskResult(
                            file_path=task.file_path,
                            extracted=len(records),
                            inserted=0,
                            skipped=len(records),
                            elapsed_sec=time.monotonic() - t0,
                            error=str(exc),
                        )
                    )
                    continue

                # 按 (browser_type, profile_name) 分组更新 backup_stats
                if records:
                    profile_counts: dict[tuple[str, str], int] = {}
                    for r in records:
                        key = (r.browser_type, r.profile_name)
                        profile_counts[key] = profile_counts.get(key, 0) + 1
                    for (bt, pn), count in profile_counts.items():
                        try:
                            self._db.update_backup_stats(bt, pn, count)
                        except Exception as exc:
                            log.warning("[Worker] update_backup_stats failed: %s", exc)

                extracted = len(records)
                skipped = extracted - inserted
                elapsed = time.monotonic() - t0

                total_extracted += extracted
                total_inserted += inserted

                self.task_done.emit(
                    TaskResult(
                        file_path=task.file_path,
                        extracted=extracted,
                        inserted=inserted,
                        skipped=skipped,
                        elapsed_sec=elapsed,
                    )
                )

            if not self._cancelled:
                self.progress.emit(total, total, "", "Done")
                self.finished.emit(total_extracted, total_inserted)

        except Exception as exc:
            log.error("[Worker] Unexpected error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class ImportViewModel(QObject):
    """
    线程生命周期管理器。对外暴露信号，隔离 UI 与线程细节。
    """

    progress_updated = Signal(int, int, str, str)  # current, total, filename, msg
    task_done = Signal(object)  # TaskResult
    import_finished = Signal(int, int)  # total_extracted, total_inserted
    import_error = Signal(str)

    def __init__(self, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._db = db
        self._thread: QThread | None = None
        self._worker: ImportWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_import(self, tasks: list[ImportTask]) -> None:
        if self.is_running:
            return

        self._thread = QThread()
        self._worker = ImportWorker(tasks, self._db)
        self._worker.moveToThread(self._thread)

        # 信号连接
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress_updated)
        self._worker.task_done.connect(self.task_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        # 线程自清理
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_refs)

        self._thread.start()

    def cancel_import(self) -> None:
        if self._worker:
            self._worker.cancel()

    @Slot(int, int)
    def _on_finished(self, extracted: int, inserted: int):
        self.import_finished.emit(extracted, inserted)

    @Slot(str)
    def _on_error(self, msg: str):
        self.import_error.emit(msg)

    @Slot()
    def _clear_refs(self):
        self._thread = None
        self._worker = None
