# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import threading
import time

from src.models.history_record import BackupStats, HistoryRecord
from src.utils.constants import DB_BATCH_SIZE
from src.utils.i18n import _
from src.utils.logger import get_logger

log = get_logger("local_db")


@dataclass
class DbStats:
    """Snapshot of database size and content metrics."""

    file_size_bytes: int  # actual file size on disk
    page_count: int       # total SQLite pages allocated
    free_page_count: int  # unused (fragmented) pages
    page_size: int        # bytes per page
    record_count: int     # rows in history table
    domain_count: int     # distinct domains (after normalization)
    fts_size_bytes: int   # estimated size of FTS index

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
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT    NOT NULL,
                    title         TEXT    NOT NULL DEFAULT '',
                    visit_time    INTEGER NOT NULL,
                    visit_count   INTEGER NOT NULL DEFAULT 1,
                    browser_type  TEXT    NOT NULL,
                    profile_name  TEXT    NOT NULL DEFAULT '',
                    metadata      TEXT    NOT NULL DEFAULT '',
                    domain_id     INTEGER REFERENCES domains(id),
                    created_at    INTEGER NOT NULL DEFAULT (strftime('%s','now'))
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
            """)
        log.info("Database schema initialized: %s", self.db_path)

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

        with self._conn() as conn:
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

        def _extract_host(url: str) -> str | None:
            if not url:
                return None
            try:
                s = url
                if "://" in s:
                    s = s.split("://", 1)[1]
                host = s.split("/")[0].split("?")[0].split("#")[0]
                if ":" in host and not host.startswith("["):
                    host = host.rsplit(":", 1)[0]
                return host.lower() or None
            except Exception:
                return None

        updated = 0
        with self._conn() as conn:
            conn.create_function("_extract_host", 1, _extract_host)

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
            log.info("Database successfully replaced")

    def upsert_records(self, records: list[HistoryRecord]) -> int:
        if not records:
            return 0

        def _extract_host(url: str) -> str | None:
            if not url:
                return None
            try:
                s = url
                if "://" in s:
                    s = s.split("://", 1)[1]
                host = s.split("/")[0].split("?")[0].split("#")[0]
                if ":" in host and not host.startswith("["):
                    host = host.rsplit(":", 1)[0]
                return host.lower() or None
            except Exception:
                return None

        sql = """
            INSERT OR IGNORE INTO history
                (url, title, visit_time, visit_count, browser_type, profile_name, metadata, domain_id)
            VALUES (?, ?, ?, ?, ?, ?, ?,
                (SELECT id FROM domains WHERE host = _extract_host(?)))
        """
        with self._conn() as conn:
            conn.create_function("_extract_host", 1, _extract_host)

            hosts = {_extract_host(r.url) for r in records if r.url}
            hosts.discard(None)
            if hosts:
                conn.executemany(
                    "INSERT OR IGNORE INTO domains(host) VALUES(?)",
                    ((h,) for h in hosts),
                )

            inserted = 0
            for i in range(0, len(records), DB_BATCH_SIZE):
                batch = records[i : i + DB_BATCH_SIZE]
                params = [
                    (r.url, r.title, r.visit_time, r.visit_count, r.browser_type, r.profile_name, r.metadata, r.url)
                    for r in batch
                ]
                cursor = conn.executemany(sql, params)
                if cursor.rowcount >= 0:
                    inserted += cursor.rowcount

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
        conn.execute("DELETE FROM _excl_ids")
        conn.executemany("INSERT OR IGNORE INTO _excl_ids VALUES(?)", ((i,) for i in excl))
        return True

    @staticmethod
    def _excl_clause(alias: str = "") -> str:
        col = f"{alias}id" if alias else "id"
        return f"{col} NOT IN (SELECT id FROM _excl_ids)"

    def get_records(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        limit: int = 200,
        offset: int = 0,
        excluded_ids: set[int] | None = None,
    ) -> list[HistoryRecord]:
        excl = excluded_ids or set()
        if keyword:
            use_fts = len(keyword.replace(" ", "")) >= 3
            if use_fts:
                sql = """
                    SELECT h.id, h.url, h.title, h.visit_time, h.visit_count,
                           h.browser_type, h.profile_name, h.metadata
                    FROM history h
                    JOIN history_fts fts ON h.id = fts.rowid
                    WHERE history_fts MATCH ?
                """
                params: list = [_build_fts_query(keyword)]
            else:
                like_pat = f"%{keyword}%"
                sql = """
                    SELECT h.id, h.url, h.title, h.visit_time, h.visit_count,
                           h.browser_type, h.profile_name, h.metadata
                    FROM history h
                    WHERE (h.url LIKE ? OR h.title LIKE ?)
                """
                params = [like_pat, like_pat]
            extra: list[str] = []
            if browser_type:
                extra.append("h.browser_type = ?")
                params.append(browser_type)
            if date_from is not None:
                extra.append("h.visit_time >= ?")
                params.append(date_from)
            if date_to is not None:
                extra.append("h.visit_time <= ?")
                params.append(date_to)
            if extra:
                sql += " AND " + " AND ".join(extra)
            sql += " ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            with self._conn() as conn:
                self._populate_excl_table(conn, excl)
                if excl:
                    sql = sql.replace(
                        " ORDER BY h.visit_time DESC LIMIT ? OFFSET ?",
                        f" AND {self._excl_clause('h.')} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?",
                    )
                rows = conn.execute(sql, params).fetchall()
        else:
            conditions: list[str] = []
            params = []
            if browser_type:
                conditions.append("browser_type = ?")
                params.append(browser_type)
            if date_from is not None:
                conditions.append("visit_time >= ?")
                params.append(date_from)
            if date_to is not None:
                conditions.append("visit_time <= ?")
                params.append(date_to)
            sql = "SELECT id, url, title, visit_time, visit_count, browser_type, profile_name, metadata FROM history"
            with self._conn() as conn:
                self._populate_excl_table(conn, excl)
                if excl:
                    conditions.append(self._excl_clause())
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                sql += " ORDER BY visit_time DESC LIMIT ? OFFSET ?"
                params += [limit, offset]
                rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_filtered_count(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
        excluded_ids: set[int] | None = None,
    ) -> int:
        excl = excluded_ids or set()
        if keyword:
            use_fts = len(keyword.replace(" ", "")) >= 3
            if use_fts:
                sql = """
                    SELECT COUNT(*) FROM history h
                    JOIN history_fts fts ON h.id = fts.rowid
                    WHERE history_fts MATCH ?
                """
                params: list = [_build_fts_query(keyword)]
            else:
                like_pat = f"%{keyword}%"
                sql = """
                    SELECT COUNT(*) FROM history h
                    WHERE (h.url LIKE ? OR h.title LIKE ?)
                """
                params = [like_pat, like_pat]
            extra: list[str] = []
            if browser_type:
                extra.append("h.browser_type = ?")
                params.append(browser_type)
            if date_from is not None:
                extra.append("h.visit_time >= ?")
                params.append(date_from)
            if date_to is not None:
                extra.append("h.visit_time <= ?")
                params.append(date_to)
            if extra:
                sql += " AND " + " AND ".join(extra)
            with self._conn() as conn:
                self._populate_excl_table(conn, excl)
                if excl:
                    sql += f" AND {self._excl_clause('h.')}"
                row = conn.execute(sql, params).fetchone()
                return row[0] if row else 0
        else:
            conditions: list[str] = []
            params = []
            if browser_type:
                conditions.append("browser_type = ?")
                params.append(browser_type)
            if date_from is not None:
                conditions.append("visit_time >= ?")
                params.append(date_from)
            if date_to is not None:
                conditions.append("visit_time <= ?")
                params.append(date_to)
            sql = "SELECT COUNT(*) FROM history"
            with self._conn() as conn:
                self._populate_excl_table(conn, excl)
                if excl:
                    conditions.append(self._excl_clause())
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                row = conn.execute(sql, params).fetchone()
                return row[0] if row else 0

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
            cursor = conn.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)
            return cursor.rowcount

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

    def delete_records_by_domain(self, domain: str) -> int:
        with self._conn() as conn:
            ids = self._domain_ids_for(conn, domain)
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            cursor = conn.execute(f"DELETE FROM history WHERE domain_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM domains WHERE id IN ({placeholders})", ids)
            return cursor.rowcount

    def get_domain_count(self, domain: str) -> int:
        with self._conn() as conn:
            ids = self._domain_ids_for(conn, domain)
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            row = conn.execute(
                f"SELECT COUNT(*) FROM history WHERE domain_id IN ({placeholders})", ids
            ).fetchone()
            return row[0] if row else 0

    def get_records_by_ids(self, ids: list[int]) -> list[HistoryRecord]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, url, title, visit_time, visit_count, browser_type, profile_name, metadata "
                f"FROM history WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _row_to_record(row) -> HistoryRecord:
        return HistoryRecord(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            visit_time=row["visit_time"],
            visit_count=row["visit_count"],
            browser_type=row["browser_type"],
            profile_name=row["profile_name"],
            metadata=row["metadata"],
        )


def _is_fts_special(keyword: str) -> bool:
    """Return True if the keyword contains FTS5 special characters or operators."""
    import re
    return bool(re.search(r'[()"\*]|(?<!\w)(AND|OR|NOT)(?!\w)', keyword))


def _build_fts_query(keyword: str) -> str:
    if not keyword:
        return '""'
    escaped = keyword.replace('"', '""')
    return f'"{escaped}"*'
