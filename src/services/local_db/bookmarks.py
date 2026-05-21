# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import time

from src.models.history_record import AnnotationRecord, BookmarkRecord
from src.utils.logger import get_logger

log = get_logger("local_db")


class _BookmarksMixin:
    """Bookmark and annotation CRUD."""

    # ── Bookmark CRUD ─────────────────────────────────────────

    def add_bookmark(self, url: str, title: str, tags: list[str], history_id: int | None = None) -> BookmarkRecord:
        """Insert or replace a bookmark. Returns the stored record."""
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        now = int(time.time())
        with self._conn() as conn:  # type: ignore[attr-defined]
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
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO deleted_bookmarks(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                (url,),
            )
            cur = conn.execute("DELETE FROM bookmarks WHERE url=?", (url,))
            return cur.rowcount > 0

    def get_bookmark(self, url: str) -> BookmarkRecord | None:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
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
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT 1 FROM bookmarks WHERE url=?", (url,)).fetchone()
        return row is not None

    def get_bookmarked_urls(self) -> set[str]:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT DISTINCT url FROM bookmarks").fetchall()
        return {r[0] for r in rows}

    def get_all_bookmarks(self, tag: str = "", hidden_mode: bool = False) -> list[BookmarkRecord]:
        """Return bookmarks, optionally filtered by tag.

        When *hidden_mode* is False (the default / normal view) bookmarks whose
        URL appears in ``hidden_records`` **or** whose domain appears in
        ``hidden_domains`` are excluded — they remain invisible just like the
        corresponding history records.

        When *hidden_mode* is True only bookmarks that point to a hidden URL or
        hidden domain are returned, mirroring the history page's hidden-only
        view.
        """
        # Build the visibility WHERE clause that mirrors history-page filtering.
        # The `domains` table stores hosts for history rows only — it has no
        # `url` column and bookmarks may point to URLs never in history.  We
        # therefore resolve the host on-the-fly with _extract_host(b.url) and
        # compare directly against hidden_domains.domain, bypassing the
        # `domains` table entirely.
        if hidden_mode:
            # Show ONLY bookmarks pointing to hidden URLs or hidden domains.
            visibility_filter = (
                "(EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = b.url)"
                " OR EXISTS ("
                "  SELECT 1 FROM hidden_domains hd"
                "  WHERE (hd.subdomain_only = 1 AND _extract_host(b.url) = hd.domain)"
                "     OR (hd.subdomain_only = 0 AND"
                "         (_extract_host(b.url) = hd.domain"
                "          OR _extract_host(b.url) LIKE '%.' || hd.domain))))"
            )
        else:
            # Normal mode: exclude bookmarks whose URL or domain is hidden.
            visibility_filter = (
                "NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = b.url)"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM hidden_domains hd"
                "  WHERE (hd.subdomain_only = 1 AND _extract_host(b.url) = hd.domain)"
                "     OR (hd.subdomain_only = 0 AND"
                "         (_extract_host(b.url) = hd.domain"
                "          OR _extract_host(b.url) LIKE '%.' || hd.domain)))"
            )

        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            if tag:
                # Filter by tag via JOIN, then LEFT JOIN again to collect all tags per bookmark.
                rows = conn.execute(
                    f"""SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt2.tag, ',') AS tags
                       FROM bookmarks b
                       JOIN bookmark_tags bt  ON b.id = bt.bookmark_id  AND bt.tag = ?
                       LEFT JOIN bookmark_tags bt2 ON b.id = bt2.bookmark_id
                       WHERE {visibility_filter}
                       GROUP BY b.id
                       ORDER BY b.bookmarked_at DESC""",
                    (tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt.tag, ',') AS tags
                       FROM bookmarks b
                       LEFT JOIN bookmark_tags bt ON b.id = bt.bookmark_id
                       WHERE {visibility_filter}
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
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT DISTINCT tag FROM bookmark_tags ORDER BY tag").fetchall()
        return [r[0] for r in rows]

    def update_bookmark_tags(self, url: str, tags: list[str]) -> bool:
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        with self._conn() as conn:  # type: ignore[attr-defined]
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
        with self._conn() as conn:  # type: ignore[attr-defined]
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
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO deleted_annotations(url) VALUES(?) ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
                (url,),
            )
            cur = conn.execute("DELETE FROM annotations WHERE url=?", (url,))
            return cur.rowcount > 0

    def get_annotation(self, url: str) -> AnnotationRecord | None:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
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
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT url FROM annotations WHERE note != ''").fetchall()
        return {r[0] for r in rows}

    def get_all_annotations(self) -> list[AnnotationRecord]:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
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
