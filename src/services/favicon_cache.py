# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
import time

from src.utils.logger import get_logger

log = get_logger("favicon_cache")

# Cache TTL: Considered stale after 30 days, will be re-extracted during next sync
_TTL_DAYS = 30


@dataclass
class FaviconRecord:
    """A single normalized favicon cache record."""

    domain: str
    data: bytes  # Binary data for PNG/ICO/WebP/GIF, or UTF-8 bytes for SVG
    data_type: str  # 'png' | 'ico' | 'svg' | 'webp' | 'jpeg' | 'gif'
    width: int  # 0 for SVG (vector, no fixed size)
    updated_at: int  # Unix timestamp (seconds)


class FaviconCache:
    """
    Manages the independent SQLite database for favicons (favicons.db).

    Responsibilities:
    - Exclusively handles persistence and retrieval of favicon data; no rendering.
    - Completely independent of history.db; never participates in WebDAV sync.
    - Uses the domain (registered domain) as the primary key to cache the best available icon.

    Performance Optimizations:
    - Uses a persistent connection (check_same_thread=False) to avoid open/close overhead
      on every get/get_many call, significantly reducing UI thread latency during rendering.
    - Write operations (upsert_many, prune_stale) explicitly commit;
      read operations (get, get_many) do not trigger unnecessary commits.
    - All operations are serialized via RLock to ensure safety between main thread reads
      and background thread writes.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS favicon_cache (
            domain      TEXT    PRIMARY KEY,
            data        BLOB    NOT NULL,
            data_type   TEXT    NOT NULL DEFAULT 'png',
            width       INTEGER NOT NULL DEFAULT 0,
            updated_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_favicon_updated
            ON favicon_cache(updated_at);
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._pconn: sqlite3.Connection | None = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Persistent Connection Management ────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        """
        Returns a persistent connection, creating it if necessary.
        Caller must hold self._lock.
        """
        if self._pconn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.commit()
            self._pconn = conn
        return self._pconn

    def _reset_conn(self) -> None:
        """Resets the connection after an error. _ensure_conn will reopen it next time."""
        if self._pconn is not None:
            try:
                self._pconn.close()
            except Exception:
                pass
            self._pconn = None

    @contextmanager
    def _conn(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """
        Thread-safe connection context manager.
        write=True: yields and commits, rolls back on error.
        write=False (read-only): avoids transaction overhead, reducing lock contention.
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
                # Connection state might be corrupted, reset for next recreation
                self._reset_conn()
                raise

    def close(self) -> None:
        """Explicitly closes the persistent connection (called on app exit)."""
        with self._lock:
            self._reset_conn()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        with self._conn(write=True) as conn:
            conn.executescript(self._SCHEMA)
        log.info("FaviconCache initialized: %s", self.db_path)

    # ── Write ────────────────────────────────────────────────

    def upsert_many(self, records: list[FaviconRecord]) -> int:
        """
        Batch inserts/updates icon records. On conflict (same domain), overwrites based on priority:
        - SVG is always preferred (lossless scaling).
        - For bitmaps, larger sizes overwrite smaller sizes.
        - If sizes are equal, the newer updated_at timestamp wins.

        Note: Deduplication within the same batch is handled in Python by _select_best_per_domain().
        The SQL conditions here prevent existing high-quality cache from being downgraded.
        """
        if not records:
            return 0

        sql = """
            INSERT INTO favicon_cache (domain, data, data_type, width, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                data       = excluded.data,
                data_type  = excluded.data_type,
                width      = excluded.width,
                updated_at = excluded.updated_at
            WHERE
                -- Upgrade if new data is SVG and old data is not
                (excluded.data_type = 'svg' AND favicon_cache.data_type != 'svg')
                -- Upgrade if both are bitmaps but new has higher resolution
                OR (excluded.data_type != 'svg' AND favicon_cache.data_type != 'svg'
                    AND excluded.width > favicon_cache.width)
                -- Same size but newer data (higher freshness)
                OR (excluded.width = favicon_cache.width
                    AND excluded.updated_at > favicon_cache.updated_at)
        """
        with self._conn(write=True) as conn:
            conn.executemany(
                sql,
                [(r.domain, r.data, r.data_type, r.width, r.updated_at) for r in records],
            )
        log.info("FaviconCache: upserted %d domain icons", len(records))
        return len(records)

    # ── Read ─────────────────────────────────────────────────

    def get(self, domain: str) -> FaviconRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT domain, data, data_type, width, updated_at FROM favicon_cache WHERE domain = ?",
                (domain,),
            ).fetchone()
        if row is None:
            return None
        return FaviconRecord(
            domain=row["domain"],
            data=bytes(row["data"]),
            data_type=row["data_type"],
            width=row["width"],
            updated_at=row["updated_at"],
        )

    def get_many(self, domains: set[str]) -> dict[str, FaviconRecord]:
        """Batch query, returns a {domain: FaviconRecord} dict (only for cache hits)."""
        if not domains:
            return {}
        placeholders = ",".join("?" * len(domains))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT domain, data, data_type, width, updated_at "
                f"FROM favicon_cache WHERE domain IN ({placeholders})",
                tuple(domains),
            ).fetchall()
        return {
            row["domain"]: FaviconRecord(
                domain=row["domain"],
                data=bytes(row["data"]),
                data_type=row["data_type"],
                width=row["width"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }

    def get_stale_domains(self) -> list[str]:
        """Returns a list of domains that exceed the TTL and need re-extraction."""
        threshold = int(time.time()) - _TTL_DAYS * 86_400
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT domain FROM favicon_cache WHERE updated_at < ?",
                (threshold,),
            ).fetchall()
        return [r["domain"] for r in rows]

    def prune_stale(self) -> int:
        """Deletes cache entries exceeding the TTL and returns the number of deleted records."""
        threshold = int(time.time()) - _TTL_DAYS * 86_400
        with self._conn(write=True) as conn:
            cursor = conn.execute(
                "DELETE FROM favicon_cache WHERE updated_at < ?",
                (threshold,),
            )
            count = cursor.rowcount
        if count:
            log.info("FaviconCache: pruned %d stale entries", count)
        return count

    def get_total_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM favicon_cache").fetchone()
            return row[0] if row else 0
