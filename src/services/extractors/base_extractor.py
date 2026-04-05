# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from abc import ABC, abstractmethod
import concurrent.futures
from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef
from src.utils.logger import get_logger

log = get_logger("extractor")

_BACKUP_TIMEOUT_SEC = 10
_LOCK_PROBE_TIMEOUT_SEC = 0.5  # Switch to file copy immediately if lock isn't acquired within 500ms


def copy_db_with_wal(src: Path, dst: Path) -> None:
    """
    File-level copy of an SQLite database.

    Copy order: WAL/SHM first, then the main file.
    Copying WAL first makes the replica's "main file + WAL" closer to a consistent
    point in time, reducing the inconsistency window. WAL/SHM files might not exist;
    skip them if missing.
    """
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(str(side), str(dst.with_name(dst.name + suffix)))
    shutil.copy2(str(src), str(dst))


def _close_quietly(conn: sqlite3.Connection | None) -> None:
    """Silently close the SQLite connection, ignoring all exceptions."""
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def open_db_snapshot(db_path: Path, display_name: str = "", timeout_sec: float = _BACKUP_TIMEOUT_SEC):
    """
    Context manager: Backs up an SQLite database to an in-memory snapshot and yields the connection.
    Ensures the connection is closed upon exit, regardless of exceptions.

    Prioritizes the SQLite backup() API (handles WAL properly, no file race conditions);
    falls back to file copying if backup() fails.

    Usage:
        with open_db_snapshot(db_path, display_name) as conn:
            rows = conn.execute(sql).fetchall()
    """
    conn = _open_snapshot(db_path, display_name, timeout_sec)
    if conn is None:
        raise RuntimeError(f"[{display_name}] Cannot open snapshot of {db_path}")
    try:
        yield conn
    finally:
        _close_quietly(conn)


def _open_snapshot(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
) -> sqlite3.Connection | None:
    """Attempts backup() -> falls back to file copy. Returns an in-memory connection or None."""
    conn = _try_backup(db_path, display_name, timeout_sec)
    if conn is not None:
        return conn
    return _try_file_copy(db_path, display_name, timeout_sec)


def _try_backup(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
) -> sqlite3.Connection | None:
    """Attempts the SQLite backup() API. Returns None on timeout to trigger file copy fallback."""
    src_conn = mem_conn = None
    _start = time.monotonic()
    cancel_event = threading.Event()

    def _do_backup() -> sqlite3.Connection | None:
        nonlocal src_conn, mem_conn
        _last_log = [_start]

        def _progress(status: int, remaining: int, total: int) -> None:
            # If the main thread has timed out and set the cancel flag, raise an exception to interrupt backup()
            if cancel_event.is_set():
                raise sqlite3.OperationalError("backup() cancelled: lock probe timed out")
            now = time.monotonic()
            if now - _last_log[0] >= 2.0:
                log.debug(
                    "[%s] backup() progress: remaining=%d total=%d elapsed=%.1fs",
                    display_name,
                    remaining,
                    total,
                    now - _start,
                )
                _last_log[0] = now

        try:
            src_conn = sqlite3.connect(str(db_path), timeout=0)
            src_conn.execute("SELECT 1")
            mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            # pages=1: Trigger progress callback every 1 page to ensure cancel_event is responded to quickly
            src_conn.backup(mem_conn, pages=1, progress=_progress)
            mem_conn.row_factory = sqlite3.Row
            return mem_conn
        except sqlite3.Error:
            _close_quietly(mem_conn)
            return None
        finally:
            _close_quietly(src_conn)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_backup)
        try:
            result = future.result(timeout=_LOCK_PROBE_TIMEOUT_SEC)
            if result is not None:
                elapsed = time.monotonic() - _start
                log.debug("[%s] backup() OK in %.2fs", display_name, elapsed)
                return result
            # backup() failed due to an error (not a lock issue)
            log.warning(
                "[%s] backup() failed for '%s' — will try file copy",
                display_name,
                db_path.name,
            )
            return None
        except concurrent.futures.TimeoutError:
            # Timeout: Notify the child thread to exit by raising an exception via the progress callback
            cancel_event.set()
            elapsed = time.monotonic() - _start
            log.debug(
                "[%s] backup() lock probe timed out in %.0fms for '%s' — switching to file copy",
                display_name,
                elapsed * 1000,
                db_path.name,
            )
            # Wait for child thread cleanup (cancel_event is set, it will exit on the next progress trigger)
            try:
                future.result(timeout=3.0)
            except Exception:
                pass
            return None


def _try_file_copy(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
    retry: int = 3,
    delay: float = 0.5,
) -> sqlite3.Connection | None:
    """File copy fallback strategy.

    *timeout_sec* caps the total wall-clock time allowed for a single copy
    attempt (file copy + in-memory backup).  The operation is run in a
    worker thread; if it does not finish within *timeout_sec* seconds the
    caller gives up and returns ``None`` immediately.  The worker thread is
    detached (shutdown(wait=False)) so it does not block the caller — Python
    cannot forcibly kill threads, but the thread will finish on its own.
    """
    for attempt in range(1, retry + 1):
        mem_conn: sqlite3.Connection | None = None
        _start = time.monotonic()

        def _do_copy() -> sqlite3.Connection | None:
            """Run inside a worker thread so we can enforce timeout_sec."""
            _file_conn: sqlite3.Connection | None = None
            _mem: sqlite3.Connection | None = None
            try:
                # Use a TemporaryDirectory for the file-level copy.  We MUST
                # close file_conn before the TemporaryDirectory context exits;
                # on Windows an open file handle prevents directory deletion and
                # raises PermissionError (Python < 3.12) or leaves orphaned temp
                # files (Python ≥ 3.12 with ignore_cleanup_errors=True).
                with tempfile.TemporaryDirectory(prefix="historysync_") as tmp_dir:
                    dst = Path(tmp_dir) / db_path.name
                    copy_db_with_wal(db_path, dst)
                    try:
                        # immutable=1: tells SQLite the file won't be modified
                        # externally, bypassing file-lock logic entirely.
                        _file_conn = sqlite3.connect(f"file:{dst}?immutable=1", uri=True)
                        _file_conn.execute("PRAGMA query_only = ON")
                        _mem = sqlite3.connect(":memory:", check_same_thread=False)
                        _file_conn.backup(_mem, pages=200)
                        _mem.row_factory = sqlite3.Row
                    finally:
                        # Close the file handle BEFORE TemporaryDirectory.__exit__
                        # so the directory can always be removed, even on Windows.
                        _close_quietly(_file_conn)
                        _file_conn = None
                # TemporaryDirectory has been cleaned up; _mem is an in-memory
                # database that no longer depends on any on-disk file.
                return _mem
            except Exception:
                _close_quietly(_mem)
                raise

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(_do_copy)
            try:
                mem_conn = future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                # Detach the pool so the caller is not blocked waiting for the
                # worker.  The thread will finish on its own; we just stop caring.
                pool.shutdown(wait=False)
                pool = None
                log.warning(
                    "[%s] file copy timed out after %.0fs (attempt %d)",
                    display_name,
                    timeout_sec,
                    attempt,
                )
                return None

            if mem_conn is not None:
                log.debug(
                    "[%s] file-copy OK (attempt %d, %.2fs)",
                    display_name,
                    attempt,
                    time.monotonic() - _start,
                )
                return mem_conn

            # _do_copy returned None — should not happen, but treat as failure
            raise RuntimeError("_do_copy returned None unexpectedly")

        except OSError as exc:
            _close_quietly(mem_conn)
            mem_conn = None
            if attempt < retry:
                log.debug("[%s] file copy attempt %d blocked: %s — retrying", display_name, attempt, exc)
                time.sleep(delay)
            else:
                log.warning("[%s] file copy failed after %d attempts: %s", display_name, retry, exc)
                return None
        except Exception as exc:
            _close_quietly(mem_conn)
            log.warning("[%s] file-copy backup() failed: %s", display_name, exc)
            return None
        finally:
            if pool is not None:
                pool.shutdown(wait=False)

    return None


# ── BaseExtractor ─────────────────────────────────────────────


class BaseExtractor(ABC):
    def __init__(self, defn: BrowserDef, custom_db_path: Path | None = None):
        """
        Args:
            defn:           Browser definition providing path strategies and metadata.
            custom_db_path: Manually specified single database path (used only for custom Chromium).
        """
        self._defn = defn
        self._custom_db_path = custom_db_path

    @property
    def browser_type(self) -> str:
        return self._defn.browser_type

    @property
    def display_name(self) -> str:
        return self._defn.display_name

    # ── Public Interfaces ─────────────────────────────────────

    def extract(self, since_map: dict[str, int] | None = None) -> list[HistoryRecord]:
        """
        Public entry point: Discovers all Profile databases, safely copies them, and extracts records.

        Args:
            since_map: {profile_name: last_known_unix_timestamp}
                       Only extracts records where visit_time > timestamp;
                       None or missing profiles are treated as 0 (full extraction).
        """
        all_records: list[HistoryRecord] = []
        since_map = since_map or {}

        for profile_name, db_path in self.get_all_db_paths():
            if not db_path.exists():
                continue
            since = since_map.get(profile_name, 0)
            log.info(
                "[%s] Extracting profile '%s' from %s (since=%d)",
                self.display_name,
                profile_name,
                db_path,
                since,
            )
            try:
                records = self._safe_extract(profile_name, db_path, since)
                all_records.extend(records)
                log.info(
                    "[%s] '%s' → %d records (incremental=%s)",
                    self.display_name,
                    profile_name,
                    len(records),
                    since > 0,
                )
            except Exception as exc:
                log.warning(
                    "[%s] Failed to extract '%s': %s",
                    self.display_name,
                    profile_name,
                    exc,
                )

        return all_records

    def is_available(self) -> bool:
        """Checks if the browser has available history database files on the current system."""
        return self._defn.is_history_available(self._custom_db_path)

    def get_all_db_paths(self) -> list[tuple[str, Path]]:
        """
        Returns a list of history database paths for all profiles.
        Used by BrowserMonitor to track file modification times.
        """
        return list(self._defn.iter_history_db_paths(self._custom_db_path))

    # ── Subclass Implementation ───────────────────────────────

    @abstractmethod
    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        """
        Extracts records from an opened SQLite in-memory snapshot.

        Args:
            conn:            Connection to the in-memory snapshot database (read-only).
            profile_name:    Profile name, used to populate HistoryRecord.
            since_unix_time: Only returns records where visit_time > this value (0 = full extraction).
        """

    # ── Internal Implementation ───────────────────────────────

    def _safe_extract(
        self,
        profile_name: str,
        db_path: Path,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        """
        Backs up the database to an in-memory snapshot, then calls _extract_from_db().
        Connection lifecycle is fully encapsulated here; callers do not need to manage connections.
        """
        try:
            with open_db_snapshot(db_path, self.display_name) as conn:
                return self._extract_from_db(conn, profile_name, since_unix_time)
        except RuntimeError as exc:
            log.warning("[%s] Cannot open snapshot for '%s': %s", self.display_name, profile_name, exc)
            return []
