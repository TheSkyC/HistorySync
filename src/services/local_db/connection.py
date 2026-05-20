# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Connection lifecycle for :class:`LocalDatabase`.

Owns:
  * the persistent read/write connection (``_pconn``)
  * the cached read-only connection used by ``search_quick`` (``_ro_conn``)
  * the locks and lifecycle hooks (``__init__``, ``close``, ``__del__``)
  * the ``_conn`` context manager that every other mixin uses

All connection-state attributes are initialised in :meth:`_ConnectionMixin.__init__`
so that subsequent mixins can rely on them being present.
"""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import threading

from src.utils.logger import get_logger
from src.utils.url_utils import extract_host as _extract_url_host

log = get_logger("local_db")


class _ConnectionMixin:
    """Persistent SQLite connection lifecycle and locking."""

    # Type hints for attributes initialised below; allows mixin code to be
    # type-checked without each mixin redeclaring them.
    db_path: Path
    _headless: bool
    _lock: threading.RLock
    _ro_lock: threading.RLock
    _pconn: sqlite3.Connection | None
    _ro_conn: sqlite3.Connection | None
    _schema_initialized: bool
    _vacuuming: bool
    _fts_thread: threading.Thread | None
    _excl_cache: dict[sqlite3.Connection, frozenset[int]]
    _excl_cache_lock: threading.Lock
    _atexit_registered: bool

    def __init__(self, db_path: Path, headless: bool = False):
        self.db_path = db_path
        self._headless = headless
        self._lock = threading.RLock()
        self._pconn = None
        self._ro_conn = None
        self._ro_lock = threading.RLock()
        self._schema_initialized = False
        self._vacuuming = False
        self._fts_thread = None
        self._excl_cache = {}
        self._excl_cache_lock = threading.Lock()
        self._atexit_registered = False
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Fallback cleanup for callers that forget to call close().
        atexit.register(self._close_at_exit)
        self._atexit_registered = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _close_at_exit(self) -> None:
        """Best-effort shutdown hook for process exit."""
        try:
            self.close()
        except Exception:
            # Interpreter shutdown order is not deterministic; avoid noisy teardown.
            pass

    # ── Internal helpers ──────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        """Return the persistent connection, creating it if necessary.
        Caller must already hold self._lock.
        """
        if self._vacuuming:
            raise RuntimeError("VACUUM in progress — database temporarily unavailable")
        if self._pconn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            # Headless mode runs a handful of queries then exits; a 4 MB page
            # cache is more than sufficient.  GUI mode keeps 32 MB for snappy
            # paginated queries over large history tables.
            cache_size = -4096 if self._headless else -32768
            conn.execute(f"PRAGMA cache_size={cache_size}")
            # mmap adds no benefit in headless (no repeated large scans) and
            # wastes virtual address space that inflates the RSS reading.
            mmap_size = 0 if self._headless else 268435456
            conn.execute(f"PRAGMA mmap_size={mmap_size}")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.commit()
            conn.create_function("_extract_host", 1, _extract_url_host)
            conn.create_function("REGEXP", 2, lambda pat, text: bool(re.search(pat, text or "", re.IGNORECASE)))
            self._pconn = conn
        if not self._schema_initialized:
            self._schema_initialized = True  # set before calling to prevent re-entry
            try:
                # _init_schema_on_conn is provided by _SchemaMixin via MRO.
                self._init_schema_on_conn(self._pconn)  # type: ignore[attr-defined]
            except sqlite3.Error:
                self._schema_initialized = False  # allow retry on next call
                raise
        return self._pconn

    @contextmanager
    def _conn_state_locks(self) -> Iterator[None]:
        """Acquire connection-state locks in a single global order (_lock -> _ro_lock)."""
        with self._lock, self._ro_lock:
            yield

    def _reset_conn_locked(self) -> None:
        """Close/discard connections; caller must hold both state locks."""
        if self._pconn is not None:
            try:
                self._pconn.close()
            except sqlite3.Error:
                pass
            self._pconn = None
        # Clear the excluded-ids cache so that a new connection (which may
        # receive the same id() address) does not incorrectly skip the temp
        # table population.  Without this, hidden-record filtering can silently
        # break after a connection reset.
        with self._excl_cache_lock:
            self._excl_cache.clear()
        if self._ro_conn is not None:
            try:
                self._ro_conn.close()
            except sqlite3.Error:
                pass
            self._ro_conn = None

    def _reset_conn(self) -> None:
        """Close and discard the persistent connection so it is recreated next time."""
        with self._conn_state_locks():
            self._reset_conn_locked()

    def _ensure_ro_conn(self) -> sqlite3.Connection:
        """Return a cached read-only connection for search_quick.

        Uses a URI read-only connection so SQLite never blocks on the write lock.
        The connection is created once and reused across calls; it is closed
        together with the main connection in _reset_conn().

        Must be called with ``_ro_lock`` already held.
        """
        if self._ro_conn is None:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.create_function("_extract_host", 1, _extract_url_host)
            conn.create_function("REGEXP", 2, lambda pat, text: bool(re.search(pat, text or "", re.IGNORECASE)))
            self._ro_conn = conn
        return self._ro_conn

    def _fresh_ro_conn(self) -> sqlite3.Connection:
        """Return the read-only connection after ending any open read transaction.

        Must be called with ``_ro_lock`` already held.

        SQLite WAL mode pins a read-only connection to the snapshot taken at the
        start of its first transaction.  Calling rollback() ends that transaction
        so the next query starts a new one against the latest WAL checkpoint,
        making writes committed by the write connection visible immediately.
        The _excl_ids temp table (populated by _populate_excl_table) is also
        cleared because rollback() undoes its DML — callers that need it must
        re-populate it after calling this method.
        """
        conn = self._ensure_ro_conn()
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        with self._excl_cache_lock:
            self._excl_cache.pop(conn, None)
        return conn

    @contextmanager
    def _conn(self, write: bool = True, strong_read: bool = False) -> Iterator[sqlite3.Connection]:
        """Thread-safe connection context manager.

        write=True  — use the main connection under _lock; commit on success,
                      rollback on error.
        write=False — use the read-only connection under _ro_lock; never blocks
                      on concurrent writes in WAL mode (SQLite allows concurrent
                      readers alongside a single writer).
        strong_read=True (read-only mode only) — end any existing read
                      transaction on the shared RO connection before yielding,
                      so callers see the latest committed WAL state immediately.
        """
        if write and strong_read:
            raise ValueError("strong_read is only valid when write=False")
        if not write:
            # Only compete for the write lock when the schema has not yet been
            # initialised.  Once _schema_initialized is True it is never reset
            # to False outside of _lock, so this double-checked read is safe
            # under the GIL and avoids blocking reads on long write operations.
            if not self._schema_initialized:
                with self._lock:
                    self._ensure_conn()
            with self._ro_lock:
                conn = self._fresh_ro_conn() if strong_read else self._ensure_ro_conn()
                try:
                    yield conn
                except Exception:
                    # Reset the RO connection on error so it is recreated next
                    # time.  Avoid calling _reset_conn() here — it also acquires
                    # _ro_lock which we already hold (RLock, so re-entry is safe,
                    # but _reset_conn touches _ro_conn state we manage here).
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass
                    self._ro_conn = None
                    with self._excl_cache_lock:
                        self._excl_cache.pop(conn, None)
                    raise
            return
        with self._lock:
            conn = self._ensure_conn()
            try:
                yield conn
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                self._reset_conn()
                raise

    def close(self) -> None:
        """Explicitly close the persistent connection (call at app shutdown)."""
        if self._atexit_registered:
            try:
                atexit.unregister(self._close_at_exit)
            except Exception:
                pass
            self._atexit_registered = False
        # Join the FTS background thread first — it holds _lock while running,
        # so we must not hold _lock ourselves while waiting or we'd deadlock.
        if self._fts_thread is not None and self._fts_thread.is_alive():
            self._fts_thread.join(timeout=30)
        self._reset_conn()

    def __del__(self) -> None:
        # Last-resort fallback only. Normal lifecycle should use close() or
        # context-manager semantics for deterministic cleanup.
        if self._pconn is not None:
            try:
                self._pconn.close()
            except sqlite3.Error:
                pass
        with self._ro_lock:
            if self._ro_conn is not None:
                try:
                    self._ro_conn.close()
                except sqlite3.Error:
                    pass
