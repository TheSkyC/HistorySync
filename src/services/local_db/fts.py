# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""FTS5 trigger management and full index rebuilds.

Trigger maintenance is hot-path code: every write to the ``history`` table
relies on the three triggers (``history_ai``, ``history_ad``, ``history_au``)
to keep ``history_fts`` in sync.  A previous process crash between
DROP TRIGGER and CREATE TRIGGER inside :meth:`upsert_records` can leave the
triggers permanently absent, so every write path calls
:meth:`_FtsMixin._ensure_fts_triggers` defensively at the top of its
transaction.
"""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from src.utils.i18n_core import _
from src.utils.logger import get_logger

log = get_logger("local_db")


class _FtsMixin:
    """FTS5 trigger lifecycle and full-index rebuild."""

    @staticmethod
    def _recreate_fts_triggers(conn: sqlite3.Connection) -> None:
        """Create (or recreate) the three FTS5 sync triggers on *conn*.

        Called both from the normal upsert path (step 7) and from the crash-
        recovery check (step 3b) that runs at the start of every upsert_records
        call.  Using IF NOT EXISTS makes it safe to call when triggers already
        exist.
        """
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

    def _ensure_fts_triggers(self, conn: sqlite3.Connection) -> None:
        """Recreate FTS triggers if any are missing.

        SQLite DDL (DROP/CREATE TRIGGER) does not participate in transaction
        rollback.  A process crash between DROP and CREATE — or an exception
        that prevents the upsert_records exception handler from running —
        leaves the triggers permanently absent.  Every write path that relies
        on the triggers for FTS consistency should call this method at the
        top of its ``_conn(write=True)`` block so that a previous crash
        window cannot silently desynchronise the FTS index.
        """
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN "
                "('history_ai','history_ad','history_au')"
            ).fetchall()
        }
        _missing = {"history_ai", "history_ad", "history_au"} - existing
        if _missing:
            log.warning("FTS triggers missing (%s) — repairing", _missing)
            self._recreate_fts_triggers(conn)

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
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute("INSERT INTO history_fts(history_fts) VALUES('rebuild')")
        _cb(_("FTS index rebuild complete."))
