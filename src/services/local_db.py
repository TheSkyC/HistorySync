# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time

from src.models.history_record import AnnotationRecord, BackupStats, BookmarkRecord, HistoryRecord
from src.utils.constants import DB_BATCH_SIZE
from src.utils.i18n_core import _
from src.utils.logger import get_logger
from src.utils.url_utils import (
    extract_display_domain as _extract_display_domain,
    extract_host as _extract_url_host,
    normalize_domain,
)

log = get_logger("local_db")


# ── SQL injection defence helpers ─────────────────────────────────────────────

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_COL_TYPES = frozenset({"INTEGER", "REAL", "TEXT", "BLOB", "NUMERIC"})


def _quote_identifier(name: str) -> str:
    """Return *name* as a safely double-quoted SQLite identifier.

    Raises ``ValueError`` if *name* contains characters that cannot appear
    in a valid SQLite identifier, providing an extra layer of defence against
    unexpected values sourced from ``sqlite_master`` or schema constants.
    """
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    # Double-quote and escape any embedded double-quotes (standard SQL).
    return '"' + name.replace('"', '""') + '"'


def _sanitize_col_type(col_type: str) -> str:
    """Validate that *col_type* is one of the known SQLite affinity keywords."""
    upper = col_type.strip().upper()
    if upper not in _ALLOWED_COL_TYPES:
        raise ValueError(f"Unsafe column type rejected: {col_type!r}")
    return upper


def _sanitize_vacuum_path(path_str: str) -> str:
    """Escape a filesystem path for use inside a ``VACUUM INTO '...'`` literal.

    SQLite path strings are delimited by single quotes; a single quote inside
    the path must be doubled.  We also reject null bytes which SQLite would
    silently truncate.
    """
    if "\x00" in path_str:
        raise ValueError("Null byte in VACUUM INTO path")
    return path_str.replace("'", "''")


@dataclass
class DbStats:
    """Snapshot of database size and content metrics."""

    file_size_bytes: int  # actual file size on disk
    page_count: int  # total SQLite pages allocated
    free_page_count: int  # unused (fragmented) pages
    page_size: int  # bytes per page
    record_count: int  # rows in history table
    domain_count: int  # distinct domains (after normalization)
    fts_size_bytes: int  # estimated size of FTS index

    @property
    def wasted_bytes(self) -> int:
        return self.free_page_count * self.page_size

    @property
    def wasted_pct(self) -> float:
        if self.page_count == 0:
            return 0.0
        return self.free_page_count / self.page_count * 100


class LocalDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._pconn: sqlite3.Connection | None = None
        self._ro_conn: sqlite3.Connection | None = None
        self._ro_lock = threading.Lock()
        self._schema_initialized: bool = False
        self._vacuuming: bool = False
        self._fts_thread: threading.Thread | None = None
        self._excl_cache: dict[int, frozenset[int]] = {}  # keyed by id(conn)
        self._excl_cache_lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)

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
            conn.execute("PRAGMA cache_size=-32768")  # 32 MB page cache
            conn.execute("PRAGMA mmap_size=268435456")  # 256 MB memory-mapped I/O
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.commit()
            conn.create_function("_extract_host", 1, _extract_url_host)
            conn.create_function("REGEXP", 2, lambda pat, text: bool(re.search(pat, text or "", re.IGNORECASE)))
            self._pconn = conn
        if not self._schema_initialized:
            self._schema_initialized = True  # set before calling to prevent re-entry
            try:
                self._init_schema_on_conn(self._pconn)
            except Exception:
                self._schema_initialized = False  # allow retry on next call
                raise
        return self._pconn

    def _reset_conn(self) -> None:
        """Close and discard the persistent connection so it is recreated next time."""
        if self._pconn is not None:
            try:
                self._pconn.close()
            except Exception:
                pass
            self._pconn = None
        # Clear the excluded-ids cache so that a new connection (which may
        # receive the same id() address) does not incorrectly skip the temp
        # table population.  Without this, hidden-record filtering can silently
        # break after a connection reset.
        with self._excl_cache_lock:
            self._excl_cache.clear()
        with self._ro_lock:
            if self._ro_conn is not None:
                try:
                    self._ro_conn.close()
                except Exception:
                    pass
                self._ro_conn = None

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
            conn.create_function("REGEXP", 2, lambda pat, text: bool(re.search(pat, text or "", re.IGNORECASE)))
            self._ro_conn = conn
        return self._ro_conn

    @contextmanager
    def _conn(self, write: bool = True) -> Iterator[sqlite3.Connection]:
        """Thread-safe connection context manager backed by a persistent connection.

        write=True  — commit on success, rollback on error (default, safe for all callers).
        write=False — skip commit/rollback for read-only queries (minor perf win).
        """
        with self._lock:
            conn = self._ensure_conn()
            try:
                yield conn
                if write:
                    conn.commit()
            except Exception:
                if write:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                self._reset_conn()
                raise

    def close(self) -> None:
        """Explicitly close the persistent connection (call at app shutdown)."""
        # Join the FTS background thread first — it holds _lock while running,
        # so we must not hold _lock ourselves while waiting or we'd deadlock.
        if self._fts_thread is not None and self._fts_thread.is_alive():
            self._fts_thread.join(timeout=30)
        with self._lock:
            self._reset_conn()

    def __del__(self) -> None:
        # Do not call close() here — joining _fts_thread during interpreter
        # shutdown can block indefinitely. Just release the DB connections.
        if self._pconn is not None:
            try:
                self._pconn.close()
            except Exception:
                pass
        with self._ro_lock:
            if self._ro_conn is not None:
                try:
                    self._ro_conn.close()
                except Exception:
                    pass

    def _init_schema_on_conn(self, conn: sqlite3.Connection) -> None:
        """Run schema creation directly on *conn* (called from _ensure_conn to avoid re-entrancy)."""
        conn.executescript("""
                CREATE TABLE IF NOT EXISTS domains (
                    id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT    NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS history (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    url               TEXT    NOT NULL,
                    title             TEXT    NOT NULL DEFAULT '',
                    visit_time        INTEGER NOT NULL,
                    visit_count       INTEGER NOT NULL DEFAULT 1,
                    browser_type      TEXT    NOT NULL,
                    profile_name      TEXT    NOT NULL DEFAULT '',
                    metadata          TEXT    NOT NULL DEFAULT '',
                    domain_id         INTEGER REFERENCES domains(id),
                    created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    typed_count       INTEGER,
                    first_visit_time  INTEGER,
                    transition_type   INTEGER,
                    visit_duration    REAL,
                    device_id         INTEGER REFERENCES devices(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_history_dedup
                    ON history(browser_type, url, visit_time);

                CREATE INDEX IF NOT EXISTS idx_history_visit_time
                    ON history(visit_time DESC);
                CREATE INDEX IF NOT EXISTS idx_history_browser
                    ON history(browser_type);
                CREATE INDEX IF NOT EXISTS idx_history_url
                    ON history(url);
                CREATE INDEX IF NOT EXISTS idx_history_domain
                    ON history(domain_id);
                -- Composite indexes for filtered ORDER BY visit_time DESC queries.
                -- These allow filtered deep-pagination (OFFSET) to stay index-only,
                -- avoiding a full table scan when browser_type or domain_id filters
                -- are active.
                CREATE INDEX IF NOT EXISTS idx_history_browser_time
                    ON history(browser_type, visit_time DESC);
                CREATE INDEX IF NOT EXISTS idx_history_domain_time
                    ON history(domain_id, visit_time DESC);

                CREATE TABLE IF NOT EXISTS backup_stats (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    browser_type         TEXT    NOT NULL,
                    profile_name         TEXT    NOT NULL DEFAULT '',
                    first_backup_time    INTEGER NOT NULL,
                    last_backup_time     INTEGER NOT NULL,
                    total_records_synced INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(browser_type, profile_name)
                );

                CREATE TABLE IF NOT EXISTS hidden_records (
                    url        TEXT    NOT NULL PRIMARY KEY,
                    hidden_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS history_fts
                    USING fts5(
                        url, title,
                        content='history',
                        content_rowid='id',
                        tokenize='trigram'
                    );

                CREATE TRIGGER IF NOT EXISTS history_ai AFTER INSERT ON history BEGIN
                    INSERT INTO history_fts(rowid, url, title)
                        VALUES (new.id, new.url, new.title);
                END;
                CREATE TRIGGER IF NOT EXISTS history_ad AFTER DELETE ON history BEGIN
                    INSERT INTO history_fts(history_fts, rowid, url, title)
                        VALUES('delete', old.id, old.url, old.title);
                END;
                CREATE TRIGGER IF NOT EXISTS history_au AFTER UPDATE ON history BEGIN
                    INSERT INTO history_fts(history_fts, rowid, url, title)
                        VALUES('delete', old.id, old.url, old.title);
                    INSERT INTO history_fts(rowid, url, title)
                        VALUES (new.id, new.url, new.title);
                END;

                CREATE TABLE IF NOT EXISTS bookmarks (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT    NOT NULL UNIQUE,
                    title         TEXT    NOT NULL DEFAULT '',
                    tags          TEXT    NOT NULL DEFAULT '',
                    bookmarked_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    history_id    INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_bookmarks_url ON bookmarks(url);
                CREATE INDEX IF NOT EXISTS idx_bookmarks_at  ON bookmarks(bookmarked_at DESC);

                CREATE TABLE IF NOT EXISTS bookmark_tags (
                    bookmark_id  INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
                    tag          TEXT    NOT NULL,
                    PRIMARY KEY (bookmark_id, tag)
                );
                CREATE INDEX IF NOT EXISTS idx_bookmark_tags_tag ON bookmark_tags(tag);

                CREATE TABLE IF NOT EXISTS annotations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    url        TEXT    NOT NULL UNIQUE,
                    note       TEXT    NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    history_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_annotations_url ON annotations(url);

                CREATE TABLE IF NOT EXISTS deleted_records (
                    url        TEXT    NOT NULL PRIMARY KEY,
                    deleted_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS deleted_bookmarks (
                    url        TEXT    NOT NULL PRIMARY KEY,
                    deleted_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS deleted_annotations (
                    url        TEXT    NOT NULL PRIMARY KEY,
                    deleted_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS devices (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid          TEXT    NOT NULL UNIQUE,
                    name          TEXT    NOT NULL,
                    platform      TEXT,
                    app_version   TEXT,
                    last_sync_at  INTEGER,
                    created_at    INTEGER DEFAULT (strftime('%s','now'))
                );
                CREATE INDEX IF NOT EXISTS idx_devices_uuid ON devices(uuid);
            """)
        # _migrate_schema and _verify_fts_integrity use self._conn() internally;
        # _schema_initialized is already True so they won't re-enter here.
        self._migrate_schema()
        # Run FTS integrity check in a background thread so it never blocks the
        # main thread / UI startup (the check itself is safe to run concurrently
        # because it only reads and the _lock protects each _conn() call).
        self._fts_thread = threading.Thread(target=self._verify_fts_integrity, daemon=True, name="fts-integrity-check")
        self._fts_thread.start()
        log.info("Database schema initialized: %s", self.db_path)

    def _migrate_schema(self) -> None:
        """Apply incremental schema migrations for existing databases.

        Each ALTER TABLE is guarded so it is a no-op when the column already
        exists (SQLite raises OperationalError in that case; we swallow it).
        """
        _new_columns = [
            ("typed_count", "INTEGER"),
            ("first_visit_time", "INTEGER"),
            ("transition_type", "INTEGER"),
            ("visit_duration", "REAL"),
            ("device_id", "INTEGER"),
        ]
        with self._conn() as conn:
            for col_name, col_type in _new_columns:
                try:
                    safe_col = _quote_identifier(col_name)
                    safe_type = _sanitize_col_type(col_type)
                    conn.execute(f"ALTER TABLE history ADD COLUMN {safe_col} {safe_type}")
                    log.info("Schema migration: added column history.%s", col_name)
                except sqlite3.OperationalError:
                    # Column already exists — nothing to do.
                    pass

            needs_migration = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE tags != ''").fetchone()[0]
            already_migrated = conn.execute("SELECT COUNT(*) FROM bookmark_tags").fetchone()[0]
            if needs_migration and not already_migrated:
                rows = conn.execute("SELECT id, tags FROM bookmarks WHERE tags != ''").fetchall()
                tag_rows = [(row["id"], tag.strip()) for row in rows for tag in row["tags"].split(",") if tag.strip()]
                conn.executemany(
                    "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                    tag_rows,
                )
                log.info("Schema migration: populated bookmark_tags from CSV (%d rows)", len(tag_rows))

            # Composite indexes added after initial release — CREATE IF NOT EXISTS is idempotent.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_browser_time ON history(browser_type, visit_time DESC)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_domain_time ON history(domain_id, visit_time DESC)")

    def _verify_fts_integrity(self) -> None:
        """Run an FTS5 integrity check on startup and auto-rebuild if corrupt.

        If the process previously crashed during ``upsert_records`` — after
        the FTS triggers were DROPped but before they were restored and the
        catch-up INSERT was executed — the FTS index will be silently out of
        sync with the ``history`` table.  SQLite's built-in integrity-check
        command detects this without requiring any user action; we simply
        trigger a full rebuild whenever it fails.

        This check is cheap (milliseconds on typical databases) and runs once
        per process start inside the existing schema-init call.
        """
        try:
            with self._conn() as conn:
                conn.execute("INSERT INTO history_fts(history_fts) VALUES('integrity-check')")
            log.debug("FTS integrity check passed.")
        except sqlite3.DatabaseError as exc:
            log.warning("FTS integrity check failed (%s) — triggering automatic rebuild.", exc)
            try:
                self.rebuild_fts_index()
                log.info("FTS index successfully rebuilt after integrity failure.")
            except Exception as rebuild_exc:
                log.error("FTS rebuild failed: %s", rebuild_exc)

    # ═══════════════════════════════════════════════════════════
    # Device registry CRUD
    # ═══════════════════════════════════════════════════════════

    def upsert_device(
        self,
        uuid: str,
        name: str,
        plat: str | None = None,
        app_version: str | None = None,
    ) -> int:
        """Insert or update a device row by UUID. Returns devices.id."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO devices(uuid, name, platform, app_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    name        = excluded.name,
                    platform    = COALESCE(excluded.platform, platform),
                    app_version = COALESCE(excluded.app_version, app_version)
                """,
                (uuid, name, plat, app_version),
            )
            row = conn.execute("SELECT id FROM devices WHERE uuid = ?", (uuid,)).fetchone()
        return row[0]

    def get_all_devices(self) -> list[dict]:
        """Return all device rows as plain dicts, newest first."""
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at "
                "FROM devices ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_device_by_uuid(self, uuid: str) -> dict | None:
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at FROM devices WHERE uuid = ?",
                (uuid,),
            ).fetchone()
        return dict(row) if row else None

    def get_device_by_id(self, device_id: int) -> dict | None:
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at FROM devices WHERE id = ?",
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_device(self, device_id: int, new_name: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE devices SET name = ? WHERE id = ?", (new_name, device_id))

    def update_device_last_sync(self, device_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE devices SET last_sync_at = ? WHERE id = ?",
                (int(time.time()), device_id),
            )

    def merge_device_records(self, from_id: int, to_id: int) -> int:
        """Re-assign all history rows from *from_id* to *to_id*. Returns rows updated."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE history SET device_id = ? WHERE device_id = ?",
                (to_id, from_id),
            )
            return cur.rowcount

    def delete_device(self, device_id: int) -> None:
        """Remove a device row; history rows get device_id=NULL."""
        with self._conn() as conn:
            conn.execute("UPDATE history SET device_id = NULL WHERE device_id = ?", (device_id,))
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def get_device_name_map(self) -> dict[int, str]:
        """Return {device_id: device_name} for all known devices."""
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT id, name FROM devices").fetchall()
        return {r[0]: r[1] for r in rows}

    # ── Hidden records CRUD ───────────────────────────────────

    def hide_records_by_ids(self, ids: list[int]) -> None:
        """Mark the given record ids as hidden (stored by URL for cross-device stability)."""
        if not ids:
            return
        _CHUNK = 900
        with self._conn() as conn:
            rows: list[sqlite3.Row] = []
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(conn.execute(f"SELECT url FROM history WHERE id IN ({placeholders})", chunk).fetchall())
            if rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO hidden_records(url) VALUES(?)",
                    ((r[0],) for r in rows),
                )

    def get_hidden_urls(self) -> set[str]:
        """Return the set of all hidden URLs."""
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT url FROM hidden_records").fetchall()
        return {r[0] for r in rows}

    def get_hidden_ids(self, candidate_ids: set[int] | None = None) -> set[int]:
        """Return DB ids of records whose URL is in hidden_records.

        If *candidate_ids* is provided, only those rows are checked (faster
        for the common case where we know which IDs might be affected).
        """
        if candidate_ids is not None and len(candidate_ids) == 0:
            return set()
        _CHUNK = 900
        with self._conn(write=False) as conn:
            if candidate_ids is not None:
                id_list = list(candidate_ids)
                result: set[int] = set()
                for i in range(0, len(id_list), _CHUNK):
                    chunk = id_list[i : i + _CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    rows = conn.execute(
                        f"""SELECT h.id FROM history h
                            JOIN hidden_records hr ON h.url = hr.url
                            WHERE h.id IN ({placeholders})""",
                        chunk,
                    ).fetchall()
                    result.update(r[0] for r in rows)
                return result
            rows = conn.execute(
                """SELECT h.id FROM history h
                       JOIN hidden_records hr ON h.url = hr.url"""
            ).fetchall()
        return {r[0] for r in rows}

    def clear_hidden_records(self) -> int:
        """Delete all entries from hidden_records. Returns the number removed."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM hidden_records")
            return cursor.rowcount

    # ═══════════════════════════════════════════════════════════
    # Maintenance operations
    # ═══════════════════════════════════════════════════════════

    def get_db_stats(self) -> DbStats:
        """Return a snapshot of size and content metrics (read-only)."""
        file_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        with self._conn(write=False) as conn:
            ps = conn.execute("PRAGMA page_size").fetchone()[0]
            pc = conn.execute("PRAGMA page_count").fetchone()[0]
            fpc = conn.execute("PRAGMA freelist_count").fetchone()[0]
            rc = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            dc = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]

            # FTS size: sum the compressed block payloads stored in the FTS5
            # data shadow table.  This is accurate and does not require the
            # optional dbstat virtual table.
            try:
                fts_bytes = conn.execute("SELECT COALESCE(SUM(LENGTH(block)), 0) FROM history_fts_data").fetchone()[0]
            except Exception:
                fts_bytes = 0

        return DbStats(
            file_size_bytes=file_size,
            page_count=pc,
            free_page_count=fpc,
            page_size=ps,
            record_count=rc,
            domain_count=dc,
            fts_size_bytes=fts_bytes,
        )

    def vacuum_and_analyze(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        def _cb(msg: str):
            if progress_cb:
                progress_cb(msg)
            log.info("vacuum: %s", msg)

        db_path = self.db_path
        size_before = db_path.stat().st_size if db_path.exists() else 0
        free = shutil.disk_usage(db_path.parent).free
        required = size_before * 2
        if free < required:
            raise RuntimeError(
                f"Not enough disk space for VACUUM: need {required // 1024 // 1024} MB, "
                f"have {free // 1024 // 1024} MB free."
            )
        # Close the persistent connection under the lock so no other thread can
        # acquire it while we are about to rewrite the file.  The slow VACUUM
        # itself runs outside the lock: SQLite's own file-level locking prevents
        # concurrent writers, and releasing _lock lets read-only callers (e.g.
        # search_quick via _ro_conn) proceed normally during the operation.
        with self._lock:
            self._vacuuming = True
            self._reset_conn()

        try:
            _cb(_("Checkpointing WAL into main file…"))
            conn = sqlite3.connect(str(db_path), timeout=60)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                result = conn.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()
                if result and result[0]:
                    _cb(_("⚠ WAL checkpoint partially blocked by active readers; VACUUM will handle remaining pages…"))
                conn.commit()
                conn.close()
                conn = None
            finally:
                if conn:
                    conn.close()

            size_before = db_path.stat().st_size if db_path.exists() else 0
            _cb(_("Running VACUUM — rewriting database file…"))
            conn = sqlite3.connect(str(db_path), timeout=120)
            try:
                conn.isolation_level = None
                conn.execute("VACUUM")
                conn.isolation_level = ""

                _cb(_("Restoring WAL mode and updating statistics…"))
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("ANALYZE")
                conn.commit()
            finally:
                conn.close()
        finally:
            with self._lock:
                self._vacuuming = False

        size_after = db_path.stat().st_size if db_path.exists() else 0
        saved = size_before - size_after
        if size_before:
            pct = saved / size_before * 100
            _cb(
                _("Done.  {before:.1f} MB → {after:.1f} MB  (saved {saved:.0f} KB, {pct:.1f}%)").format(
                    before=size_before / 1024 / 1024,
                    after=size_after / 1024 / 1024,
                    saved=saved / 1024,
                    pct=pct,
                )
            )
        else:
            _cb(_("Done."))
        return size_before, size_after

    def export_without_fts(self, dest: Path) -> None:
        """Export a copy of the database with FTS tables/triggers stripped.

        The exported file is a valid SQLite database containing all user data
        (history, domains, backup_stats, hidden_records) but *without* the
        history_fts virtual table or its shadow tables/triggers.  This makes
        it much smaller for upload to WebDAV.  The caller is responsible for
        deleting *dest* when done.
        """
        dest_path = dest.absolute().as_posix()
        if dest.exists():
            dest.unlink()

        with self._lock, self._conn(write=False) as conn:
            safe_path = _sanitize_vacuum_path(dest_path)
            conn.execute(f"VACUUM INTO '{safe_path}'")

        dst_conn = sqlite3.connect(dest_path, timeout=30)
        try:
            dst_conn.isolation_level = None  # autocommit for DDL and VACUUM

            # 1. Drop triggers first to avoid any issues with virtual table removal
            dst_conn.execute("DROP TRIGGER IF EXISTS history_ai")
            dst_conn.execute("DROP TRIGGER IF EXISTS history_ad")
            dst_conn.execute("DROP TRIGGER IF EXISTS history_au")

            # 2. Drop the FTS5 virtual table itself.
            dst_conn.execute("DROP TABLE IF EXISTS history_fts")

            # 3. Double-check that triggers are really gone (belt-and-suspenders)
            cursor = dst_conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'history_%'")
            for trigger_name in [row[0] for row in cursor.fetchall()]:
                dst_conn.execute(f"DROP TRIGGER IF EXISTS {_quote_identifier(trigger_name)}")

            # 4. Skip second VACUUM — the space freed by dropping FTS (typically
            #    10-20% of the DB) is reclaimed by ZIP compression in the WebDAV
            #    upload layer, so the I/O cost of rewriting the entire file again
            #    is not justified.  This halves the wall-clock time of the export.

            cursor = dst_conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'history_fts%'")
            leftovers = [row[0] for row in cursor.fetchall()]
            if leftovers:
                log.warning("FTS stripping completed with leftovers: %s", leftovers)
            else:
                log.info("FTS stripping successful: All related tables and triggers removed.")
        finally:
            dst_conn.close()

    def rebuild_fts_index(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        """Rebuild the FTS5 index from scratch to fix any stale/corrupted entries."""

        def _cb(msg: str):
            if progress_cb:
                progress_cb(msg)
            log.info("fts_rebuild: %s", msg)

        _cb(_("Rebuilding full-text search index…"))
        with self._conn() as conn:
            conn.execute("INSERT INTO history_fts(history_fts) VALUES('rebuild')")
        _cb(_("FTS index rebuild complete."))

    def normalize_domains(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> int:
        """Ensure all history rows have a valid domain_id; return rows updated."""

        def _cb(msg: str):
            if progress_cb:
                progress_cb(msg)
            log.info("normalize_domains: %s", msg)

        _cb(_("Scanning for un-normalised URLs…"))

        updated = 0
        with self._conn() as conn:
            _cb(_("Inserting new domain entries…"))
            conn.execute("""
                INSERT OR IGNORE INTO domains(host)
                SELECT DISTINCT _extract_host(url)
                FROM history
                WHERE _extract_host(url) IS NOT NULL
                  AND (domain_id IS NULL OR domain_id NOT IN (SELECT id FROM domains))
            """)

        _cb(_("Back-filling domain_id on history rows…"))
        _BATCH = 5000
        while True:
            with self._conn() as conn:
                cursor = conn.execute(
                    """
                    UPDATE history
                    SET domain_id = (
                        SELECT d.id FROM domains d
                        WHERE d.host = _extract_host(history.url)
                    )
                    WHERE rowid IN (
                        SELECT rowid FROM history WHERE domain_id IS NULL LIMIT ?
                    )
                """,
                    (_BATCH,),
                )
                batch_count = cursor.rowcount
            if batch_count == 0:
                break
            updated += batch_count
            _cb(_("Back-filling domain_id on history rows… ({n} so far)").format(n=f"{updated:,}"))

        _cb(_("Domain normalisation complete — {n} rows updated.").format(n=f"{updated:,}"))
        return updated

    # ═══════════════════════════════════════════════════════════
    # Write operations
    # ═══════════════════════════════════════════════════════════

    def replace_database(self, new_db_path: Path) -> None:
        """Safely replace the underlying SQLite file (used for WebDAV restore)."""
        if self._fts_thread is not None and self._fts_thread.is_alive():
            self._fts_thread.join(timeout=10)
        with self._lock, self._ro_lock:
            log.info("Replacing current database with %s", new_db_path)
            # Close all connections before touching the file so that
            # search_quick cannot read a partially-written DB on Windows
            # (which disallows overwriting open files) or any platform.
            # Inline the _pconn reset here; inline the _ro_conn reset too
            # since we already hold _ro_lock and _reset_conn would deadlock.
            if self._pconn is not None:
                try:
                    self._pconn.close()
                except Exception:
                    pass
                self._pconn = None
            if self._ro_conn is not None:
                try:
                    self._ro_conn.close()
                except Exception:
                    pass
                self._ro_conn = None
            self._schema_initialized = False
            for suffix in ("-wal", "-shm"):
                p = self.db_path.with_name(self.db_path.name + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError as exc:
                        log.warning("Failed to delete %s: %s", p.name, exc)
            shutil.copy2(new_db_path, self.db_path)
            log.info("Database successfully replaced")

    def merge_from_db(
        self,
        src_path: Path,
        progress_cb: Callable[[str], None] | None = None,
        include_user_data: bool = True,
    ) -> int:
        """Merge history records from *src_path* into this database.

        Rows are streamed from the source in batches of ``DB_BATCH_SIZE`` to
        avoid loading the entire backup into memory at once.

        When *include_user_data* is ``True`` (the default), bookmarks,
        annotations, hidden_records, and tombstones are also merged by calling
        :meth:`merge_user_data_from_db` automatically.  Pass ``False`` only
        when you need to merge history alone (e.g. plain import without user
        data).
        """

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)
            log.info("merge_from_db: %s", msg)

        _cb(_("Opening backup database for merge..."))
        src_conn = sqlite3.connect(str(src_path), timeout=30)
        src_conn.row_factory = sqlite3.Row
        try:
            integrity = src_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"Backup database failed integrity check: {integrity}")
            # Collect remote tombstones so we don't resurrect remotely-deleted records
            try:
                remote_deleted = src_conn.execute("SELECT url, deleted_at FROM deleted_records").fetchall()
            except sqlite3.OperationalError:
                remote_deleted = []
            # Collect remote devices for ID remapping
            try:
                remote_devices = src_conn.execute(
                    "SELECT id, uuid, name, platform, app_version FROM devices"
                ).fetchall()
            except sqlite3.OperationalError:
                remote_devices = []

            # Build remote_device_id -> local_device_id map before streaming rows
            remote_to_local_id: dict[int, int] = {}
            for dev in remote_devices:
                local_id = self.upsert_device(
                    uuid=dev["uuid"],
                    name=dev["name"],
                    plat=dev["platform"],
                    app_version=dev["app_version"],
                )
                remote_to_local_id[dev["id"]] = local_id

            total_src: int = src_conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            _cb(_("Merging {n} records from backup...").format(n=total_src))

            _remote_deleted_urls = {r[0] for r in remote_deleted}

            # Read local tombstones before streaming so we can skip already-deleted
            # URLs during batch construction, avoiding a write-then-delete FTS churn.
            with self._conn(write=False) as _ro:
                try:
                    _local_deleted_urls: set[str] = {
                        r[0] for r in _ro.execute("SELECT url FROM deleted_records").fetchall()
                    }
                except sqlite3.OperationalError:
                    _local_deleted_urls = set()

            _skip_urls = _remote_deleted_urls | _local_deleted_urls

            cursor = src_conn.execute(
                "SELECT url, title, visit_time, visit_count, browser_type, profile_name, "
                "metadata, typed_count, first_visit_time, transition_type, visit_duration, "
                "device_id "
                "FROM history"
            )

            inserted = 0
            while True:
                raw_batch = cursor.fetchmany(DB_BATCH_SIZE)
                if not raw_batch:
                    break
                records = [
                    HistoryRecord(
                        url=r["url"],
                        title=r["title"] or "",
                        visit_time=r["visit_time"],
                        visit_count=r["visit_count"] or 1,
                        browser_type=r["browser_type"],
                        profile_name=r["profile_name"] or "",
                        metadata=r["metadata"] or "",
                        typed_count=r["typed_count"],
                        first_visit_time=r["first_visit_time"],
                        transition_type=r["transition_type"],
                        visit_duration=r["visit_duration"],
                        device_id=remote_to_local_id.get(r["device_id"]) if r["device_id"] is not None else None,
                    )
                    for r in raw_batch
                    if r["url"] not in _skip_urls
                ]
                inserted += self.upsert_records(records)

        finally:
            src_conn.close()

        # Absorb remote tombstones only when merging full user data.
        # Persisting tombstones during a plain import (include_user_data=False)
        # would silently block those URLs from being re-imported in the future.
        if include_user_data and remote_deleted:
            with self._conn() as conn:
                conn.executemany(
                    "INSERT INTO deleted_records(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r[0], r[1]) for r in remote_deleted),
                )

        _cb(
            _("Merge complete: {inserted} new records added (of {total} in backup).").format(
                inserted=inserted, total=total_src
            )
        )
        if include_user_data:
            self.merge_user_data_from_db(src_path, progress_cb=progress_cb)
        return inserted

    def merge_user_data_from_db(
        self,
        src_path: Path,
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        """Merge bookmarks, annotations, hidden_records, and tombstones from *src_path*.

        All auto-increment IDs (history_id, bookmark_id) are re-resolved against
        local tables by URL — remote integer IDs are never copied directly.
        """

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)
            log.info("merge_user_data: %s", msg)

        _cb(_("Merging user data (bookmarks, annotations, hidden records)..."))

        src_conn = sqlite3.connect(str(src_path), timeout=30)
        src_conn.row_factory = sqlite3.Row
        try:

            def _safe_fetch(query: str) -> list:
                try:
                    return src_conn.execute(query).fetchall()
                except sqlite3.OperationalError:
                    return []

            remote_deleted_records = _safe_fetch("SELECT url, deleted_at FROM deleted_records")
            remote_deleted_bookmarks = _safe_fetch("SELECT url, deleted_at FROM deleted_bookmarks")
            remote_deleted_annots = _safe_fetch("SELECT url, deleted_at FROM deleted_annotations")
            remote_hidden = _safe_fetch("SELECT url FROM hidden_records")
            remote_bookmarks = _safe_fetch("SELECT url, title, tags, bookmarked_at FROM bookmarks")
            # Build url→tags map from bookmark_tags (preferred) falling back to legacy tags column
            try:
                remote_bm_tags = _safe_fetch(
                    "SELECT b.url, bt.tag FROM bookmark_tags bt JOIN bookmarks b ON b.id = bt.bookmark_id"
                )
            except sqlite3.OperationalError:
                remote_bm_tags = []
            remote_annotations = _safe_fetch("SELECT url, note, created_at, updated_at FROM annotations")
        finally:
            src_conn.close()

        with self._conn() as conn:
            # 1. Merge tombstones first
            if remote_deleted_records:
                conn.executemany(
                    "INSERT INTO deleted_records(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r["url"], r["deleted_at"]) for r in remote_deleted_records),
                )
            if remote_deleted_bookmarks:
                conn.executemany(
                    "INSERT INTO deleted_bookmarks(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r["url"], r["deleted_at"]) for r in remote_deleted_bookmarks),
                )
            if remote_deleted_annots:
                conn.executemany(
                    "INSERT INTO deleted_annotations(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r["url"], r["deleted_at"]) for r in remote_deleted_annots),
                )

            # 2. Apply history tombstones
            conn.execute("DELETE FROM history WHERE url IN (SELECT url FROM deleted_records)")

            # 3. Merge hidden_records
            if remote_hidden:
                conn.executemany(
                    "INSERT OR IGNORE INTO hidden_records(url) VALUES(?)",
                    ((r["url"],) for r in remote_hidden),
                )

            # 4. Merge bookmarks (skip tombstoned urls, keep newer bookmarked_at)
            deleted_bm_urls: set[str] = {r[0] for r in conn.execute("SELECT url FROM deleted_bookmarks").fetchall()}
            # Track urls where remote won (bookmarked_at was newer) so we can replace tags atomically
            tag_replace_urls: set[str] = set()

            # Pre-fetch history_id and existing bookmarked_at for all remote bookmark URLs in bulk
            remote_bm_urls = [bm["url"] for bm in remote_bookmarks if bm["url"] not in deleted_bm_urls]
            history_id_map: dict[str, int] = {}
            existing_bm_map: dict[str, int] = {}
            for _i in range(0, max(len(remote_bm_urls), 1), 900):
                _chunk = remote_bm_urls[_i : _i + 900]
                if not _chunk:
                    break
                _ph = ",".join("?" * len(_chunk))
                history_id_map.update(
                    (r["url"], r["id"])
                    for r in conn.execute(
                        f"SELECT url, id FROM history WHERE url IN ({_ph})",
                        _chunk,
                    ).fetchall()
                )
                existing_bm_map.update(
                    (r["url"], r["bookmarked_at"])
                    for r in conn.execute(
                        f"SELECT url, bookmarked_at FROM bookmarks WHERE url IN ({_ph})",
                        _chunk,
                    ).fetchall()
                )

            for bm in remote_bookmarks:
                url = bm["url"]
                if url in deleted_bm_urls:
                    continue
                history_id = history_id_map.get(url)
                remote_ts = bm["bookmarked_at"]
                existing_ts = existing_bm_map.get(url)
                if existing_ts is None or remote_ts > existing_ts:
                    # Remote is newer (or new insert) — upsert and mark for tag replacement
                    conn.execute(
                        """INSERT INTO bookmarks(url, title, tags, bookmarked_at, history_id)
                           VALUES(?, ?, ?, ?, ?)
                           ON CONFLICT(url) DO UPDATE SET
                               title         = excluded.title,
                               tags          = excluded.tags,
                               bookmarked_at = excluded.bookmarked_at,
                               history_id    = COALESCE(excluded.history_id, history_id)""",
                        (url, bm["title"] or "", bm["tags"] or "", remote_ts, history_id),
                    )
                    tag_replace_urls.add(url)

            # 5. Merge bookmark_tags atomically: replace all tags for bookmarks where remote won
            # Build a map of url -> [tags] from remote
            remote_tags_by_url: dict[str, list[str]] = {}
            for bt in remote_bm_tags:
                remote_tags_by_url.setdefault(bt["url"], []).append(bt["tag"])

            # Pre-fetch bookmark ids for all tag_replace_urls in bulk
            bm_id_map: dict[str, int] = {}
            if tag_replace_urls:
                _tag_url_list = list(tag_replace_urls)
                for _i in range(0, len(_tag_url_list), 900):
                    _chunk = _tag_url_list[_i : _i + 900]
                    _ph2 = ",".join("?" * len(_chunk))
                    bm_id_map.update(
                        (r["url"], r["id"])
                        for r in conn.execute(
                            f"SELECT url, id FROM bookmarks WHERE url IN ({_ph2})",
                            _chunk,
                        ).fetchall()
                    )

            for url in tag_replace_urls:
                bm_id = bm_id_map.get(url)
                if not bm_id:
                    continue
                # Atomically replace: delete existing tags, insert remote tags
                conn.execute("DELETE FROM bookmark_tags WHERE bookmark_id=?", (bm_id,))
                for tag in remote_tags_by_url.get(url, []):
                    conn.execute(
                        "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                        (bm_id, tag),
                    )

            # 6. Merge annotations (skip tombstoned urls, keep newer updated_at)
            deleted_ann_urls: set[str] = {r[0] for r in conn.execute("SELECT url FROM deleted_annotations").fetchall()}

            # Pre-fetch history ids for all annotation urls in bulk
            ann_urls = [ann["url"] for ann in remote_annotations if ann["url"] not in deleted_ann_urls]
            ann_history_id_map: dict[str, int] = {}
            for _i in range(0, max(len(ann_urls), 1), 900):
                _chunk = ann_urls[_i : _i + 900]
                if not _chunk:
                    break
                _ph3 = ",".join("?" * len(_chunk))
                ann_history_id_map.update(
                    (r["url"], r["id"])
                    for r in conn.execute(
                        f"SELECT url, id FROM history WHERE url IN ({_ph3})",
                        _chunk,
                    ).fetchall()
                )

            for ann in remote_annotations:
                url = ann["url"]
                if url in deleted_ann_urls:
                    continue
                history_id = ann_history_id_map.get(url)
                conn.execute(
                    """INSERT INTO annotations(url, note, created_at, updated_at, history_id)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(url) DO UPDATE SET
                           note       = CASE WHEN excluded.updated_at > updated_at
                                             THEN excluded.note ELSE note END,
                           updated_at = CASE WHEN excluded.updated_at > updated_at
                                             THEN excluded.updated_at ELSE updated_at END,
                           history_id = COALESCE(excluded.history_id, history_id)""",
                    (url, ann["note"] or "", ann["created_at"], ann["updated_at"], history_id),
                )

        _cb(_("User data merge complete."))

    def upsert_records(self, records: list[HistoryRecord]) -> int:
        if not records:
            return 0

        # Pre-compute host for every record once in Python (avoids per-row UDF round-trip)
        rec_hosts = [_extract_url_host(r.url) for r in records]

        with self._conn() as conn:
            # 1. Bulk-insert any new domains
            hosts = {h for h in rec_hosts if h}
            if hosts:
                conn.executemany(
                    "INSERT OR IGNORE INTO domains(host) VALUES(?)",
                    ((h,) for h in hosts),
                )

            # 2. Fetch the full host→id map in one query so we never need a
            #    per-row subquery back into SQLite from Python.
            host_to_id: dict[str, int] = {}
            if hosts:
                placeholders = ",".join("?" * len(hosts))
                rows = conn.execute(
                    f"SELECT host, id FROM domains WHERE host IN ({placeholders})",
                    list(hosts),
                ).fetchall()
                host_to_id = {row[0]: row[1] for row in rows}

            # 3. Snapshot the current max history id so we can sync FTS for
            #    only the newly inserted rows afterwards.
            max_id_before: int = conn.execute("SELECT COALESCE(MAX(id), 0) FROM history").fetchone()[0]

            # 4-8. Wrap the trigger DDL + bulk insert + FTS sync in a SAVEPOINT
            #      so a mid-operation crash leaves the DB consistent (triggers
            #      still present, no partial inserts).  We use individual
            #      execute() calls instead of executescript() because
            #      executescript() issues an implicit COMMIT which would exit
            #      the savepoint prematurely.
            # For small batches the DDL overhead of DROP/CREATE triggers exceeds
            # the per-row FTS cost, so we only disable triggers for large batches.
            _disable_triggers = len(records) > 200

            conn.execute("SAVEPOINT upsert_batch")
            try:
                # 4. Temporarily drop FTS triggers to avoid per-row FTS overhead
                #    during bulk insert; a single targeted sync follows instead.
                #    Skipped for small batches where DDL cost outweighs the saving.
                if _disable_triggers:
                    conn.execute("DROP TRIGGER IF EXISTS history_ai")
                    conn.execute("DROP TRIGGER IF EXISTS history_ad")
                    conn.execute("DROP TRIGGER IF EXISTS history_au")

                # 4b. Pre-capture rows that will be touched by DO UPDATE so we
                #     have their OLD content for the FTS 'delete' command later.
                #     FTS5 external-content 'delete' must receive the pre-update
                #     values; querying after the upsert would return new values and
                #     leave old tokens as ghost entries in the inverted index.
                old_fts_rows: list[tuple] = []
                if _disable_triggers and records:
                    conn.execute(
                        "CREATE TEMP TABLE IF NOT EXISTS _upsert_keys "
                        "(browser_type TEXT, url TEXT, visit_time INTEGER, "
                        " PRIMARY KEY (browser_type, url, visit_time))"
                    )
                    conn.execute("DELETE FROM _upsert_keys")
                    conn.executemany(
                        "INSERT OR IGNORE INTO _upsert_keys VALUES (?, ?, ?)",
                        ((r.browser_type, r.url, r.visit_time) for r in records),
                    )
                    old_fts_rows = conn.execute(
                        "SELECT h.id, h.url, h.title FROM history h "
                        "JOIN _upsert_keys k "
                        "  ON h.browser_type = k.browser_type "
                        " AND h.url          = k.url "
                        " AND h.visit_time   = k.visit_time "
                        "WHERE h.id <= ?",
                        (max_id_before,),
                    ).fetchall()
                    conn.execute("DROP TABLE IF EXISTS _upsert_keys")

                # 5. Bulk insert history records using plain positional params
                #    (no subquery, no UDF call per row).
                sql = """
                    INSERT INTO history
                        (url, title, visit_time, visit_count,
                         browser_type, profile_name, metadata, domain_id,
                         typed_count, first_visit_time, transition_type, visit_duration,
                         device_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(browser_type, url, visit_time) DO UPDATE SET
                        title            = CASE WHEN excluded.title != '' THEN excluded.title
                                               ELSE title END,
                        visit_count      = CASE WHEN excluded.visit_count > visit_count THEN excluded.visit_count
                                               ELSE visit_count END,
                        typed_count      = COALESCE(excluded.typed_count, typed_count),
                        first_visit_time = COALESCE(excluded.first_visit_time, first_visit_time),
                        transition_type  = COALESCE(excluded.transition_type, transition_type),
                        visit_duration   = COALESCE(excluded.visit_duration, visit_duration),
                        device_id        = COALESCE(device_id, excluded.device_id)
                """
                for i in range(0, len(records), DB_BATCH_SIZE):
                    batch = records[i : i + DB_BATCH_SIZE]
                    params = [
                        (
                            r.url,
                            r.title,
                            r.visit_time,
                            r.visit_count,
                            r.browser_type,
                            r.profile_name,
                            r.metadata,
                            host_to_id.get(rec_hosts[i + j]),
                            r.typed_count,
                            r.first_visit_time,
                            r.transition_type,
                            r.visit_duration,
                            r.device_id,
                        )
                        for j, r in enumerate(batch)
                    ]
                    conn.executemany(sql, params)

                # 6. Count truly new rows using the id watermark (ON CONFLICT DO UPDATE
                #    reports rowcount=1 for both inserts and updates, so rowcount is unreliable).
                inserted: int = conn.execute("SELECT COUNT(*) FROM history WHERE id > ?", (max_id_before,)).fetchone()[
                    0
                ]

                # 7. Restore FTS triggers (only if they were dropped).
                if _disable_triggers:
                    conn.execute(
                        "CREATE TRIGGER IF NOT EXISTS history_ai AFTER INSERT ON history BEGIN"
                        " INSERT INTO history_fts(rowid, url, title) VALUES (new.id, new.url, new.title);"
                        " END"
                    )
                    conn.execute(
                        "CREATE TRIGGER IF NOT EXISTS history_ad AFTER DELETE ON history BEGIN"
                        " INSERT INTO history_fts(history_fts, rowid, url, title)"
                        " VALUES('delete', old.id, old.url, old.title);"
                        " END"
                    )
                    conn.execute(
                        "CREATE TRIGGER IF NOT EXISTS history_au AFTER UPDATE ON history BEGIN"
                        " INSERT INTO history_fts(history_fts, rowid, url, title)"
                        " VALUES('delete', old.id, old.url, old.title);"
                        " INSERT INTO history_fts(rowid, url, title) VALUES (new.id, new.url, new.title);"
                        " END"
                    )

                # 8. Batch-sync FTS for the trigger-free window.
                #    Only needed when triggers were disabled; when triggers were
                #    active they already kept FTS up to date during insert.
                #
                #    Two populations need to be covered:
                #      a) Newly inserted rows  (id > max_id_before): simple INSERT into FTS.
                #      b) Updated rows         (id <= max_id_before, touched by DO UPDATE):
                #         FTS still holds the old content — we must delete the stale entry
                #         and re-insert the current one.
                #
                #    We identify updated rows by matching on the dedup key
                #    (browser_type, url, visit_time) from the input batch against
                #    pre-existing history rows.  This is precise and avoids a full
                #    FTS rebuild.

                if _disable_triggers:
                    # 8a. Insert FTS entries for genuinely new rows.
                    conn.execute(
                        "INSERT INTO history_fts(rowid, url, title) SELECT id, url, title FROM history WHERE id > ?",
                        (max_id_before,),
                    )

                # 8b. Refresh FTS for updated rows (pre-existing rows whose content
                #     may have changed due to DO UPDATE).  We gather their ids via
                #     a join on the dedup key, then do a delete+re-insert in FTS.
                #
                #     This block must only run when triggers were disabled (large
                #     batches).  When triggers are active the history_au trigger
                #     already performed the identical delete+re-insert during the
                #     ON CONFLICT DO UPDATE; executing it a second time would
                #     create duplicate FTS entries and cause search results to
                #     appear multiple times.
                if _disable_triggers and old_fts_rows:
                    # Delete stale FTS entries using OLD pre-update content.
                    # FTS5 'delete' must receive the values that were indexed;
                    # old_fts_rows was captured before the upsert for exactly this.
                    conn.executemany(
                        "INSERT INTO history_fts(history_fts, rowid, url, title) VALUES('delete', ?, ?, ?)",
                        ((row[0], row[1], row[2]) for row in old_fts_rows),
                    )
                    # Re-insert using current (post-update) content.
                    id_placeholders = ",".join("?" * len(old_fts_rows))
                    new_rows = conn.execute(
                        f"SELECT id, url, title FROM history WHERE id IN ({id_placeholders})",
                        [row[0] for row in old_fts_rows],
                    ).fetchall()
                    conn.executemany(
                        "INSERT INTO history_fts(rowid, url, title) VALUES (?, ?, ?)",
                        ((row[0], row[1], row[2]) for row in new_rows),
                    )

                conn.execute("RELEASE upsert_batch")
            except Exception:
                conn.execute("ROLLBACK TO upsert_batch")
                conn.execute("RELEASE upsert_batch")
                raise

        log.info("Upserted %d / %d records", inserted, len(records))
        return inserted

    def update_backup_stats(
        self,
        browser_type: str,
        profile_name: str,
        records_synced: int,
    ) -> None:
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO backup_stats
                    (browser_type, profile_name, first_backup_time, last_backup_time, total_records_synced)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(browser_type, profile_name) DO UPDATE SET
                    last_backup_time     = excluded.last_backup_time,
                    total_records_synced = total_records_synced + excluded.total_records_synced
            """,
                (browser_type, profile_name, now, now, records_synced),
            )

    # ═══════════════════════════════════════════════════════════
    # Read operations
    # ═══════════════════════════════════════════════════════════

    def get_total_count(self) -> int:
        with self._conn(write=False) as conn:
            row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
            return row[0] if row else 0

    def get_max_visit_times(self, browser_type: str) -> dict[str, int]:
        with self._conn(write=False) as conn:
            rows = conn.execute(
                """
                SELECT profile_name, MAX(visit_time) AS max_t
                FROM history
                WHERE browser_type = ?
                GROUP BY profile_name
                """,
                (browser_type,),
            ).fetchall()
        return {r["profile_name"]: r["max_t"] for r in rows if r["max_t"] is not None}

    # ── excluded_ids helpers ──────────────────────────────────

    def _populate_excl_table(self, conn: sqlite3.Connection, excl: set[int]) -> bool:
        if not excl:
            return False
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _excl_ids (id INTEGER PRIMARY KEY)")
        # Skip the expensive DELETE + re-insert when the set hasn't changed since
        # the last call on this connection (common in UI scroll / pagination).
        with self._excl_cache_lock:
            cached: set[int] | None = self._excl_cache.get(id(conn))
            if cached != excl:
                conn.execute("DELETE FROM _excl_ids")
                conn.executemany("INSERT OR IGNORE INTO _excl_ids VALUES(?)", ((i,) for i in excl))
                self._excl_cache[id(conn)] = frozenset(excl)
        return True

    @staticmethod
    def _excl_clause(alias: str = "") -> str:
        col = f"{alias}id" if alias else "id"
        return f"{col} NOT IN (SELECT id FROM _excl_ids)"

    def get_records_regex_iter(
        self,
        pattern: re.Pattern,
        batch_size: int = 1000,
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        excluded_ids: set[int] | None = None,
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
    ) -> Iterator[HistoryRecord]:
        """Incremental regex search iterator backed by a SQL REGEXP filter.

        The REGEXP function is registered on the connection so filtering happens
        inside SQLite, avoiding full-table deserialisation into Python objects.
        Results are streamed in batches to bound memory usage.

        Args:
            pattern: Compiled regex pattern to match against.
            batch_size: Number of records to fetch per SQL query.
            Other args: Same as get_records() for filtering candidates.

        Yields:
            HistoryRecord: Each record that matches the regex pattern.
        """
        pat_str = pattern.pattern
        if title_only:
            regex_cond = "h.title REGEXP ?"
            regex_params: list = [pat_str]
        elif url_only:
            regex_cond = "h.url REGEXP ?"
            regex_params = [pat_str]
        else:
            regex_cond = "(h.title REGEXP ? OR h.url REGEXP ?)"
            regex_params = [pat_str, pat_str]

        excl = excluded_ids or set()
        _COLS = (
            "h.id, h.url, h.title, h.visit_time, h.visit_count, "
            "h.browser_type, h.profile_name, h.metadata, "
            "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
            "h.device_id, d.host AS domain"
        )

        # Hold the connection for the entire iteration to avoid lock contention
        with self._conn(write=False) as conn:
            from_where, base_params, _ = self._build_query_parts(
                conn=conn,
                keyword="",
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=False,
                url_only=False,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                _force_like=False,
                device_ids=device_ids,
            )
            connector = " AND " if "WHERE" in from_where else " WHERE "
            sql = f"SELECT {_COLS} {from_where}{connector}{regex_cond} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"

            offset = 0
            while True:
                params = base_params + regex_params + [batch_size, offset]
                rows = conn.execute(sql, params).fetchall()

                for row in rows:
                    yield self._row_to_record(row)

                offset += batch_size
                if len(rows) < batch_size:
                    break

    # ── Query builder (shared core) ───────────────────────────

    def _build_query_parts(
        self,
        conn: sqlite3.Connection,
        keyword: str,
        browser_type: str,
        date_from: int | None,
        date_to: int | None,
        excluded_ids: set[int],
        domain_ids: list[int] | None,
        excludes: list[str] | None,
        title_only: bool,
        url_only: bool,
        bookmarked_only: bool,
        has_annotation: bool,
        bookmark_tag: str,
        _force_like: bool,
        device_ids: list[int] | None = None,
    ) -> tuple[str, list, bool]:
        """Build the shared FROM/WHERE fragment used by both get_records and get_filtered_count.

        Returns ``(from_where_sql, params, use_fts)`` where *from_where_sql* is
        everything from ``FROM history h …`` up to (but not including) any
        ORDER BY / LIMIT clause.  Callers prepend their own SELECT projection.

        ``use_fts`` is True when the FTS join is active so callers that need to
        handle FTS fallback can detect it without re-inspecting the SQL string.
        """
        # ── Bookmark / annotation JOINs ───────────────────────
        bm_joins: str = ""
        bm_conditions: list[str] = []
        bm_params_prefix: list = []
        if bookmarked_only or bookmark_tag:
            bm_joins = " JOIN bookmarks bm ON h.url = bm.url"
            if bookmark_tag:
                bm_joins += " JOIN bookmark_tags bt ON bm.id = bt.bookmark_id"
                bm_conditions.append("LOWER(bt.tag) = LOWER(?)")
                bm_params_prefix.append(bookmark_tag)
        if has_annotation:
            bm_joins += " JOIN annotations ann ON h.url = ann.url AND ann.note != ''"

        # ── Populate excluded-ids temp table ──────────────────
        self._populate_excl_table(conn, excluded_ids)

        use_fts = False
        extra_conditions: list[str] = []
        params: list = []

        if keyword:
            # FTS5 trigram tokenizer cannot index tokens shorter than 3 characters,
            # so any individual word under that threshold would return no results.
            # Force LIKE path when any word in the keyword is shorter than 3 chars.
            use_fts = not _force_like and _keyword_eligible_for_fts(keyword)
            if use_fts:
                from_where = (
                    "FROM history h\n    JOIN history_fts fts ON h.id = fts.rowid\n    WHERE history_fts MATCH ?"
                )
                fts_keyword = keyword
                if title_only:
                    fts_keyword = f"title:{keyword}"
                elif url_only:
                    fts_keyword = f"url:{keyword}"
                params = [_build_fts_query(fts_keyword)]
            else:
                like_pat = f"%{_escape_like(keyword)}%"
                if title_only:
                    from_where = "FROM history h\n    WHERE h.title LIKE ? ESCAPE '\\'"
                    params = [like_pat]
                elif url_only:
                    from_where = "FROM history h\n    WHERE h.url LIKE ? ESCAPE '\\'"
                    params = [like_pat]
                else:
                    from_where = "FROM history h\n    WHERE (h.url LIKE ? ESCAPE '\\' OR h.title LIKE ? ESCAPE '\\')"
                    params = [like_pat, like_pat]
        else:
            from_where = "FROM history h"

        # ── Common filter conditions ───────────────────────────
        if browser_type:
            extra_conditions.append("h.browser_type = ?")
            params.append(browser_type)
        if date_from is not None:
            extra_conditions.append("h.visit_time >= ?")
            params.append(date_from)
        if date_to is not None:
            extra_conditions.append("h.visit_time <= ?")
            params.append(date_to)
        if domain_ids:
            placeholders = ",".join("?" * len(domain_ids))
            extra_conditions.append(f"h.domain_id IN ({placeholders})")
            params.extend(domain_ids)
        if device_ids:
            placeholders = ",".join("?" * len(device_ids))
            extra_conditions.append(f"h.device_id IN ({placeholders})")
            params.extend(device_ids)
        if excludes:
            for ex in excludes:
                extra_conditions.append("h.url NOT LIKE ? ESCAPE '\\' AND h.title NOT LIKE ? ESCAPE '\\'")
                params.extend([f"%{_escape_like(ex)}%", f"%{_escape_like(ex)}%"])
        if excluded_ids:
            extra_conditions.append(self._excl_clause("h."))

        # ── Inject bookmark/annotation JOIN into FROM clause ───
        if bm_joins:
            from_where = from_where.replace("FROM history h", f"FROM history h{bm_joins}", 1)
            extra_conditions = bm_conditions + extra_conditions
            params = bm_params_prefix + params

        # ── Append extra conditions to WHERE clause ────────────
        if extra_conditions:
            connector = " AND " if "WHERE" in from_where else " WHERE "
            from_where += connector + " AND ".join(extra_conditions)

        # ── Inject domains JOIN so callers can SELECT d.host AS domain ──
        # Placed after WHERE injection so it never disturbs condition building.
        # LEFT JOIN is safe even when domain_id IS NULL (host will be NULL).
        from_where = from_where.replace(
            "FROM history h",
            "FROM history h LEFT JOIN domains d ON h.domain_id = d.id",
            1,
        )

        return from_where, params, use_fts

    # ── Public query methods ──────────────────────────────────

    def get_records(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        limit: int = 200,
        offset: int = 0,
        excluded_ids: set[int] | None = None,
        # Extended search params
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        use_regex: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
        _force_like: bool = False,  # Internal use for FTS fallback
    ) -> list[HistoryRecord]:
        excl = excluded_ids or set()

        if use_regex and keyword:
            try:
                prog = re.compile(keyword, re.IGNORECASE)
            except Exception as exc:
                log.warning("Invalid regex '%s': %s", keyword, exc)
                return []

            iter_obj = self.get_records_regex_iter(
                pattern=prog,
                batch_size=1000,
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                device_ids=device_ids,
            )
            results = []
            match_count = 0
            for record in iter_obj:
                match_count += 1
                if match_count <= offset:
                    continue
                results.append(record)
                if len(results) >= limit:
                    break
            return results

        _COLS = (
            "h.id, h.url, h.title, h.visit_time, h.visit_count, "
            "h.browser_type, h.profile_name, h.metadata, "
            "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
            "h.device_id, d.host AS domain"
        )
        with self._conn(write=False) as conn:
            from_where, params, _use_fts = self._build_query_parts(
                conn=conn,
                keyword=keyword,
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                _force_like=_force_like,
                device_ids=device_ids,
            )
            sql = f"SELECT {_COLS} {from_where} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                if "fts5" in str(exc).lower() and not _force_like:
                    return self.get_records(
                        keyword=keyword,
                        browser_type=browser_type,
                        date_from=date_from,
                        date_to=date_to,
                        limit=limit,
                        offset=offset,
                        excluded_ids=excl,
                        domain_ids=domain_ids,
                        excludes=excludes,
                        title_only=title_only,
                        url_only=url_only,
                        use_regex=False,
                        device_ids=device_ids,
                        bookmarked_only=bookmarked_only,
                        has_annotation=has_annotation,
                        bookmark_tag=bookmark_tag,
                        _force_like=True,
                    )
                raise
        return [self._row_to_record(r) for r in rows]

    def get_visit_time_at_offset(
        self,
        offset: int,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        excluded_ids: set[int] | None = None,
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
    ) -> int | None:
        """Return only the visit_time of the record at *offset* in the current
        filtered result set.  Much cheaper than get_records() for scroll-bubble
        updates because it fetches a single integer instead of full rows."""
        excl = excluded_ids or set()
        with self._conn(write=False) as conn:
            from_where, params, _ = self._build_query_parts(
                conn=conn,
                keyword=keyword,
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                _force_like=False,
                device_ids=device_ids,
            )
            sql = f"SELECT h.visit_time {from_where} ORDER BY h.visit_time DESC LIMIT 1 OFFSET ?"
            params.append(offset)
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def get_filtered_count(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        excluded_ids: set[int] | None = None,
        # Extended search params
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
        _force_like: bool = False,  # Internal use for FTS fallback
    ) -> int:
        excl = excluded_ids or set()

        with self._conn(write=False) as conn:
            from_where, params, _use_fts = self._build_query_parts(
                conn=conn,
                keyword=keyword,
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                _force_like=_force_like,
                device_ids=device_ids,
            )
            sql = f"SELECT COUNT(*) {from_where}"
            try:
                row = conn.execute(sql, params).fetchone()
            except sqlite3.OperationalError as exc:
                if "fts5" in str(exc).lower() and not _force_like:
                    return self.get_filtered_count(
                        keyword=keyword,
                        browser_type=browser_type,
                        date_from=date_from,
                        date_to=date_to,
                        excluded_ids=excl,
                        domain_ids=domain_ids,
                        excludes=excludes,
                        title_only=title_only,
                        url_only=url_only,
                        bookmarked_only=bookmarked_only,
                        has_annotation=has_annotation,
                        bookmark_tag=bookmark_tag,
                        device_ids=device_ids,
                        _force_like=True,
                    )
                raise
            return row[0] if row else 0

    # ── Bookmark CRUD ─────────────────────────────────────────

    def add_bookmark(self, url: str, title: str, tags: list[str], history_id: int | None = None) -> BookmarkRecord:
        """Insert or replace a bookmark. Returns the stored record."""
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO bookmarks(url, title, tags, bookmarked_at, history_id)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       title=excluded.title,
                       tags=excluded.tags,
                       bookmarked_at=excluded.bookmarked_at,
                       history_id=excluded.history_id""",
                (url, title, tags_str, now, history_id),
            )
            row = conn.execute("SELECT id, bookmarked_at FROM bookmarks WHERE url=?", (url,)).fetchone()
            bm_id = row["id"]
            # Sync bookmark_tags: replace all tags for this bookmark atomically
            conn.execute("DELETE FROM bookmark_tags WHERE bookmark_id = ?", (bm_id,))
            if clean_tags:
                conn.executemany(
                    "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                    ((bm_id, tag) for tag in clean_tags),
                )
        return BookmarkRecord(
            id=bm_id,
            url=url,
            title=title,
            tags=clean_tags,
            bookmarked_at=row["bookmarked_at"],
            history_id=history_id,
        )

    def remove_bookmark(self, url: str) -> bool:
        """Delete a bookmark by URL. Returns True if something was deleted."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO deleted_bookmarks(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                (url,),
            )
            cur = conn.execute("DELETE FROM bookmarks WHERE url=?", (url,))
            return cur.rowcount > 0

    def get_bookmark(self, url: str) -> BookmarkRecord | None:
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT id, url, title, bookmarked_at, history_id FROM bookmarks WHERE url=?", (url,)
            ).fetchone()
            if row is None:
                return None
            tag_rows = conn.execute("SELECT tag FROM bookmark_tags WHERE bookmark_id = ?", (row["id"],)).fetchall()
        return BookmarkRecord(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            tags=[r["tag"] for r in tag_rows],
            bookmarked_at=row["bookmarked_at"],
            history_id=row["history_id"],
        )

    def is_bookmarked(self, url: str) -> bool:
        with self._conn(write=False) as conn:
            row = conn.execute("SELECT 1 FROM bookmarks WHERE url=?", (url,)).fetchone()
        return row is not None

    def get_bookmarked_urls(self) -> set[str]:
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT url FROM bookmarks").fetchall()
        return {r[0] for r in rows}

    def get_all_bookmarks(self, tag: str = "") -> list[BookmarkRecord]:
        with self._conn(write=False) as conn:
            if tag:
                # Filter by tag via JOIN, then LEFT JOIN again to collect all tags per bookmark.
                rows = conn.execute(
                    """SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt2.tag, ',') AS tags
                       FROM bookmarks b
                       JOIN bookmark_tags bt  ON b.id = bt.bookmark_id  AND bt.tag = ?
                       LEFT JOIN bookmark_tags bt2 ON b.id = bt2.bookmark_id
                       GROUP BY b.id
                       ORDER BY b.bookmarked_at DESC""",
                    (tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt.tag, ',') AS tags
                       FROM bookmarks b
                       LEFT JOIN bookmark_tags bt ON b.id = bt.bookmark_id
                       GROUP BY b.id
                       ORDER BY b.bookmarked_at DESC"""
                ).fetchall()
        return [
            BookmarkRecord(
                id=r["id"],
                url=r["url"],
                title=r["title"],
                tags=r["tags"].split(",") if r["tags"] else [],
                bookmarked_at=r["bookmarked_at"],
                history_id=r["history_id"],
            )
            for r in rows
        ]

    def get_all_bookmark_tags(self) -> list[str]:
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT DISTINCT tag FROM bookmark_tags ORDER BY tag").fetchall()
        return [r[0] for r in rows]

    def update_bookmark_tags(self, url: str, tags: list[str]) -> bool:
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        with self._conn() as conn:
            cur = conn.execute("UPDATE bookmarks SET tags=? WHERE url=?", (tags_str, url))
            if cur.rowcount == 0:
                return False
            bm_id = conn.execute("SELECT id FROM bookmarks WHERE url=?", (url,)).fetchone()["id"]
            conn.execute("DELETE FROM bookmark_tags WHERE bookmark_id = ?", (bm_id,))
            if clean_tags:
                conn.executemany(
                    "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                    ((bm_id, tag) for tag in clean_tags),
                )
            return True

    # ── Annotation CRUD ────────────────────────────────────────

    def upsert_annotation(self, url: str, note: str, history_id: int | None = None) -> AnnotationRecord:
        now = int(time.time())
        with self._conn() as conn:
            existing = conn.execute("SELECT id, created_at FROM annotations WHERE url=?", (url,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE annotations SET note=?, updated_at=?, history_id=? WHERE url=?",
                    (note, now, history_id, url),
                )
                ann_id = existing["id"]
                created_at = existing["created_at"]
            else:
                cur = conn.execute(
                    "INSERT INTO annotations(url, note, created_at, updated_at, history_id) VALUES(?,?,?,?,?)",
                    (url, note, now, now, history_id),
                )
                ann_id = cur.lastrowid
                created_at = now
        return AnnotationRecord(
            id=ann_id,
            url=url,
            note=note,
            created_at=created_at,
            updated_at=now,
            history_id=history_id,
        )

    def delete_annotation(self, url: str) -> bool:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO deleted_annotations(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                (url,),
            )
            cur = conn.execute("DELETE FROM annotations WHERE url=?", (url,))
            return cur.rowcount > 0

    def get_annotation(self, url: str) -> AnnotationRecord | None:
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT id, url, note, created_at, updated_at, history_id FROM annotations WHERE url=?", (url,)
            ).fetchone()
        if row is None:
            return None
        return AnnotationRecord(
            id=row["id"],
            url=row["url"],
            note=row["note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            history_id=row["history_id"],
        )

    def get_annotated_urls(self) -> set[str]:
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT url FROM annotations WHERE note != ''").fetchall()
        return {r[0] for r in rows}

    def get_all_annotations(self) -> list[AnnotationRecord]:
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT id, url, note, created_at, updated_at, history_id FROM annotations ORDER BY updated_at DESC"
            ).fetchall()
        return [
            AnnotationRecord(
                id=r["id"],
                url=r["url"],
                note=r["note"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                history_id=r["history_id"],
            )
            for r in rows
        ]

    # ── End bookmark / annotation section ─────────────────────

    def get_browser_types(self) -> list[str]:
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT DISTINCT browser_type FROM history ORDER BY browser_type").fetchall()
            return [r[0] for r in rows]

    # ── Stats / analytics queries ─────────────────────────────

    @staticmethod
    def _time_range(year: int | None, month: int | None = None) -> tuple[int, int] | None:
        """Return (start_ts, end_ts) for the given year/month, or None for all-time."""
        import calendar as _cal
        import datetime as _dt

        if year is None:
            return None
        if month is not None:
            last_day = _cal.monthrange(year, month)[1]
            start = int(_dt.datetime(year, month, 1).timestamp())
            end = int(_dt.datetime(year, month, last_day, 23, 59, 59).timestamp()) + 1
            return start, end
        start = int(_dt.datetime(year, 1, 1).timestamp())
        end = int(_dt.datetime(year + 1, 1, 1).timestamp())
        return start, end

    def get_available_years(self) -> list[int]:
        """Return sorted list of years that have history records."""
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT DISTINCT CAST(strftime('%Y', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS yr "
                "FROM history ORDER BY yr"
            ).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def get_daily_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[str, int]:
        """Return {YYYY-MM-DD: count} for days with visits, filtered by year/month."""
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            with self._conn(write=False) as conn:
                rows = conn.execute(
                    "SELECT strftime('%Y-%m-%d', visit_time, 'unixepoch', 'localtime') AS day, "
                    "COUNT(*) AS cnt FROM history "
                    "WHERE visit_time >= ? AND visit_time < ? "
                    "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY day ORDER BY day",
                    (start_ts, end_ts),
                ).fetchall()
        else:
            with self._conn(write=False) as conn:
                rows = conn.execute(
                    "SELECT strftime('%Y-%m-%d', visit_time, 'unixepoch', 'localtime') AS day, "
                    "COUNT(*) AS cnt FROM history "
                    "WHERE NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY day ORDER BY day"
                ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_browser_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[str, int]:
        """Return {browser_type: count}, optionally filtered to *year*/*month*."""
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                "SELECT browser_type, COUNT(*) AS cnt FROM history "
                "WHERE visit_time >= ? AND visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY browser_type"
            )
            params: tuple = (start_ts, end_ts)
        else:
            sql = (
                "SELECT browser_type, COUNT(*) AS cnt FROM history "
                "WHERE NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY browser_type"
            )
            params = ()
        with self._conn(write=False) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_hourly_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[int, int]:
        """Return {hour_0_to_23: count} for a heat-of-day chart."""
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                "SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                "COUNT(*) AS cnt FROM history "
                "WHERE visit_time >= ? AND visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY hr"
            )
            params: tuple = (start_ts, end_ts)
        else:
            sql = (
                "SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                "COUNT(*) AS cnt FROM history "
                "WHERE NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY hr"
            )
            params = ()
        with self._conn(write=False) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_top_domains(
        self, limit: int = 10, year: int | None = None, month: int | None = None
    ) -> list[tuple[str, int]]:
        """Return [(domain, count)] for the most-visited domains."""
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                "SELECT d.host, COUNT(*) AS cnt FROM history h "
                "JOIN domains d ON h.domain_id = d.id "
                "WHERE h.visit_time >= ? AND h.visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = h.url) "
                "GROUP BY d.host ORDER BY cnt DESC LIMIT ?"
            )
            params: tuple = (start_ts, end_ts, limit)
        else:
            sql = (
                "SELECT d.host, COUNT(*) AS cnt FROM history h "
                "JOIN domains d ON h.domain_id = d.id "
                "WHERE NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = h.url) "
                "GROUP BY d.host ORDER BY cnt DESC LIMIT ?"
            )
            params = (limit,)
        with self._conn(write=False) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def get_day_top_pages(self, date_str: str, limit: int = 3) -> list[tuple[str, str, int]]:
        """Return [(title, url, total_visits)] for the most-visited pages on *date_str* (YYYY-MM-DD)."""
        import datetime as _dt

        d = _dt.date.fromisoformat(date_str)
        start_ts = int(_dt.datetime(d.year, d.month, d.day).timestamp())
        end_ts = start_ts + 86400
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT MAX(title) AS title, url, SUM(visit_count) AS total_visits FROM history "
                "WHERE visit_time >= ? AND visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) "
                "GROUP BY url "
                "ORDER BY total_visits DESC LIMIT ?",
                (start_ts, end_ts, limit),
            ).fetchall()
        return [(r[0] or r[1], r[1], r[2]) for r in rows]

    def get_day_hourly_counts(self, date_str: str) -> dict[int, int]:
        """Return {hour_0_to_23: count} for a specific date (YYYY-MM-DD)."""
        import datetime as _dt

        d = _dt.date.fromisoformat(date_str)
        start_ts = int(_dt.datetime(d.year, d.month, d.day).timestamp())
        end_ts = start_ts + 86400
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                "COUNT(*) AS cnt FROM history "
                "WHERE visit_time >= ? AND visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url) GROUP BY hr",
                (start_ts, end_ts),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_available_browsers(self) -> list[tuple[str, str]]:
        """Return [(browser_type, display_name)] for browsers that have history records."""
        from src.services.browser_defs import BROWSER_DEF_MAP

        return [(t, BROWSER_DEF_MAP[t].display_name if t in BROWSER_DEF_MAP else t) for t in self.get_browser_types()]

    def search_quick(
        self, keyword: str, browser_type: str | None = None, limit: int = 8, offset: int = 0
    ) -> list[HistoryRecord]:
        """Overlay-only fast read using a cached read-only connection.

        Reuses a persistent read-only connection so the overlay is never blocked
        by self._lock during concurrent sync writes (SQLite WAL allows concurrent
        readers even while a writer holds the write lock).

        The entire query runs under _ro_lock to prevent a race where _reset_conn
        closes the connection between _ensure_ro_conn() and conn.execute().
        """
        _COLS = (
            "h.id, h.url, h.title, h.visit_time, h.visit_count, "
            "h.browser_type, h.profile_name, h.metadata, "
            "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
            "h.device_id, d.host AS domain"
        )
        params: list = []
        conditions: list[str] = []

        _any_short_word = keyword and not _keyword_eligible_for_fts(keyword)
        if keyword and _any_short_word:
            from_clause = "FROM history h"
            conditions.append("(h.title LIKE ? ESCAPE '\\' OR h.url LIKE ? ESCAPE '\\')")
            params.extend([f"%{_escape_like(keyword)}%", f"%{_escape_like(keyword)}%"])
        elif keyword:
            fts_query = _build_fts_query(keyword)
            from_clause = "FROM history_fts fts JOIN history h ON h.id = fts.rowid"
            conditions.append("history_fts MATCH ?")
            params.append(fts_query)
        else:
            from_clause = "FROM history h"

        if browser_type and browser_type not in ("auto", "all"):
            conditions.append("h.browser_type = ?")
            params.append(browser_type)

        conditions.append("NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = h.url)")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        # Inject domains JOIN so _row_to_record can read d.host AS domain directly.
        from_clause_with_join = from_clause.replace(
            "FROM history h",
            "FROM history h LEFT JOIN domains d ON h.domain_id = d.id",
            1,
        )
        sql = f"SELECT {_COLS} {from_clause_with_join} {where} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._ro_lock:
            conn = self._ensure_ro_conn()
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.ProgrammingError:
                # Connection was closed by _reset_conn between acquire and execute — rebuild.
                self._ro_conn = None
                conn = self._ensure_ro_conn()
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS index unavailable — fall back to LIKE
                if keyword:
                    from_clause = "FROM history h LEFT JOIN domains d ON h.domain_id = d.id"
                    conditions = [
                        "(h.title LIKE ? ESCAPE '\\' OR h.url LIKE ? ESCAPE '\\')",
                        "NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = h.url)",
                    ]
                    params = [f"%{_escape_like(keyword)}%", f"%{_escape_like(keyword)}%"]
                    if browser_type and browser_type not in ("auto", "all"):
                        conditions.append("h.browser_type = ?")
                        params.append(browser_type)
                    where = "WHERE " + " AND ".join(conditions)
                    sql = f"SELECT {_COLS} {from_clause} {where} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    try:
                        rows = conn.execute(sql, params).fetchall()
                    except sqlite3.ProgrammingError:
                        # Connection was closed between the first failure and the
                        # fallback execute — rebuild once and retry.
                        self._ro_conn = None
                        conn = self._ensure_ro_conn()
                        rows = conn.execute(sql, params).fetchall()
                else:
                    rows = []
        return [self._row_to_record(r) for r in rows]

    def get_all_known_domains(self) -> set[str]:
        """
        Returns the set of all distinct hostnames recorded in the history database.

        This is used by the favicon extractor to restrict icon extraction to only
        the domains the user has actually visited, avoiding unnecessary work on
        the full browser favicon database.  The ``domains`` table is kept
        normalised by the importer, so this query is always an O(n) index scan
        with no JOIN required.
        """
        with self._conn(write=False) as conn:
            rows = conn.execute("SELECT host FROM domains").fetchall()
        return {r[0] for r in rows}

    def get_day_counts_batch(self, day_starts: list[int]) -> dict[int, int]:
        """Return {day_start_ts: record_count} for every timestamp in *day_starts*.

        Executes a **single** SQL statement regardless of batch size by
        constructing a VALUES-based CTE at call time.  Each ``day_start``
        value is a local-midnight Unix timestamp; records are counted in the
        half-open interval [day_start, day_start + 86400).

        Performance characteristics
        ---------------------------
        * One round-trip to SQLite for the entire batch (vs N round-trips).
        * The history.visit_time column is covered by the primary index used
          for time-range scans, so each per-day COUNT is an index range scan.
        * Typical batch size is 3-10 visible separator rows, making this
          negligibly cheap even on large databases.
        """
        if not day_starts:
            return {}
        union_clause = " UNION ALL ".join("SELECT ? AS ds" for _ in day_starts)
        sql = f"""
            WITH ranges(ds) AS ({union_clause})
            SELECT r.ds, COUNT(h.id)
            FROM   ranges r
            LEFT JOIN history h ON h.visit_time >= r.ds AND h.visit_time < r.ds + 86400
            GROUP  BY r.ds
        """
        with self._conn(write=False) as conn:
            rows = conn.execute(sql, day_starts).fetchall()
        return {int(r[0]): int(r[1]) for r in rows}

    def get_day_rank(self, day_start_ts: int, ts: int) -> int:
        """Return the 1-based rank of ts among all records in the same day (ordered by visit_time)."""
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM history "
                "WHERE visit_time BETWEEN ? AND ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url)",
                (day_start_ts, ts),
            ).fetchone()
        return row[0] if row else 1

    def get_day_stats(self, day_start_ts: int, day_end_ts: int, top_n: int = 3) -> dict:
        """Return stats for a given day used by the scroll time bubble.

        Uses a half-open interval [day_start_ts, day_end_ts) so the boundary
        is consistent with get_day_hourly_counts (which uses start + 86400).

        Returns:
            {
                "total": int,          # total records for the day
                "domains": [(host, count), ...]  # top N domains by visit count
            }
        """
        with self._conn(write=False) as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM history "
                "WHERE visit_time >= ? AND visit_time < ? "
                "AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = history.url)",
                (day_start_ts, day_end_ts),
            ).fetchone()
            total = total_row[0] if total_row else 0

            domain_rows = conn.execute(
                """
                SELECT d.host, COUNT(h.id) AS cnt
                FROM history h
                JOIN domains d ON h.domain_id = d.id
                WHERE h.visit_time >= ? AND h.visit_time < ?
                AND NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = h.url)
                GROUP BY d.id
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (day_start_ts, day_end_ts, top_n),
            ).fetchall()

        return {
            "total": total,
            "domains": [(r[0], r[1]) for r in domain_rows],
        }

    def get_all_backup_stats(self) -> list[BackupStats]:
        with self._conn(write=False) as conn:
            rows = conn.execute("""
                SELECT id, browser_type, profile_name,
                       first_backup_time, last_backup_time, total_records_synced
                FROM backup_stats ORDER BY last_backup_time DESC
            """).fetchall()
        return [
            BackupStats(
                id=r["id"],
                browser_type=r["browser_type"],
                profile_name=r["profile_name"],
                first_backup_time=r["first_backup_time"],
                last_backup_time=r["last_backup_time"],
                total_records_synced=r["total_records_synced"],
            )
            for r in rows
        ]

    def get_last_sync_time(self) -> int | None:
        with self._conn(write=False) as conn:
            row = conn.execute("SELECT MAX(last_backup_time) FROM backup_stats").fetchone()
            return row[0] if row and row[0] else None

    # ── Privacy / management ──────────────────────────────────

    def delete_records_by_ids(self, ids: list[int]) -> int:
        if not ids:
            return 0
        _CHUNK = 900
        with self._conn() as conn:
            deleted = 0
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                # Tombstone only URLs that will have no remaining rows after deletion.
                # A URL shared across multiple browsers must NOT be tombstoned when only
                # one browser's copy is removed — doing so would silently wipe the other
                # browsers' records during the next WebDAV sync.
                # GROUP BY + HAVING avoids the O(N²) NOT IN full-table scan: the correlated
                # COUNT uses idx_history_url (O(log N) per group) → O(M log N) total.
                conn.execute(
                    f"INSERT OR IGNORE INTO deleted_records(url) "
                    f"SELECT url FROM history WHERE id IN ({placeholders}) "
                    f"GROUP BY url "
                    f"HAVING COUNT(*) = (SELECT COUNT(*) FROM history h2 WHERE h2.url = history.url)",
                    chunk,
                )
                cursor = conn.execute(f"DELETE FROM history WHERE id IN ({placeholders})", chunk)
                deleted += cursor.rowcount
            return deleted

    def delete_records_by_browser(self, browser_type: str) -> int:
        """Delete all history records for a specific browser and corresponding backup_stats entries."""
        with self._conn() as conn:
            # Tombstone only URLs that exist exclusively in this browser.
            # If a URL also appears under a different browser_type it must NOT receive a
            # tombstone — otherwise the next sync would delete the other browser's record.
            # GROUP BY + HAVING avoids the O(N²) NOT IN full-table scan.
            conn.execute(
                "INSERT OR IGNORE INTO deleted_records(url) "
                "SELECT url FROM history WHERE browser_type = ? "
                "GROUP BY url "
                "HAVING COUNT(*) = (SELECT COUNT(*) FROM history h2 WHERE h2.url = history.url)",
                (browser_type,),
            )
            cursor = conn.execute("DELETE FROM history WHERE browser_type = ?", (browser_type,))
            deleted = cursor.rowcount
            conn.execute("DELETE FROM backup_stats WHERE browser_type = ?", (browser_type,))
            return deleted

    # ── Domain-matching helpers ──────────────────────────────

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Canonical form: lowercase, no port, no leading ``www.``"""
        return normalize_domain(domain)

    @staticmethod
    def _domain_ids_for(conn: sqlite3.Connection, domain: str) -> list[int]:
        """Return domain.id values for *domain* and all its subdomains."""
        domain_norm = LocalDatabase._normalize_domain(domain)
        if not domain_norm:
            return []
        rows = conn.execute(
            "SELECT id FROM domains WHERE host = ? OR host LIKE ?",
            (domain_norm, "%." + domain_norm),
        ).fetchall()
        return [r[0] for r in rows]

    def get_domain_ids(self, domains: list[str]) -> list[int]:
        """Return all domain.id values matching *domains* and their subdomains.

        Public interface used by CLI export and other callers that need to
        resolve domain names to IDs without accessing internal connection state.
        """
        if not domains:
            return []
        with self._conn(write=False) as conn:
            ids: list[int] = []
            for d in domains:
                ids.extend(self._domain_ids_for(conn, d))
        return list(set(ids))

    def delete_records_by_domain(self, domain: str) -> int:
        with self._conn() as conn:
            ids = self._domain_ids_for(conn, domain)
            if not ids:
                return 0
            _CHUNK = 900
            deleted = 0
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                # Only tombstone URLs that have no surviving rows outside the deleted domain_ids.
                # GROUP BY + HAVING avoids the O(N²) NOT IN full-table scan: the correlated
                # COUNT uses idx_history_url (O(log N) per group) → O(M log N) total.
                conn.execute(
                    f"INSERT OR IGNORE INTO deleted_records(url) "
                    f"SELECT url FROM history WHERE domain_id IN ({placeholders}) "
                    f"GROUP BY url "
                    f"HAVING COUNT(*) = (SELECT COUNT(*) FROM history h2 WHERE h2.url = history.url)",
                    chunk,
                )
                cursor = conn.execute(f"DELETE FROM history WHERE domain_id IN ({placeholders})", chunk)
                deleted += cursor.rowcount
                conn.execute(f"DELETE FROM domains WHERE id IN ({placeholders})", chunk)
            return deleted

    def resolve_domain_ids(self, domains: list[str]) -> list[int]:
        """Return the flattened list of domain.id values for all given domain names."""
        if not domains:
            return []
        ids: list[int] = []
        with self._conn(write=False) as conn:
            for d in domains:
                ids.extend(self._domain_ids_for(conn, d))
        return ids

    def get_domain_count(self, domain: str) -> int:
        with self._conn(write=False) as conn:
            ids = self._domain_ids_for(conn, domain)
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            row = conn.execute(f"SELECT COUNT(*) FROM history WHERE domain_id IN ({placeholders})", ids).fetchone()
            return row[0] if row else 0

    def get_filtered_id_times(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        excluded_ids: set[int] | None = None,
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
    ) -> list[tuple[int, int]]:
        """Return (id, visit_time) for all matching rows ordered visit_time DESC.

        Much lighter than get_records() — only two integers per row.  Used to
        build a lightweight scroll index so page fetches can use WHERE id IN (...)
        instead of LIMIT/OFFSET full-table scans.
        """
        excl = excluded_ids or set()
        with self._conn(write=False) as conn:
            from_where, params, _ = self._build_query_parts(
                conn=conn,
                keyword=keyword,
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                excluded_ids=excl,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                _force_like=False,
                device_ids=device_ids,
            )
            sql = f"SELECT h.id, h.visit_time {from_where} ORDER BY h.visit_time DESC"
            cur = conn.execute(sql, params)
            return [(row[0], row[1]) for row in cur]

    def get_records_by_ids(self, ids: list[int]) -> list[HistoryRecord]:
        if not ids:
            return []
        _CHUNK = 900
        rows: list[sqlite3.Row] = []
        with self._conn(write=False) as conn:
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows.extend(
                    conn.execute(
                        f"SELECT h.id, h.url, h.title, h.visit_time, h.visit_count, "
                        f"h.browser_type, h.profile_name, h.metadata, "
                        f"h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
                        f"h.device_id, d.host AS domain "
                        f"FROM history h LEFT JOIN domains d ON h.domain_id = d.id "
                        f"WHERE h.id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
        record_map = {r["id"]: self._row_to_record(r) for r in rows}
        return [record_map[i] for i in ids if i in record_map]

    def get_row_offset_for_url(self, url: str) -> int:
        """Return the 0-based row index of the *most-recent* visit for *url*
        in the default (unfiltered, visit_time DESC) sort order.

        Returns -1 if the URL is not found.  Used by the "Locate in History"
        feature so the history table can scroll to and select that exact row.
        """
        with self._conn(write=False) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM history WHERE visit_time > (SELECT MAX(visit_time) FROM history WHERE url = ?)",
                (url,),
            ).fetchone()
            if row is None:
                return -1
            count = row[0]
            # Verify at least one record exists for that URL
            exists = conn.execute("SELECT 1 FROM history WHERE url = ? LIMIT 1", (url,)).fetchone()
            return count if exists else -1

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _row_to_record(row) -> HistoryRecord:
        # sqlite3.Row always supports key-based access; no hasattr guard needed.
        # Using try/except for the optional device_id column is O(1) — far cheaper
        # than building a keys() list and doing an O(n) membership test on every row.
        try:
            device_id = row["device_id"]
        except IndexError:
            device_id = None
        # Prefer the pre-joined d.host value (avoids per-row Python URL parsing).
        # Fall back to _extract_display_domain only when domain_id was NULL or the
        # column is absent (e.g. legacy callers that haven't added the JOIN yet).
        try:
            domain = row["domain"] or _extract_display_domain(row["url"])
        except IndexError:
            domain = _extract_display_domain(row["url"])
        return HistoryRecord(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            visit_time=row["visit_time"],
            visit_count=row["visit_count"],
            browser_type=row["browser_type"],
            profile_name=row["profile_name"],
            domain=domain,
            metadata=row["metadata"],
            typed_count=row["typed_count"],
            first_visit_time=row["first_visit_time"],
            transition_type=row["transition_type"],
            visit_duration=row["visit_duration"],
            device_id=device_id,
        )

    def resolve_device_ids(self, name_or_uuid: str) -> list[int]:
        """Return device.id values whose name contains or uuid starts with the given string."""
        if not name_or_uuid:
            return []
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT id FROM devices WHERE name LIKE ? ESCAPE '\\' OR uuid LIKE ? ESCAPE '\\'",
                (f"%{_escape_like(name_or_uuid)}%", f"{_escape_like(name_or_uuid)}%"),
            ).fetchall()
        return [r[0] for r in rows]


def _is_fts_special(keyword: str) -> bool:
    """Return True if the keyword contains FTS5 special characters or operators.

    Not called by production code - used by tests/test_fts.py to verify FTS
    special-character detection logic independently.
    """
    return bool(re.search(r'[()"*]|(?<!\w)(AND|OR|NOT)(?!\w)', keyword))


def _escape_like(value: str) -> str:
    """Escape LIKE wildcard characters in *value* for use with ``ESCAPE '\\'``."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _keyword_eligible_for_fts(keyword: str) -> bool:
    """Return True when *keyword* can be handled by the FTS5 trigram index.

    The trigram tokenizer requires every individual token to be at least
    3 characters long.  A keyword fails this check when:
    - it is empty, or
    - any whitespace-separated word is shorter than 3 characters, or
    - the keyword stripped of spaces is shorter than 3 characters.
    """
    if not keyword:
        return False
    if any(len(w) < 3 for w in keyword.split() if w):
        return False
    return len(keyword.replace(" ", "")) >= 3


def _build_fts_query(keyword: str) -> str:
    """Build an FTS5 MATCH expression from a keyword.

    If the keyword already carries a column-filter prefix (``title:`` or
    ``url:``), we must NOT wrap the whole string in phrase-quotes because
    that would make FTS5 treat ``url:`` as literal text instead of a column
    filter, causing zero results.  Strip the prefix, quote only the bare
    term, then re-attach the column prefix.

    Multi-word keywords are split and joined with AND so that each word is
    matched independently (prefix search per word), giving higher recall than
    phrase matching which requires adjacent occurrence.

    Examples:
        ``github``            ->  ``"github"*``
        ``python tutorial``   ->  ``"python"* AND "tutorial"*``
        ``url:github``        ->  ``url:"github"*``
        ``title:python``      ->  ``title:"python"*``
    """
    if not keyword:
        return '""'

    for prefix in ("url:", "title:"):
        if keyword.startswith(prefix):
            bare = keyword[len(prefix) :]
            if not bare:
                return '""'
            escaped = bare.replace('"', '""')
            return f'{prefix}"{escaped}"*'

    # Split on whitespace; each token gets its own prefix-quoted term
    tokens = keyword.split()
    if len(tokens) == 1:
        escaped = tokens[0].replace('"', '""')
        return f'"{escaped}"*'
    parts = [f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens]
    return " AND ".join(parts)
