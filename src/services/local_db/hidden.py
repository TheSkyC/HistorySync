# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

from src.utils.logger import get_logger
from src.utils.url_utils import normalize_domain

log = get_logger("local_db")


class _HiddenMixin:
    """Hidden-record and hidden-domain CRUD plus shared filter SQL fragments."""

    # ── Hidden records CRUD ───────────────────────────────────

    def get_all_hidden_ids(self) -> set[int]:
        """Return the combined set of hidden record IDs (URL-level + domain-level).

        Explicitly ends any open read transaction on the shared read-only
        connection before querying, so callers always see the latest committed
        data rather than a stale WAL snapshot from a previous read.
        """
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            url_ids = self.get_hidden_ids(_conn=conn)
            domain_ids = self.get_hidden_domain_ids(_conn=conn)
        return url_ids | domain_ids

    def hide_records_by_ids(self, ids: list[int]) -> None:
        """Mark the given record ids as hidden (stored by URL for cross-device stability)."""
        if not ids:
            return
        _CHUNK = 900
        with self._conn() as conn:  # type: ignore[attr-defined]
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
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT url FROM hidden_records").fetchall()
        return {r[0] for r in rows}

    def get_hidden_ids(
        self, candidate_ids: set[int] | None = None, _conn: sqlite3.Connection | None = None
    ) -> set[int]:
        """Return DB ids of records whose URL is in hidden_records.

        If *candidate_ids* is provided, only those rows are checked (faster
        for the common case where we know which IDs might be affected).
        If *_conn* is provided, use it directly instead of opening a new connection.
        """
        if candidate_ids is not None and len(candidate_ids) == 0:
            return set()
        _CHUNK = 900

        def _query(conn: sqlite3.Connection) -> set[int]:
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

        if _conn is not None:
            return _query(_conn)
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            return _query(conn)

    def clear_hidden_records(self) -> int:
        """Delete all entries from hidden_records. Returns the number removed."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute("DELETE FROM hidden_records")
            return cursor.rowcount

    def unhide_records_by_ids(self, ids: list[int]) -> None:
        """Remove hidden_records entries for the given record IDs."""
        if not ids:
            return
        _CHUNK = 900
        with self._conn() as conn:  # type: ignore[attr-defined]
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i : i + _CHUNK]
                placeholders = ",".join("?" * len(chunk))
                conn.execute(
                    f"DELETE FROM hidden_records WHERE url IN (SELECT url FROM history WHERE id IN ({placeholders}))",
                    chunk,
                )

    def hide_records_by_domain(self, domain: str, subdomain_only: bool) -> int:
        """Insert all current records matching *domain* into hidden_records (URL-level).

        Used when the user hides a domain without enabling auto-hide, so only
        the records that exist right now are hidden — future synced records are
        **not** filtered.  Returns the number of distinct URLs hidden.
        """
        with self._conn() as conn:  # type: ignore[attr-defined]
            d_ids = self._domain_ids_for_hide(conn, domain, subdomain_only)
            if not d_ids:
                return 0
            placeholders = ",".join("?" * len(d_ids))
            urls = conn.execute(
                f"SELECT DISTINCT url FROM history WHERE domain_id IN ({placeholders})", d_ids
            ).fetchall()
            if urls:
                conn.executemany(
                    "INSERT OR IGNORE INTO hidden_records(url) VALUES(?)",
                    ((r[0],) for r in urls),
                )
            return len(urls)

    # ── Stats filter helpers ──────────────────────────────────

    @staticmethod
    def _hr_filter(alias: str = "history") -> str:
        """SQL fragment: exclude URL-level hidden records."""
        return f"NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = {alias}.url)"

    @staticmethod
    def _hd_filter(history_alias: str = "history", domain_alias: str | None = None) -> str:
        """SQL fragment: exclude hidden-domain records.

        If *domain_alias* names an already-joined ``domains`` table alias the
        host column is referenced directly (no extra join).  Otherwise an
        inline ``JOIN domains`` subquery is used.

        hd.domain values are escaped via REPLACE() before use in LIKE patterns
        so that any literal % or _ in a stored domain name is not treated as a
        wildcard character.
        """
        # Escape % and _ in hd.domain so they are treated as literals in LIKE
        _escaped = "REPLACE(REPLACE(hd.domain, '%', '\\%'), '_', '\\_')"
        if domain_alias:
            return (
                f"NOT EXISTS (SELECT 1 FROM hidden_domains hd "
                f"WHERE (hd.subdomain_only = 1 AND {domain_alias}.host = hd.domain) "
                f"OR (hd.subdomain_only = 0 AND "
                f"({domain_alias}.host = hd.domain OR {domain_alias}.host LIKE '%.' || {_escaped} ESCAPE '\\')))"
            )
        return (
            f"NOT EXISTS (SELECT 1 FROM hidden_domains hd "
            f"JOIN domains _hdd ON _hdd.id = {history_alias}.domain_id "
            f"WHERE (hd.subdomain_only = 1 AND _hdd.host = hd.domain) "
            f"OR (hd.subdomain_only = 0 AND "
            f"(_hdd.host = hd.domain OR _hdd.host LIKE '%.' || {_escaped} ESCAPE '\\')))"
        )

    # ── Hidden domains CRUD ───────────────────────────────────

    def hide_domain(self, domain: str, subdomain_only: bool = False) -> None:
        """Persist *domain* in hidden_domains for query-time filtering.

        If the domain is already present, REPLACE updates the subdomain_only
        flag and resets hidden_at so the most-recent intent wins.
        """
        if not domain:
            return
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT OR REPLACE INTO hidden_domains(domain, subdomain_only) VALUES(?, ?)",
                (domain, 1 if subdomain_only else 0),
            )
        log.debug("hide_domain: added '%s' (subdomain_only=%s)", domain, subdomain_only)

    def unhide_domain(self, domain: str) -> None:
        """Remove *domain* from hidden_domains."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute("DELETE FROM hidden_domains WHERE domain = ?", (domain,))
        log.debug("unhide_domain: removed '%s'", domain)

    def get_hidden_domains(self) -> list[dict]:
        """Return all hidden-domain entries as dicts, newest first."""
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT domain, subdomain_only, hidden_at FROM hidden_domains ORDER BY hidden_at DESC"
            ).fetchall()
        return [{"domain": r[0], "subdomain_only": bool(r[1]), "hidden_at": r[2]} for r in rows]

    def count_records_for_domain(self, domain: str, subdomain_only: bool) -> int:
        """Return the number of history rows currently matching *domain*.

        Used by the confirmation dialog to preview how many records will be
        hidden.  Does *not* exclude records already in hidden_records.
        """
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            d_ids = self._domain_ids_for_hide(conn, domain, subdomain_only)
            if not d_ids:
                return 0
            placeholders = ",".join("?" * len(d_ids))
            row = conn.execute(f"SELECT COUNT(*) FROM history WHERE domain_id IN ({placeholders})", d_ids).fetchone()
            return row[0] if row else 0

    def count_records_by_url_prefixes(self, prefixes: list[str]) -> int:
        """Return the number of history rows whose URL starts with any of the given prefixes.

        Used by the confirmation dialog to preview how many records will be deleted
        when URL prefix filters are applied retroactively.
        A single SQL query with OR clauses avoids double-counting URLs that match
        more than one prefix.
        """
        if not prefixes:
            return 0
        escaped = [p.replace("%", r"\%").replace("_", r"\_") + "%" for p in prefixes]
        clauses = " OR ".join(["url LIKE ? ESCAPE '\\'"] * len(escaped))
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            row = conn.execute(f"SELECT COUNT(*) FROM history WHERE {clauses}", escaped).fetchone()
        return row[0] if row else 0

    def delete_records_by_url_prefixes(self, prefixes: list[str]) -> int:
        """Delete history rows whose URL starts with any of the given prefixes.

        Used when retroactively applying URL prefix filters. Returns the total
        number of deleted rows.
        """
        if not prefixes:
            return 0
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
            total_deleted = 0
            for prefix in prefixes:
                escaped = prefix.replace("%", r"\%").replace("_", r"\_")
                # First, tombstone URLs that will be fully deleted
                conn.execute(
                    "INSERT OR IGNORE INTO deleted_records(url) "
                    "SELECT url FROM history WHERE url LIKE ? ESCAPE '\\' "
                    "GROUP BY url "
                    "HAVING COUNT(*) = (SELECT COUNT(*) FROM history h2 WHERE h2.url = history.url)",
                    (escaped + "%",),
                )
                cursor = conn.execute(
                    "DELETE FROM history WHERE url LIKE ? ESCAPE '\\'",
                    (escaped + "%",),
                )
                total_deleted += cursor.rowcount
            return total_deleted

    def get_hidden_domain_ids(self, _conn: sqlite3.Connection | None = None) -> set[int]:
        """Return history record IDs that match any entry in hidden_domains.

        Called by the viewmodel to build the combined excluded-IDs set, which
        is then passed to ``HistoryViewModel.set_hidden_ids()`` so the table
        model filters both URL-hidden and domain-hidden records in one pass.
        If *_conn* is provided, use it directly instead of opening a new connection.
        """

        def _query(conn: sqlite3.Connection) -> set[int]:
            domain_rows = conn.execute("SELECT domain, subdomain_only FROM hidden_domains").fetchall()
            if not domain_rows:
                return set()
            result: set[int] = set()
            _CHUNK = 900
            for domain, subdomain_only in domain_rows:
                d_ids = self._domain_ids_for_hide(conn, domain, bool(subdomain_only))
                if not d_ids:
                    continue
                for i in range(0, len(d_ids), _CHUNK):
                    chunk = d_ids[i : i + _CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    rows = conn.execute(f"SELECT id FROM history WHERE domain_id IN ({placeholders})", chunk).fetchall()
                    result.update(r[0] for r in rows)
            return result

        if _conn is not None:
            return _query(_conn)
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            return _query(conn)

    def clear_hidden_domains(self) -> int:
        """Remove all entries from hidden_domains.  Returns count removed."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute("DELETE FROM hidden_domains")
            return cursor.rowcount

    @staticmethod
    def _domain_ids_for_hide(conn: sqlite3.Connection, domain: str, subdomain_only: bool) -> list[int]:
        """Resolve *domain* to a list of ``domains.id`` values.

        If *subdomain_only* is True only the exact host is matched; otherwise
        the domain itself **and** all subdomains (``LIKE '%.domain'``) match.
        Domain normalisation (lowercase, no port, no leading ``www.``) is
        delegated to :func:`src.utils.url_utils.normalize_domain`.
        """
        domain_norm = normalize_domain(domain)
        if not domain_norm:
            return []
        if subdomain_only:
            rows = conn.execute("SELECT id FROM domains WHERE host = ?", (domain_norm,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM domains WHERE host = ? OR host LIKE ?",
                (domain_norm, "%." + domain_norm),
            ).fetchall()
        return [r[0] for r in rows]
