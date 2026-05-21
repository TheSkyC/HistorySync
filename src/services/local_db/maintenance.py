# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import sqlite3

from src.utils.i18n_core import _
from src.utils.logger import get_logger

from ._helpers import DbStats, _quote_identifier, _sanitize_vacuum_path

log = get_logger("local_db")


class _MaintenanceMixin:
    """VACUUM, tombstone prune, domain normalisation, FTS-stripped export, replace."""

    def get_db_stats(self) -> DbStats:
        """Return a snapshot of size and content metrics (read-only)."""
        file_size = self.db_path.stat().st_size if self.db_path.exists() else 0  # type: ignore[attr-defined]

        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
            except sqlite3.Error:
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

    def get_visit_time_range(self) -> tuple[int, int] | None:
        """Return (min_visit_time, max_visit_time) across all history records, or None if empty."""
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT MIN(visit_time), MAX(visit_time) FROM history").fetchone()
        if row and row[0] and row[1]:
            return (row[0], row[1])
        return None

    def prune_tombstones(self, keep_days: int = 90) -> int:
        """Delete tombstone rows older than *keep_days* from all three soft-delete tables.

        Tombstones only need to survive long enough for every device to sync at
        least once.  Keeping 90 days is more than sufficient for any reasonable
        sync cadence, and prevents the tables from growing without bound.

        Returns the total number of rows deleted across all three tables.
        """
        import time as _time

        threshold = int(_time.time()) - keep_days * 86400
        total = 0
        with self._conn(write=True) as conn:  # type: ignore[attr-defined]
            for table in ("deleted_records", "deleted_bookmarks", "deleted_annotations"):
                cur = conn.execute(f"DELETE FROM {table} WHERE deleted_at < ?", (threshold,))
                total += cur.rowcount
        if total:
            log.info("prune_tombstones: removed %d expired rows (keep_days=%d)", total, keep_days)
        return total

    def vacuum_and_analyze(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        def _cb(msg: str):
            if progress_cb:
                progress_cb(msg)
            log.info("vacuum: %s", msg)

        db_path: Path = self.db_path  # type: ignore[attr-defined]
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
        with self._lock:  # type: ignore[attr-defined]
            self._vacuuming = True  # type: ignore[attr-defined]
            self._reset_conn()  # type: ignore[attr-defined]

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
            with self._lock:  # type: ignore[attr-defined]
                self._vacuuming = False  # type: ignore[attr-defined]

        pruned = self.prune_tombstones()
        if pruned:
            _cb(_("Pruned {n} expired tombstone rows (>90 days old).").format(n=pruned))

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

        Implementation note — why two VACUUM INTO calls are required
        ────────────────────────────────────────────────────────────
        SQLite's DROP TABLE (including DROP of a virtual FTS5 table and all its
        shadow tables) only marks those pages as *free* in the freelist; it does
        NOT reclaim the physical file space.  The freed pages stay in the file
        until a VACUUM rewrites the database from scratch.

        For an FTS5 trigram index the shadow tables (data, idx, content, docsize,
        config) typically account for 60-80 % of the total database size.  If we
        skip the second VACUUM the exported file is almost as large as the
        original, and the "FTS stripped: X MB → Y MB" log line shows only a
        tiny reduction (a few MB of page-header bookkeeping) instead of the
        expected multi-tens-of-MB saving.

        The two-phase approach:
          1. VACUUM INTO  — copy the *live* DB (including FTS) to a temp file,
                            consolidating any existing freelist in the source.
          2. DROP FTS     — logically remove FTS virtual table, shadow tables,
                            and triggers in the temp file (adds to freelist).
          3. VACUUM INTO  — rewrite the temp file into *dest*, physically
                            reclaiming the now-freed FTS pages.

        The extra VACUUM pass is necessary to actually shrink the file; ZIP
        compression at the upload layer can compress zero-filled freed pages
        but delivers only a fraction of the saving compared to genuinely
        removing those pages.
        """
        dest_path = dest.absolute().as_posix()
        if dest.exists():
            dest.unlink()

        # ── Phase 1: VACUUM INTO a staging file ──────────────────────────────
        # Use a sibling temp file so both files land on the same filesystem,
        # preventing cross-device rename errors and guaranteeing that the disk
        # has enough space for both copies simultaneously.
        staging = dest.with_suffix(".staging.db")
        staging_path = staging.absolute().as_posix()
        if staging.exists():
            staging.unlink()

        # VACUUM INTO can take tens of seconds on large databases.  Holding
        # _lock for that duration blocks every write operation (hide record,
        # add bookmark, etc.) for the entire duration.  Instead, reset the
        # persistent connection under the lock (same pattern as
        # vacuum_and_analyze) and run VACUUM INTO outside the lock via an
        # independent connection.  SQLite's own file-level locking prevents
        # concurrent writers from corrupting the source while we read it.
        with self._lock:  # type: ignore[attr-defined]
            self._reset_conn()  # type: ignore[attr-defined]

        try:
            vac_conn = sqlite3.connect(str(self.db_path), timeout=120)  # type: ignore[attr-defined]
            try:
                safe_staging = _sanitize_vacuum_path(staging_path)
                vac_conn.execute(f"VACUUM INTO '{safe_staging}'")
            finally:
                vac_conn.close()

            # ── Phase 2: DROP FTS objects in the staging copy ────────────────
            stage_conn = sqlite3.connect(staging_path, timeout=30)
            try:
                stage_conn.isolation_level = None  # autocommit for DDL

                # Drop triggers first so the virtual table can be removed cleanly.
                stage_conn.execute("DROP TRIGGER IF EXISTS history_ai")
                stage_conn.execute("DROP TRIGGER IF EXISTS history_ad")
                stage_conn.execute("DROP TRIGGER IF EXISTS history_au")

                # Drop the FTS5 virtual table (also removes its shadow tables).
                stage_conn.execute("DROP TABLE IF EXISTS history_fts")

                # Belt-and-suspenders: remove any lingering history_* triggers.
                cursor = stage_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'history_%'"
                )
                for (trigger_name,) in cursor.fetchall():
                    stage_conn.execute(f"DROP TRIGGER IF EXISTS {_quote_identifier(trigger_name)}")

                # Verify nothing FTS-related remains in sqlite_master.
                cursor = stage_conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'history_fts%'")
                leftovers = [row[0] for row in cursor.fetchall()]
                if leftovers:
                    log.warning("FTS stripping completed with leftovers: %s", leftovers)
                else:
                    log.info("FTS stripping successful: All related tables and triggers removed.")

                # ── Phase 3: VACUUM INTO dest to reclaim freed FTS pages ──────
                # After DROP TABLE the pages are only on the freelist; a second
                # VACUUM INTO physically rewrites the file without them, which is
                # what actually shrinks the backup.
                safe_dest = _sanitize_vacuum_path(dest_path)
                stage_conn.execute(f"VACUUM INTO '{safe_dest}'")

            finally:
                stage_conn.close()

        finally:
            # Always clean up the intermediate staging file.
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass

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
        with self._conn() as conn:  # type: ignore[attr-defined]
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
            with self._conn() as conn:  # type: ignore[attr-defined]
                self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
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

    def replace_database(self, new_db_path: Path) -> None:
        """Safely replace the underlying SQLite file (used for WebDAV restore)."""
        if self._fts_thread is not None and self._fts_thread.is_alive():  # type: ignore[attr-defined]
            self._fts_thread.join(timeout=10)  # type: ignore[attr-defined]
        with self._conn_state_locks():  # type: ignore[attr-defined]
            log.info("Replacing current database with %s", new_db_path)
            # Close all connections before touching the file so that
            # search_quick cannot read a partially-written DB on Windows
            # (which disallows overwriting open files) or any platform.
            self._reset_conn_locked()  # type: ignore[attr-defined]
            self._schema_initialized = False  # type: ignore[attr-defined]
            for suffix in ("-wal", "-shm"):
                p = self.db_path.with_name(self.db_path.name + suffix)  # type: ignore[attr-defined]
                if p.exists():
                    try:
                        p.unlink()
                    except OSError as exc:
                        log.warning("Failed to delete %s: %s", p.name, exc)
            shutil.copy2(new_db_path, self.db_path)  # type: ignore[attr-defined]
            log.info("Database successfully replaced")
