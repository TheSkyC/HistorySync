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
from src.utils.url_utils import extract_host as _extract_url_host

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
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Internal helpers ──────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        """Return the persistent connection, creating it if necessary.
        Caller must already hold self._lock.
        """
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
            self._pconn = conn
        return self._pconn

    def _reset_conn(self) -> None:
        """Close and discard the persistent connection so it is recreated next time."""
        if self._pconn is not None:
            try:
                self._pconn.close()
            except Exception:
                pass
            self._pconn = None

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
        with self._lock:
            self._reset_conn()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        with self._conn() as conn:
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
        self._migrate_schema()
        self._verify_fts_integrity()
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
        import time as _time

        with self._conn() as conn:
            conn.execute(
                "UPDATE devices SET last_sync_at = ? WHERE id = ?",
                (int(_time.time()), device_id),
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
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(f"SELECT url FROM history WHERE id IN ({placeholders})", ids).fetchall()
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
        with self._conn(write=False) as conn:
            if candidate_ids:
                placeholders = ",".join("?" * len(candidate_ids))
                rows = conn.execute(
                    f"""SELECT h.id FROM history h
                        JOIN hidden_records hr ON h.url = hr.url
                        WHERE h.id IN ({placeholders})""",
                    list(candidate_ids),
                ).fetchall()
            else:
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

            # FTS size estimate: sum payload bytes of all FTS shadow tables.
            try:
                fts_pages = conn.execute("""
                    SELECT COALESCE(SUM(payload), 0)
                    FROM dbstat
                    WHERE name LIKE 'history_fts%'
                """).fetchone()
                fts_bytes = fts_pages[0] if fts_pages else 0
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
        with self._lock:
            _cb(_("Checkpointing WAL into main file…"))
            conn = sqlite3.connect(str(db_path), timeout=60)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                result = conn.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()
                if result and result[0]:
                    _cb(_("⚠ WAL checkpoint partially blocked by active readers; proceeding anyway…"))
                conn.commit()
                conn.close()
                conn = None
            finally:
                if conn:
                    conn.close()
            size_before = db_path.stat().st_size if db_path.exists() else 0
            for suffix in ("-wal", "-shm"):
                p = db_path.with_name(db_path.name + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
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

            # 4. Reclaim all space previously occupied by FTS index
            dst_conn.execute("VACUUM")

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
            conn.create_function("_extract_host", 1, _extract_url_host)

            _cb(_("Inserting new domain entries…"))
            conn.execute("""
                INSERT OR IGNORE INTO domains(host)
                SELECT DISTINCT _extract_host(url)
                FROM history
                WHERE _extract_host(url) IS NOT NULL
                  AND (domain_id IS NULL OR domain_id NOT IN (SELECT id FROM domains))
            """)

            _cb(_("Back-filling domain_id on history rows…"))
            cursor = conn.execute("""
                UPDATE history
                SET domain_id = (
                    SELECT d.id FROM domains d
                    WHERE d.host = _extract_host(history.url)
                )
                WHERE domain_id IS NULL
            """)
            updated = cursor.rowcount

        _cb(_("Domain normalisation complete — {n} rows updated.").format(n=f"{updated:,}"))
        return updated

    # ═══════════════════════════════════════════════════════════
    # Write operations
    # ═══════════════════════════════════════════════════════════

    def replace_database(self, new_db_path: Path) -> None:
        """Safely replace the underlying SQLite file (used for WebDAV restore)."""
        with self._lock:
            log.info("Replacing current database with %s", new_db_path)
            for suffix in ("-wal", "-shm"):
                p = self.db_path.with_name(self.db_path.name + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError as exc:
                        log.warning("Failed to delete %s: %s", p.name, exc)
            shutil.copy2(new_db_path, self.db_path)
            self._reset_conn()
            log.info("Database successfully replaced")

    def merge_from_db(
        self,
        src_path: Path,
        progress_cb: Callable[[str], None] | None = None,
    ) -> int:
        """Merge history records from *src_path* into this database.

        Rows are streamed from the source in batches of ``DB_BATCH_SIZE`` to
        avoid loading the entire backup into memory at once.
        """

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)
            log.info("merge_from_db: %s", msg)

        _cb(_("Opening backup database for merge..."))
        src_conn = sqlite3.connect(str(src_path), timeout=30)
        src_conn.row_factory = sqlite3.Row
        try:
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
                    if r["url"] not in _remote_deleted_urls
                ]
                inserted += self.upsert_records(records)

        finally:
            src_conn.close()

        # Apply local tombstones — remove any history rows that were hard-deleted on this device
        with self._conn() as conn:
            conn.execute("DELETE FROM history WHERE url IN (SELECT url FROM deleted_records)")
            # Also absorb remote tombstones into local table
            if remote_deleted:
                conn.executemany(
                    "INSERT INTO deleted_records(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r[0], r[1]) for r in remote_deleted),
                )

        _cb(
            _("Merge complete: {inserted} new records added (of {total} in backup).").format(
                inserted=inserted, total=total_src
            )
        )
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
            for bm in remote_bookmarks:
                url = bm["url"]
                if url in deleted_bm_urls:
                    continue
                # Re-resolve history_id by url
                h_row = conn.execute("SELECT id FROM history WHERE url=? LIMIT 1", (url,)).fetchone()
                history_id = h_row[0] if h_row else None
                existing = conn.execute("SELECT bookmarked_at FROM bookmarks WHERE url=?", (url,)).fetchone()
                remote_ts = bm["bookmarked_at"]
                if existing is None or remote_ts > existing[0]:
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

            for url in tag_replace_urls:
                bm_row = conn.execute("SELECT id FROM bookmarks WHERE url=?", (url,)).fetchone()
                if not bm_row:
                    continue
                bm_id = bm_row[0]
                # Atomically replace: delete existing tags, insert remote tags
                conn.execute("DELETE FROM bookmark_tags WHERE bookmark_id=?", (bm_id,))
                for tag in remote_tags_by_url.get(url, []):
                    conn.execute(
                        "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                        (bm_id, tag),
                    )

            # 6. Merge annotations (skip tombstoned urls, keep newer updated_at)
            deleted_ann_urls: set[str] = {r[0] for r in conn.execute("SELECT url FROM deleted_annotations").fetchall()}
            for ann in remote_annotations:
                url = ann["url"]
                if url in deleted_ann_urls:
                    continue
                h_row = conn.execute("SELECT id FROM history WHERE url=? LIMIT 1", (url,)).fetchone()
                history_id = h_row[0] if h_row else None
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

            # 4. Temporarily drop FTS triggers so the per-row FTS overhead is
            #    avoided during a bulk insert; we do a single targeted sync at
            #    the end instead.  executescript issues an implicit COMMIT
            #    first, which is intentional — it persists domains before DDL.
            conn.executescript("""
                DROP TRIGGER IF EXISTS history_ai;
                DROP TRIGGER IF EXISTS history_ad;
                DROP TRIGGER IF EXISTS history_au;
            """)

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
            inserted: int = conn.execute("SELECT COUNT(*) FROM history WHERE id > ?", (max_id_before,)).fetchone()[0]

            # 7. Commit the history inserts, then restore FTS triggers.
            #    executescript issues an implicit COMMIT, which is intentional.
            conn.commit()
            conn.executescript("""
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
            """)

            # 8. Batch-sync FTS for the trigger-free window.
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

            # 8a. Insert FTS entries for genuinely new rows.
            conn.execute(
                "INSERT INTO history_fts(rowid, url, title) SELECT id, url, title FROM history WHERE id > ?",
                (max_id_before,),
            )

            # 8b. Refresh FTS for updated rows (pre-existing rows whose content
            #     may have changed due to DO UPDATE).  We gather their ids via
            #     a join on the dedup key, then do a delete+re-insert in FTS.
            if records:
                # Build a temp table of (browser_type, url, visit_time) tuples
                # for all input records to identify which pre-existing rows
                # were touched by the DO UPDATE clause.
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
                updated_rows = conn.execute(
                    "SELECT h.id, h.url, h.title FROM history h "
                    "JOIN _upsert_keys k "
                    "  ON h.browser_type = k.browser_type "
                    " AND h.url          = k.url "
                    " AND h.visit_time   = k.visit_time "
                    "WHERE h.id <= ?",
                    (max_id_before,),
                ).fetchall()
                conn.execute("DROP TABLE IF EXISTS _upsert_keys")

                if updated_rows:
                    # Delete stale FTS entries, then re-insert current content.
                    conn.executemany(
                        "INSERT INTO history_fts(history_fts, rowid, url, title) VALUES('delete', ?, ?, ?)",
                        ((row[0], row[1], row[2]) for row in updated_rows),
                    )
                    conn.executemany(
                        "INSERT INTO history_fts(rowid, url, title) VALUES (?, ?, ?)",
                        ((row[0], row[1], row[2]) for row in updated_rows),
                    )

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
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
            return row[0] if row else 0

    def get_max_visit_times(self, browser_type: str) -> dict[str, int]:
        with self._conn() as conn:
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

    @staticmethod
    def _populate_excl_table(conn: sqlite3.Connection, excl: set[int]) -> bool:
        if not excl:
            return False
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _excl_ids (id INTEGER PRIMARY KEY)")
        # Skip the expensive DELETE + re-insert when the set hasn't changed since
        # the last call on this connection (common in UI scroll / pagination).
        cached: set[int] | None = getattr(conn, "_excl_ids_cache", None)
        if cached != excl:
            conn.execute("DELETE FROM _excl_ids")
            conn.executemany("INSERT OR IGNORE INTO _excl_ids VALUES(?)", ((i,) for i in excl))
            conn._excl_ids_cache = excl  # type: ignore[attr-defined]
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
        """Incremental regex search iterator.

        Fetches candidates in batches from the database, filters them with
        the regex pattern, and yields matching records one by one. This
        avoids the hard-coded 5000-record limit and enables true incremental
        loading for large datasets.

        Args:
            pattern: Compiled regex pattern to match against.
            batch_size: Number of candidate records to fetch per batch.
            Other args: Same as get_records() for filtering candidates.

        Yields:
            HistoryRecord: Each record that matches the regex pattern.
        """
        offset = 0
        while True:
            candidates = self.get_records(
                keyword="",  # No FTS/LIKE filtering
                browser_type=browser_type,
                date_from=date_from,
                date_to=date_to,
                limit=batch_size,
                offset=offset,
                excluded_ids=excluded_ids,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=False,  # Filter in Python layer
                url_only=False,
                use_regex=False,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                device_ids=device_ids,
            )

            if not candidates:
                break

            for r in candidates:
                if title_only:
                    match = pattern.search(r.title or "")
                elif url_only:
                    match = pattern.search(r.url)
                else:
                    match = pattern.search(r.title or "") or pattern.search(r.url)

                if match:
                    yield r

            offset += batch_size
            if len(candidates) < batch_size:
                break  # Reached end of database

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
                bm_conditions.append("bt.tag = ?")
                bm_params_prefix.append(bookmark_tag)
        if has_annotation:
            bm_joins += " JOIN annotations ann ON h.url = ann.url AND ann.note != ''"

        # ── Populate excluded-ids temp table ──────────────────
        self._populate_excl_table(conn, excluded_ids)

        use_fts = False
        extra_conditions: list[str] = []
        params: list = []

        if keyword:
            use_fts = len(keyword.replace(" ", "")) >= 3 and not _force_like
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
                like_pat = f"%{keyword}%"
                if title_only:
                    from_where = "FROM history h\n    WHERE h.title LIKE ?"
                    params = [like_pat]
                elif url_only:
                    from_where = "FROM history h\n    WHERE h.url LIKE ?"
                    params = [like_pat]
                else:
                    from_where = "FROM history h\n    WHERE (h.url LIKE ? OR h.title LIKE ?)"
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
                extra_conditions.append("h.url NOT LIKE ? AND h.title NOT LIKE ?")
                params.extend([f"%{ex}%", f"%{ex}%"])
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
            for record in iter_obj:
                results.append(record)
                if len(results) >= offset + limit:
                    break
            return results[offset : offset + limit]

        _COLS = (
            "h.id, h.url, h.title, h.visit_time, h.visit_count, "
            "h.browser_type, h.profile_name, h.metadata, "
            "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
            "h.device_id"
        )
        with self._conn() as conn:
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
                        _force_like=True,
                    )
                raise
        return [self._row_to_record(r) for r in rows]

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

        with self._conn() as conn:
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
                rows = conn.execute(
                    """SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id
                       FROM bookmarks b
                       JOIN bookmark_tags bt ON b.id = bt.bookmark_id
                       WHERE bt.tag = ?
                       ORDER BY b.bookmarked_at DESC""",
                    (tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, url, title, bookmarked_at, history_id FROM bookmarks ORDER BY bookmarked_at DESC"
                ).fetchall()
            if not rows:
                return []
            bm_ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(bm_ids))
            tag_rows = conn.execute(
                f"SELECT bookmark_id, tag FROM bookmark_tags WHERE bookmark_id IN ({placeholders})",
                bm_ids,
            ).fetchall()
        tags_by_id: dict[int, list[str]] = {}
        for tr in tag_rows:
            tags_by_id.setdefault(tr["bookmark_id"], []).append(tr["tag"])
        return [
            BookmarkRecord(
                id=r["id"],
                url=r["url"],
                title=r["title"],
                tags=tags_by_id.get(r["id"], []),
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
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT browser_type FROM history ORDER BY browser_type").fetchall()
            return [r[0] for r in rows]

    def get_all_backup_stats(self) -> list[BackupStats]:
        with self._conn() as conn:
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
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(last_backup_time) FROM backup_stats").fetchone()
            return row[0] if row and row[0] else None

    # ── Privacy / management ──────────────────────────────────

    def delete_records_by_ids(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            # Tombstone before delete
            urls = conn.execute(f"SELECT url FROM history WHERE id IN ({placeholders})", ids).fetchall()
            if urls:
                conn.executemany(
                    "INSERT INTO deleted_records(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                    ((r[0],) for r in urls),
                )
            cursor = conn.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)
            return cursor.rowcount

    def delete_records_by_browser(self, browser_type: str) -> int:
        """Delete all history records for a specific browser and corresponding backup_stats entries."""
        with self._conn() as conn:
            urls = conn.execute("SELECT url FROM history WHERE browser_type = ?", (browser_type,)).fetchall()
            if urls:
                conn.executemany(
                    "INSERT INTO deleted_records(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                    ((r[0],) for r in urls),
                )
            cursor = conn.execute("DELETE FROM history WHERE browser_type = ?", (browser_type,))
            deleted = cursor.rowcount
            conn.execute("DELETE FROM backup_stats WHERE browser_type = ?", (browser_type,))
            return deleted

    # ── Domain-matching helpers ──────────────────────────────

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Canonical form: lowercase, no port, no leading ``www.``"""
        d = domain.lower().strip().lstrip(".")
        if ":" in d and not d.startswith("["):
            d = d.rsplit(":", 1)[0]
        if d.startswith("www."):
            d = d[4:]
        return d

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
            placeholders = ",".join("?" * len(ids))
            urls = conn.execute(f"SELECT url FROM history WHERE domain_id IN ({placeholders})", ids).fetchall()
            if urls:
                conn.executemany(
                    "INSERT INTO deleted_records(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                    ((r[0],) for r in urls),
                )
            cursor = conn.execute(f"DELETE FROM history WHERE domain_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM domains WHERE id IN ({placeholders})", ids)
            return cursor.rowcount

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
        with self._conn() as conn:
            ids = self._domain_ids_for(conn, domain)
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            row = conn.execute(f"SELECT COUNT(*) FROM history WHERE domain_id IN ({placeholders})", ids).fetchone()
            return row[0] if row else 0

    def get_records_by_ids(self, ids: list[int]) -> list[HistoryRecord]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, url, title, visit_time, visit_count, browser_type, profile_name, metadata, "
                f"typed_count, first_visit_time, transition_type, visit_duration, device_id "
                f"FROM history WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_row_offset_for_url(self, url: str) -> int:
        """Return the 0-based row index of the *most-recent* visit for *url*
        in the default (unfiltered, visit_time DESC) sort order.

        Returns -1 if the URL is not found.  Used by the "Locate in History"
        feature so the history table can scroll to and select that exact row.
        """
        with self._conn() as conn:
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
        keys = row.keys() if hasattr(row, "keys") else []
        return HistoryRecord(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            visit_time=row["visit_time"],
            visit_count=row["visit_count"],
            browser_type=row["browser_type"],
            profile_name=row["profile_name"],
            metadata=row["metadata"],
            typed_count=row["typed_count"],
            first_visit_time=row["first_visit_time"],
            transition_type=row["transition_type"],
            visit_duration=row["visit_duration"],
            device_id=row["device_id"] if "device_id" in keys else None,
        )

    def resolve_device_ids(self, name_or_uuid: str) -> list[int]:
        """Return device.id values whose name contains or uuid starts with the given string."""
        if not name_or_uuid:
            return []
        with self._conn(write=False) as conn:
            rows = conn.execute(
                "SELECT id FROM devices WHERE name LIKE ? OR uuid LIKE ?",
                (f"%{name_or_uuid}%", f"{name_or_uuid}%"),
            ).fetchall()
        return [r[0] for r in rows]


def _is_fts_special(keyword: str) -> bool:
    """Return True if the keyword contains FTS5 special characters or operators."""
    import re

    return bool(re.search(r'[()"\*]|(?<!\w)(AND|OR|NOT)(?!\w)', keyword))


def _build_fts_query(keyword: str) -> str:
    """Build an FTS5 MATCH expression from a keyword.

    If the keyword already carries a column-filter prefix (``title:`` or
    ``url:``), we must NOT wrap the whole string in phrase-quotes because
    that would make FTS5 treat ``url:`` as literal text instead of a column
    filter, causing zero results.  Strip the prefix, quote only the bare
    term, then re-attach the column prefix.

    Examples:
        ``github``       →  ``"github"*``
        ``url:github``   →  ``url:"github"*``
        ``title:python`` →  ``title:"python"*``
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

    # Plain keyword — wrap entirely in phrase quotes
    escaped = keyword.replace('"', '""')
    return f'"{escaped}"*'
