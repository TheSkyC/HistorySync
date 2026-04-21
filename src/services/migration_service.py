# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import shutil
import sqlite3

from src.utils.i18n_core import _
from src.utils.logger import get_logger
from src.utils.migration_detector import LegacyDetectionResult

log = get_logger("migration_service")


# ---------------------------------------------------------------------------
# Enums / dataclasses
# ---------------------------------------------------------------------------


class MigrationStep(StrEnum):
    BACKUP = "backup"
    DB_MIGRATE = "db_migrate"
    CONFIG_MERGE = "config_merge"
    VERIFY = "verify"


@dataclass
class MigrationReport:
    success: bool
    backup_dir: Path | None = None
    db_record_count_before: int = 0
    db_record_count_after: int = 0
    error: str = ""
    error_step: MigrationStep | None = None
    rollback_ok: bool = True


# ---------------------------------------------------------------------------
# Type alias for the progress callback
# ---------------------------------------------------------------------------
# Signature: (step, fraction_0_to_1, human_readable_message)
ProgressCallback = Callable[[MigrationStep, float, str], None]


# ---------------------------------------------------------------------------
# MigrationService
# ---------------------------------------------------------------------------


class MigrationService:
    """Execute a lossless migration from HistorySync 1.0.x to the current version.

    Parameters
    ----------
    result:
        The detection result produced by ``detect_legacy_installation()``.
    progress_callback:
        Called at key checkpoints with ``(step, 0.0-1.0, message)``.
        Must be thread-safe; the UI should connect via Qt signals.
    """

    # Cumulative progress weights for each step (must sum to 1.0)
    _WEIGHTS = {
        MigrationStep.BACKUP: 0.20,
        MigrationStep.DB_MIGRATE: 0.40,
        MigrationStep.CONFIG_MERGE: 0.30,
        MigrationStep.VERIFY: 0.10,
    }

    def __init__(
        self,
        result: LegacyDetectionResult,
        progress_callback: ProgressCallback,
    ) -> None:
        self._result = result
        self._cb: ProgressCallback = progress_callback
        self._backup_dir: Path | None = None
        self._step_base_progress = 0.0  # cumulative progress before current step

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> MigrationReport:
        """Execute all migration steps.  Returns a :class:`MigrationReport`."""
        report = MigrationReport(
            success=False,
            db_record_count_before=self._result.db_record_count,
        )
        current_step: MigrationStep | None = None

        try:
            self._step_base_progress = 0.0

            current_step = MigrationStep.BACKUP
            self._step_backup()
            self._step_base_progress += self._WEIGHTS[MigrationStep.BACKUP]

            current_step = MigrationStep.DB_MIGRATE
            self._step_db_migrate()
            self._step_base_progress += self._WEIGHTS[MigrationStep.DB_MIGRATE]

            current_step = MigrationStep.CONFIG_MERGE
            self._step_config_merge()
            self._step_base_progress += self._WEIGHTS[MigrationStep.CONFIG_MERGE]

            current_step = MigrationStep.VERIFY
            after_count = self._step_verify()
            self._step_base_progress += self._WEIGHTS[MigrationStep.VERIFY]

            report.success = True
            report.backup_dir = self._backup_dir
            report.db_record_count_after = after_count
            log.info("Migration completed successfully (records: %d → %d)", report.db_record_count_before, after_count)

        except Exception as exc:
            err_msg = str(exc)
            log.exception("Migration failed at step %s: %s", current_step, err_msg)
            report.error = err_msg
            report.error_step = current_step
            try:
                self.rollback()
            except Exception as rb_exc:
                log.exception("Rollback also failed: %s", rb_exc)
                report.rollback_ok = False

        return report

    def rollback(self) -> None:
        """Restore all files from the backup directory to their original locations."""
        if self._backup_dir is None or not self._backup_dir.exists():
            log.warning("Rollback requested but no backup directory available")
            return

        log.info("Rolling back migration from backup: %s", self._backup_dir)

        restore_map = {
            self._result.config_file: self._backup_dir / "config.json",
            self._result.db_file: self._backup_dir / "history.db",
            self._result.favicon_db: self._backup_dir / "favicons.db",
            self._result.secret_key: self._backup_dir / "secret.key",
        }

        for dest, src in restore_map.items():
            if dest is not None and src.exists():
                try:
                    shutil.copy2(src, dest)
                    log.info("Restored: %s → %s", src.name, dest)
                except Exception as exc:
                    log.error("Failed to restore %s: %s", src.name, exc)

        log.info("Rollback complete")

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _report(self, step: MigrationStep, step_fraction: float, message: str) -> None:
        """Compute overall progress and invoke the callback."""
        overall = self._step_base_progress + self._WEIGHTS[step] * step_fraction
        overall = min(overall, 1.0)
        log.debug("[%s] %.0f%% — %s", step.value, overall * 100, message)
        try:
            self._cb(step, overall, message)
        except Exception:
            pass  # never let a bad callback abort the migration

    def _step_backup(self) -> None:
        """Copy all legacy files to a timestamped backup directory."""
        self._report(MigrationStep.BACKUP, 0.0, _("Creating backup…"))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Place backup next to the config dir so it is never inside the data dir
        # (prevents DB size metrics being skewed by the backup copy).
        backup_parent = self._result.config_dir.parent
        backup_dir = backup_parent / f"HistorySync_backup_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        files_to_backup = [
            self._result.config_file,
            self._result.db_file,
            self._result.favicon_db,
            self._result.secret_key,
        ]

        total = sum(1 for f in files_to_backup if f and f.exists())
        copied = 0

        for f in files_to_backup:
            if f and f.exists():
                dest = backup_dir / f.name
                shutil.copy2(f, dest)
                copied += 1
                log.info("Backed up: %s → %s", f.name, dest)
                self._report(MigrationStep.BACKUP, copied / max(total, 1), _("Backed up {name}").format(name=f.name))

        self._backup_dir = backup_dir
        self._report(MigrationStep.BACKUP, 1.0, _("Backup created: {path}").format(path=backup_dir))

    def _step_db_migrate(self) -> None:
        """Upgrade the history.db schema via LocalDatabase (idempotent)."""
        self._report(MigrationStep.DB_MIGRATE, 0.0, _("Upgrading database schema…"))

        if not self._result.db_file:
            self._report(MigrationStep.DB_MIGRATE, 1.0, _("No database file — skipped"))
            return

        # Importing LocalDatabase triggers _init_schema → _migrate_schema
        from src.services.local_db import LocalDatabase

        self._report(MigrationStep.DB_MIGRATE, 0.3, _("Running schema migration…"))
        db = LocalDatabase(self._result.db_file)
        db.close()
        self._report(MigrationStep.DB_MIGRATE, 0.8, _("Schema migration complete, verifying columns…"))

        # Verify the new columns exist
        required_cols = {"typed_count", "first_visit_time", "transition_type", "visit_duration"}
        conn = sqlite3.connect(str(self._result.db_file), timeout=10)
        try:
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
        finally:
            conn.close()

        missing = required_cols - existing_cols
        if missing:
            raise RuntimeError(f"Database schema verification failed — missing columns: {', '.join(sorted(missing))}")

        self._report(MigrationStep.DB_MIGRATE, 1.0, _("Database schema upgraded successfully"))

    def _step_config_merge(self) -> None:
        """Merge old config.json with new-format defaults and write it back."""
        self._report(MigrationStep.CONFIG_MERGE, 0.0, _("Merging configuration…"))

        from src.models.app_config import AppConfig

        raw = self._result.raw_config
        self._report(MigrationStep.CONFIG_MERGE, 0.4, _("Applying new default fields…"))

        # from_dict already handles unknown / missing fields gracefully
        cfg = AppConfig.from_dict(raw)

        # The single most critical new field: prevents FirstRunWizard from
        # appearing again after migration completes.
        cfg.first_run_completed = True

        self._report(MigrationStep.CONFIG_MERGE, 0.8, _("Writing updated config.json…"))
        cfg.save()
        self._report(MigrationStep.CONFIG_MERGE, 1.0, _("Configuration merged successfully"))

    def _step_verify(self) -> int:
        """Verify data integrity after migration.  Returns post-migration record count."""
        self._report(MigrationStep.VERIFY, 0.0, _("Verifying migration…"))

        # 1. Config must be parseable and mark first_run_completed=True
        from src.models.app_config import AppConfig

        cfg = AppConfig.load()
        if not cfg.first_run_completed:
            raise RuntimeError("Config verification failed: first_run_completed is not True after migration")
        self._report(MigrationStep.VERIFY, 0.5, _("Config verified"))

        # 2. Record count must not have decreased
        after_count = 0
        if self._result.db_file and self._result.db_file.exists():
            # Use a direct connection rather than a full LocalDatabase() to avoid
            # triggering schema init overhead (migrations already ran in _step_db_migrate).
            _conn = sqlite3.connect(str(self._result.db_file), timeout=10)
            try:
                after_count = _conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            finally:
                _conn.close()

            before = self._result.db_record_count
            if after_count < before:
                raise RuntimeError(
                    f"Record count decreased after migration: {before} → {after_count}. Data may have been lost."
                )

        self._report(
            MigrationStep.VERIFY, 1.0, _("Verification passed — {n} records intact").format(n=f"{after_count:,}")
        )
        return after_count
