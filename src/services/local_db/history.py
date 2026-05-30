# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator
import re
import sqlite3
import time

from src.models.history_record import BackupStats, HistoryRecord
import src.services.local_db as _pkg
from src.utils.constants import DB_BATCH_SIZE
from src.utils.logger import get_logger
from src.utils.url_utils import (
    extract_host as _extract_url_host,
    normalize_domain,
)

log = get_logger("local_db")


class _HistoryMixin:
    """History CRUD, filtered query builder, and shared scroll helpers."""

    # ── Write operations ──────────────────────────────────────

    def upsert_records(self, records: list[HistoryRecord]) -> int:
        if not records:
            return 0

        # Pre-compute host for every record once in Python (avoids per-row UDF round-trip)
        rec_hosts = [_extract_url_host(r.url) for r in records]

        with self._conn() as conn:  # type: ignore[attr-defined]
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

            # 3b. Recover from a previous crash that left FTS triggers missing.
            # SQLite DDL (DROP/CREATE TRIGGER) does not participate in transaction
            # rollback, so a process crash between DROP and CREATE leaves the
            # triggers permanently absent.  Detect and repair that state here
            # before we potentially drop them again below.
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]

            # 4-8. Wrap the trigger DDL + bulk insert + FTS sync in a SAVEPOINT
            #      so a mid-operation crash leaves the DB consistent for DML
            #      (no partial inserts).  Note: SQLite DDL (DROP/CREATE TRIGGER)
            #      does NOT roll back with the savepoint — see comment in step 7
            #      for how we mitigate the crash window.
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
                # If the process crashes between DROP (step 4) and here, the
                # triggers will be absent on the next run.  Step 3b detects and
                # repairs that state at the start of the next upsert_records call.
                if _disable_triggers:
                    self._recreate_fts_triggers(conn)  # type: ignore[attr-defined]

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
                if _disable_triggers:
                    # DDL (DROP TRIGGER) does not roll back with the savepoint,
                    # so triggers may be permanently absent after this exception.
                    # Restore them immediately; step 3b will also catch this on
                    # the next call, but closing the window here prevents other
                    # write paths (delete_records_by_ids, merge_from_db) from
                    # silently skipping FTS updates in the interim.
                    try:
                        self._recreate_fts_triggers(conn)  # type: ignore[attr-defined]
                    except Exception:
                        pass  # step 3b will repair on next upsert_records call
                raise

        log.info("Upserted %d / %d records", inserted, len(records))
        return inserted

    def update_backup_stats(
        self,
        browser_type: str,
        profile_name: str,
        records_synced: int,
        db_mtime: float = 0.0,
    ) -> None:
        now = int(time.time())
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                INSERT INTO backup_stats
                    (browser_type, profile_name, first_backup_time, last_backup_time, total_records_synced, last_db_mtime)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(browser_type, profile_name) DO UPDATE SET
                    last_backup_time     = excluded.last_backup_time,
                    last_db_mtime        = excluded.last_db_mtime,
                    total_records_synced = total_records_synced + excluded.total_records_synced
            """,
                (browser_type, profile_name, now, now, records_synced, db_mtime),
            )

    # ═══════════════════════════════════════════════════════════
    # Read operations
    # ═══════════════════════════════════════════════════════════

    def get_total_count(self) -> int:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
            return row[0] if row else 0

    def get_max_visit_times(self, browser_type: str) -> dict[str, int]:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
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
        with self._excl_cache_lock:  # type: ignore[attr-defined]
            cached: frozenset[int] | None = self._excl_cache.get(conn)  # type: ignore[attr-defined]
            if cached != excl:
                conn.execute("DELETE FROM _excl_ids")
                conn.executemany("INSERT OR IGNORE INTO _excl_ids VALUES(?)", ((i,) for i in excl))
                self._excl_cache[conn] = frozenset(excl)  # type: ignore[attr-defined]
        return True

    @staticmethod
    def _excl_clause(alias: str = "") -> str:
        col = f"{alias}id" if alias else "id"
        return f"{col} NOT IN (SELECT id FROM _excl_ids)"

    @staticmethod
    def _incl_clause(alias: str = "") -> str:
        """SQL fragment: restrict to only the IDs in the temp table (hidden-only mode)."""
        col = f"{alias}id" if alias else "id"
        return f"{col} IN (SELECT id FROM _excl_ids)"

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
        hidden_only: bool = False,
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
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                hidden_only=hidden_only,
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
        hidden_only: bool = False,
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
            use_fts = not _force_like and _pkg._keyword_eligible_for_fts(keyword)
            if use_fts:
                from_where = (
                    "FROM history h\n    JOIN history_fts fts ON h.id = fts.rowid\n    WHERE history_fts MATCH ?"
                )
                fts_keyword = keyword
                if title_only:
                    fts_keyword = f"title:{keyword}"
                elif url_only:
                    fts_keyword = f"url:{keyword}"
                params = [_pkg._build_fts_query(fts_keyword)]
            else:
                like_pat = f"%{_pkg._escape_like(keyword)}%"
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
            extra_conditions.append("LOWER(h.browser_type) = ?")
            params.append(browser_type.lower())
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
                params.extend([f"%{_pkg._escape_like(ex)}%", f"%{_pkg._escape_like(ex)}%"])
        if excluded_ids:
            if hidden_only:
                extra_conditions.append(self._incl_clause("h."))
            else:
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
        cursor: tuple[int, int] | None = None,  # (visit_time, id) for keyset pagination
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
        hidden_only: bool = False,
    ) -> list[HistoryRecord]:
        excl = excluded_ids or set()

        if use_regex and keyword:
            try:
                prog = re.compile(keyword, re.IGNORECASE)
            except re.error as exc:
                log.warning("Invalid regex '%s': %s", keyword, exc)
                return []

            pat_str = prog.pattern
            if title_only:
                regex_cond = "h.title REGEXP ?"
                regex_params: list = [pat_str]
            elif url_only:
                regex_cond = "h.url REGEXP ?"
                regex_params = [pat_str]
            else:
                regex_cond = "(h.title REGEXP ? OR h.url REGEXP ?)"
                regex_params = [pat_str, pat_str]

            _RCOLS = (
                "h.id, h.url, h.title, h.visit_time, h.visit_count, "
                "h.browser_type, h.profile_name, h.metadata, "
                "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
                "h.device_id, d.host AS domain"
            )
            with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                    hidden_only=hidden_only,
                )
                connector = " AND " if "WHERE" in from_where else " WHERE "
                sql = f"SELECT {_RCOLS} {from_where}{connector}{regex_cond} ORDER BY h.visit_time DESC, h.id DESC LIMIT ? OFFSET ?"
                rows = conn.execute(sql, base_params + regex_params + [limit, offset]).fetchall()
            return [self._row_to_record(row) for row in rows]

        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                hidden_only=hidden_only,
            )
            # Strip the domains LEFT JOIN injected by _build_query_parts.
            # The id-scan query only needs h.id; keeping the JOIN prevents SQLite
            # from using a covering index and makes every page fetch ~5x slower.
            # Domain host is resolved in the second step via get_records_by_ids.
            id_from_where = from_where.replace(" LEFT JOIN domains d ON h.domain_id = d.id", "", 1)
            if cursor is not None:
                vt, rid = cursor
                connector = " AND " if "WHERE" in id_from_where else " WHERE "
                # Rewrite the keyset condition as UNION ALL so SQLite uses two
                # index range scans instead of a full covering-index SCAN.
                # The OR form forces a full scan even with (visit_time DESC, id DESC).
                lt_where = id_from_where + f"{connector}h.visit_time < ?"
                eq_where = id_from_where + f"{connector}h.visit_time = ? AND h.id < ?"
                id_sql = (
                    f"SELECT id FROM ("
                    f"SELECT h.id, h.visit_time {lt_where}"
                    f" UNION ALL "
                    f"SELECT h.id, h.visit_time {eq_where}"
                    f") ORDER BY visit_time DESC, id DESC LIMIT ?"
                )
                id_params = [*params, vt, *params, vt, rid, limit]
            else:
                id_sql = f"SELECT h.id {id_from_where} ORDER BY h.visit_time DESC, h.id DESC LIMIT ? OFFSET ?"
                id_params = [*params, limit, offset]
            try:
                id_rows = conn.execute(id_sql, id_params).fetchall()
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
                        cursor=cursor,
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
                        hidden_only=hidden_only,
                    )
                raise
            if not id_rows:
                return []
            # Resolve full columns + domain host in one query using the page ids.
            # JOIN on the PK index (200 rows) is cheap; the covering-index scan above
            # already did the expensive pagination work.  Using a CTE keeps both steps
            # in the same connection context (single lock acquisition) and preserves
            # visit_time DESC order via the final ORDER BY.
            page_ids = [r[0] for r in id_rows]
            placeholders = ",".join("?" * len(page_ids))
            _COLS = (
                "h.id, h.url, h.title, h.visit_time, h.visit_count, "
                "h.browser_type, h.profile_name, h.metadata, "
                "h.typed_count, h.first_visit_time, h.transition_type, h.visit_duration, "
                "h.device_id, d.host AS domain"
            )
            full_rows = conn.execute(
                f"SELECT {_COLS} FROM history h "
                f"LEFT JOIN domains d ON h.domain_id = d.id "
                f"WHERE h.id IN ({placeholders}) "
                f"ORDER BY h.visit_time DESC, h.id DESC",
                page_ids,
            ).fetchall()
            return [self._row_to_record(r) for r in full_rows]

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
        hidden_only: bool = False,
    ) -> int | None:
        """Return only the visit_time of the record at *offset* in the current
        filtered result set.  Much cheaper than get_records() for scroll-bubble
        updates because it fetches a single integer instead of full rows."""
        excl = excluded_ids or set()
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                hidden_only=hidden_only,
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
        hidden_only: bool = False,
    ) -> int:
        excl = excluded_ids or set()

        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                hidden_only=hidden_only,
            )
            # Strip the domains LEFT JOIN — COUNT(*) never needs d.host,
            # and the extra JOIN forces a full scan on large tables.
            count_from_where = from_where.replace(" LEFT JOIN domains d ON h.domain_id = d.id", "", 1)
            sql = f"SELECT COUNT(*) {count_from_where}"
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
                        hidden_only=hidden_only,
                    )
                raise
            return row[0] if row else 0

    def get_browser_types(self) -> list[str]:
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT DISTINCT browser_type FROM history ORDER BY browser_type").fetchall()
            return [r[0] for r in rows]

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

        _any_short_word = keyword and not _pkg._keyword_eligible_for_fts(keyword)
        if keyword and _any_short_word:
            from_clause = "FROM history h"
            conditions.append("(h.title LIKE ? ESCAPE '\\' OR h.url LIKE ? ESCAPE '\\')")
            params.extend([f"%{_pkg._escape_like(keyword)}%", f"%{_pkg._escape_like(keyword)}%"])
        elif keyword:
            fts_query = _pkg._build_fts_query(keyword)
            from_clause = "FROM history_fts fts JOIN history h ON h.id = fts.rowid"
            conditions.append("history_fts MATCH ?")
            params.append(fts_query)
        else:
            from_clause = "FROM history h"

        if browser_type and browser_type not in ("auto", "all"):
            conditions.append("h.browser_type = ?")
            params.append(browser_type)

        conditions.append("_hr.url IS NULL")
        conditions.append(self._hd_filter(history_alias="h", domain_alias="d"))  # type: ignore[attr-defined]

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        # Inject domains JOIN and hidden_records anti-join so the optimizer can
        # use the hidden_records PRIMARY KEY index instead of a correlated subquery.
        from_clause_with_join = from_clause.replace(
            "FROM history h",
            "FROM history h LEFT JOIN domains d ON h.domain_id = d.id LEFT JOIN hidden_records _hr ON _hr.url = h.url",
            1,
        )
        sql = f"SELECT {_COLS} {from_clause_with_join} {where} ORDER BY h.visit_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._ro_lock:  # type: ignore[attr-defined]
            conn = self._ensure_ro_conn()  # type: ignore[attr-defined]
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.ProgrammingError:
                # Connection was closed by _reset_conn between acquire and execute — rebuild.
                self._ro_conn = None  # type: ignore[attr-defined]
                conn = self._ensure_ro_conn()  # type: ignore[attr-defined]
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS index unavailable — fall back to LIKE
                if keyword:
                    from_clause = (
                        "FROM history h LEFT JOIN domains d ON h.domain_id = d.id"
                        " LEFT JOIN hidden_records _hr ON _hr.url = h.url"
                    )
                    conditions = [
                        "(h.title LIKE ? ESCAPE '\\' OR h.url LIKE ? ESCAPE '\\')",
                        "_hr.url IS NULL",
                        self._hd_filter(history_alias="h", domain_alias="d"),  # type: ignore[attr-defined]
                    ]
                    params = [f"%{_pkg._escape_like(keyword)}%", f"%{_pkg._escape_like(keyword)}%"]
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
                        self._ro_conn = None  # type: ignore[attr-defined]
                        conn = self._ensure_ro_conn()  # type: ignore[attr-defined]
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
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT host FROM domains").fetchall()
        return {r[0] for r in rows}

    # ── Backup-stats CRUD ─────────────────────────────────────

    def get_all_backup_stats(self) -> list[BackupStats]:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("""
                SELECT id, browser_type, profile_name,
                       first_backup_time, last_backup_time, total_records_synced, last_db_mtime
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
                last_db_mtime=r["last_db_mtime"],
            )
            for r in rows
        ]

    def get_last_sync_time(self) -> int | None:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT MAX(last_backup_time) FROM backup_stats").fetchone()
            return row[0] if row and row[0] else None

    # ── Privacy / management ──────────────────────────────────

    def delete_records_by_ids(self, ids: list[int]) -> int:
        if not ids:
            return 0
        _CHUNK = 900
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
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
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
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
        domain_norm = normalize_domain(domain)
        if not domain_norm:
            return []
        rows = conn.execute(
            "SELECT id FROM domains WHERE host = ? OR host LIKE ? ESCAPE '\\'",
            (domain_norm, "%." + _pkg._escape_like(domain_norm)),
        ).fetchall()
        return [r[0] for r in rows]

    def get_domain_ids(self, domains: list[str]) -> list[int]:
        """Return all domain.id values matching *domains* and their subdomains.

        Public interface used by CLI export and other callers that need to
        resolve domain names to IDs without accessing internal connection state.
        """
        if not domains:
            return []
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            ids: list[int] = []
            for d in domains:
                ids.extend(self._domain_ids_for(conn, d))
        return list(set(ids))

    def delete_records_by_domain(self, domain: str) -> int:
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
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
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            for d in domains:
                ids.extend(self._domain_ids_for(conn, d))
        return ids

    def get_domain_count(self, domain: str) -> int:
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
        hidden_only: bool = False,
    ) -> list[tuple[int, int]]:
        """Return (id, visit_time) for all matching rows ordered visit_time DESC.

        Much lighter than get_records() — only two integers per row.  Used to
        build a lightweight scroll index so page fetches can use WHERE id IN (...)
        instead of LIMIT/OFFSET full-table scans.
        """
        excl = excluded_ids or set()
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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
                hidden_only=hidden_only,
            )
            sql = f"SELECT h.id, h.visit_time {from_where} ORDER BY h.visit_time DESC"
            cur = conn.execute(sql, params)
            return [(row[0], row[1]) for row in cur]

    def get_records_by_ids(self, ids: list[int]) -> list[HistoryRecord]:
        if not ids:
            return []
        _CHUNK = 900
        rows: list[sqlite3.Row] = []
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
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

    def _get_row_offset_for_target(
        self,
        *,
        target_condition: str,
        target_params: list,
        excluded_ids: set[int] | None = None,
        hidden_only: bool = False,
    ) -> int:
        """Return the 0-based row offset for the first row matching *target_condition*.

        The target is resolved and ranked against the exact same dataset rules
        used by the history page: hidden-record exclusion or inclusion, plus
        the same total ordering (visit_time DESC, id DESC).
        """
        excl = excluded_ids or set()
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            from_where, params, _ = self._build_query_parts(
                conn=conn,
                keyword="",
                browser_type="",
                date_from=None,
                date_to=None,
                excluded_ids=excl,
                domain_ids=None,
                excludes=None,
                title_only=False,
                url_only=False,
                bookmarked_only=False,
                has_annotation=False,
                bookmark_tag="",
                _force_like=False,
                device_ids=None,
                hidden_only=hidden_only,
            )
            from_where = from_where.replace(" LEFT JOIN domains d ON h.domain_id = d.id", "", 1)
            connector = " AND " if "WHERE" in from_where else " WHERE "

            target = conn.execute(
                f"SELECT h.id, h.visit_time {from_where}{connector}{target_condition} "
                "ORDER BY h.visit_time DESC, h.id DESC LIMIT 1",
                [*params, *target_params],
            ).fetchone()
            if target is None:
                return -1

            target_id = target["id"]
            target_visit_time = target["visit_time"]
            row = conn.execute(
                f"SELECT COUNT(*) {from_where}{connector}(h.visit_time > ? OR (h.visit_time = ? AND h.id > ?))",
                [*params, target_visit_time, target_visit_time, target_id],
            ).fetchone()
            return int(row[0]) if row is not None else -1

    def get_row_offset_for_history_id(
        self,
        history_id: int,
        excluded_ids: set[int] | None = None,
        hidden_only: bool = False,
    ) -> int:
        """Return the 0-based row index for a specific history row id.

        Returns -1 if the row is not part of the current dataset.
        """
        return self._get_row_offset_for_target(
            target_condition="h.id = ?",
            target_params=[history_id],
            excluded_ids=excluded_ids,
            hidden_only=hidden_only,
        )

    def get_row_offset_for_url(
        self,
        url: str,
        excluded_ids: set[int] | None = None,
        hidden_only: bool = False,
    ) -> int:
        """Return the 0-based row index of the most-recent matching URL.

        The lookup is performed against the same dataset rules as the history
        page, not against the raw history table.
        """
        return self._get_row_offset_for_target(
            target_condition="h.url = ?",
            target_params=[url],
            excluded_ids=excluded_ids,
            hidden_only=hidden_only,
        )

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
            domain = row["domain"] or _pkg._extract_display_domain(row["url"])
        except IndexError:
            domain = _pkg._extract_display_domain(row["url"])
        # Positional construction is ~20% faster than keyword args with __slots__
        return HistoryRecord(
            row["url"],
            row["title"],
            row["visit_time"],
            row["visit_count"],
            row["browser_type"],
            row["profile_name"],
            domain,
            row["metadata"],
            row["typed_count"],
            row["first_visit_time"],
            row["transition_type"],
            row["visit_duration"],
            row["id"],
            device_id,
        )
