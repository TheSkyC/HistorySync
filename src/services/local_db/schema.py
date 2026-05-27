# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import sqlite3
import threading

from src.utils.logger import get_logger

from ._helpers import _quote_identifier, _sanitize_col_type

log = get_logger("local_db")


class _SchemaMixin:
    """Schema initialisation, migration and FTS5 integrity verification."""

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

                CREATE INDEX IF NOT EXISTS idx_history_browser
                    ON history(browser_type);
                CREATE INDEX IF NOT EXISTS idx_history_url
                    ON history(url);
                CREATE INDEX IF NOT EXISTS idx_history_domain
                    ON history(domain_id);
                -- Composite indexes for filtered ORDER BY visit_time DESC, id DESC queries.
                -- Including id as the tiebreaker enables efficient keyset pagination:
                -- the cursor condition (visit_time < ? OR (visit_time = ? AND id < ?))
                -- becomes an index range scan instead of a full table scan.
                CREATE INDEX IF NOT EXISTS idx_history_visit_time_id
                    ON history(visit_time DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_history_browser_time
                    ON history(browser_type, visit_time DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_history_domain_time
                    ON history(domain_id, visit_time DESC, id DESC);

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

                -- Soft-hide by domain; synced across devices like hidden_records.
                -- subdomain_only=0 → hide main domain + all subdomains
                -- subdomain_only=1 → hide only the exact subdomain stored in `domain`
                CREATE TABLE IF NOT EXISTS hidden_domains (
                    domain         TEXT    NOT NULL PRIMARY KEY,
                    subdomain_only INTEGER NOT NULL DEFAULT 0,
                    hidden_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
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
                    history_id    INTEGER,
                    -- Materialised hostname extracted from `url` so visibility filters
                    -- against hidden_domains are pure SQL with no Python-UDF callbacks.
                    -- Populated synchronously by add_bookmark / update_bookmark_tags;
                    -- backfilled for existing rows by _migrate_schema.
                    host          TEXT    NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_bookmarks_url  ON bookmarks(url);
                CREATE INDEX IF NOT EXISTS idx_bookmarks_at   ON bookmarks(bookmarked_at DESC);

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
        self._fts_thread = threading.Thread(  # type: ignore[attr-defined]
            target=self._verify_fts_integrity, daemon=True, name="fts-integrity-check"
        )
        self._fts_thread.start()  # type: ignore[attr-defined]
        log.info("Database schema initialized: %s", self.db_path)  # type: ignore[attr-defined]

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
        with self._conn() as conn:  # type: ignore[attr-defined]
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

            # Rebuild composite indexes to include id as tiebreaker for keyset pagination.
            # The cursor condition (visit_time < ? OR (visit_time = ? AND id < ?)) requires
            # id in the index to avoid a full table scan on every cursor-based page fetch.
            _keyset_indexes = {
                "idx_history_visit_time_id": "history(visit_time DESC, id DESC)",
                "idx_history_browser_time": "history(browser_type, visit_time DESC, id DESC)",
                "idx_history_domain_time": "history(domain_id, visit_time DESC, id DESC)",
            }
            _SAFE_IDX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
            assert all(_SAFE_IDX.match(k) for k in _keyset_indexes), "index names must be internal constants"
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='history'"
                ).fetchall()
            }
            for idx_name, idx_cols in _keyset_indexes.items():
                needs_rebuild = False
                if idx_name not in existing:
                    needs_rebuild = True
                else:
                    # Check if the existing index already includes id (i.e. was built by this migration).
                    sql_row = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
                    ).fetchone()
                    if sql_row and ", id " not in (sql_row[0] or "") and ",id " not in (sql_row[0] or ""):
                        conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                        needs_rebuild = True
                if needs_rebuild:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_cols}")
                    log.info("Schema migration: rebuilt index %s to include id for keyset pagination", idx_name)
            # Drop the old single-column visit_time index superseded by idx_history_visit_time_id.
            if "idx_history_visit_time" in existing:
                conn.execute("DROP INDEX IF EXISTS idx_history_visit_time")
                log.info("Schema migration: dropped superseded index idx_history_visit_time")

            # hidden_domains table — added in later release; safe to run on existing DBs.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hidden_domains (
                    domain         TEXT    NOT NULL PRIMARY KEY,
                    subdomain_only INTEGER NOT NULL DEFAULT 0,
                    hidden_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )

            # bookmarks.host column + supporting indexes — added so visibility
            # filtering against hidden_domains and keyset pagination can run
            # entirely in SQL without per-row Python UDF callbacks.
            try:
                conn.execute("ALTER TABLE bookmarks ADD COLUMN host TEXT NOT NULL DEFAULT ''")
                log.info("Schema migration: added column bookmarks.host")
            except sqlite3.OperationalError:
                # Column already exists.
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_host ON bookmarks(host)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_at_id ON bookmarks(bookmarked_at DESC, id DESC)")
            # One-shot backfill: populate host for any rows still empty.
            # Uses the registered _extract_host UDF so the result matches the
            # value written by add_bookmark / update_bookmark_tags.
            unfilled = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE host = '' AND url != ''").fetchone()[0]
            if unfilled:
                conn.execute(
                    "UPDATE bookmarks SET host = COALESCE(_extract_host(url), '') WHERE host = '' AND url != ''"
                )
                log.info("Schema migration: backfilled bookmarks.host for %d row(s)", unfilled)

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
            with self._conn() as conn:  # type: ignore[attr-defined]
                conn.execute("INSERT INTO history_fts(history_fts) VALUES('integrity-check')")
            log.debug("FTS integrity check passed.")
        except sqlite3.DatabaseError as exc:
            log.warning("FTS integrity check failed (%s) — triggering automatic rebuild.", exc)
            try:
                self.rebuild_fts_index()  # type: ignore[attr-defined]
                log.info("FTS index successfully rebuilt after integrity failure.")
            except Exception as rebuild_exc:
                log.error("FTS rebuild failed: %s", rebuild_exc)
