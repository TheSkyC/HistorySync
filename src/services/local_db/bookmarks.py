# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import time

from src.models.history_record import AnnotationRecord, BookmarkRecord
from src.utils.logger import get_logger
from src.utils.url_utils import extract_host as _extract_url_host

log = get_logger("local_db")


# ── Bookmark page filter / cursor ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BookmarkPageFilter:
    """All filterable inputs that map to SQL WHERE conditions in get_bookmarks_page.

    The struct is frozen so it can be cheaply compared in the model's filter
    diff and used as a cache key for sizeHint calculations in the delegate.
    """

    tag: str = ""
    keyword: str = ""
    title_only: bool = False
    url_only: bool = False
    has_annotation: bool = False
    excludes: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    after: date | None = None
    before: date | None = None
    hidden_mode: bool = False


@dataclass(frozen=True, slots=True)
class BookmarkCursor:
    """Keyset-pagination cursor over (bookmarked_at DESC, id DESC)."""

    bookmarked_at: int
    id: int


# ── _BookmarksMixin ──────────────────────────────────────────────────────────


# Shared visibility-filter SQL fragments used by every bookmark read path.
# Expressed as plain string constants (not f-strings with parameters) so the
# planner can reuse the same prepared-statement cache entries across calls.
#
# NOTE: ``b.host`` is the materialised hostname column populated by every
# bookmark write path and backfilled on schema migration.  Using it instead
# of ``_extract_host(b.url)`` removes O(B × D) Python UDF callbacks per
# query; the deterministic flag on the UDF keeps even legacy callers cheap.
_VIS_HIDDEN_FALSE_SQL = (
    "NOT EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = b.url)"
    " AND NOT EXISTS ("
    "  SELECT 1 FROM hidden_domains hd"
    "  WHERE (hd.subdomain_only = 1 AND b.host = hd.domain)"
    "     OR (hd.subdomain_only = 0 AND"
    "         (b.host = hd.domain OR b.host LIKE '%.' || hd.domain)))"
)
_VIS_HIDDEN_TRUE_SQL = (
    "(EXISTS (SELECT 1 FROM hidden_records hr WHERE hr.url = b.url)"
    " OR EXISTS ("
    "  SELECT 1 FROM hidden_domains hd"
    "  WHERE (hd.subdomain_only = 1 AND b.host = hd.domain)"
    "     OR (hd.subdomain_only = 0 AND"
    "         (b.host = hd.domain OR b.host LIKE '%.' || hd.domain))))"
)


def _visibility_sql(hidden_mode: bool) -> str:
    return _VIS_HIDDEN_TRUE_SQL if hidden_mode else _VIS_HIDDEN_FALSE_SQL


def _escape_like(value: str) -> str:
    """Escape LIKE wildcard characters; pair with ``ESCAPE '\\'`` in SQL."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _bookmark_filter_parts(
    page_filter: BookmarkPageFilter,
    cursor: BookmarkCursor | None = None,
    url: str | None = None,
) -> tuple[str, list[object]]:
    """Build the shared bookmark WHERE clause for page/count/single-row reads."""
    visibility = _visibility_sql(page_filter.hidden_mode)
    clauses: list[str] = [visibility]
    params: list[object] = []

    if url is not None:
        clauses.append("b.url = ?")
        params.append(url)

    if page_filter.tag:
        clauses.append("EXISTS (SELECT 1 FROM bookmark_tags bt WHERE bt.bookmark_id = b.id AND bt.tag = ?)")
        params.append(page_filter.tag)

    if page_filter.has_annotation:
        clauses.append("EXISTS (SELECT 1 FROM annotations a WHERE a.url = b.url AND a.note != '')")

    if page_filter.after is not None:
        from datetime import datetime as _dt

        after_ts = int(_dt(page_filter.after.year, page_filter.after.month, page_filter.after.day).timestamp())
        clauses.append("b.bookmarked_at >= ?")
        params.append(after_ts)
    if page_filter.before is not None:
        from datetime import datetime as _dt

        before_ts = int(
            _dt(
                page_filter.before.year,
                page_filter.before.month,
                page_filter.before.day,
                23,
                59,
                59,
            ).timestamp()
        )
        clauses.append("b.bookmarked_at <= ?")
        params.append(before_ts)

    if page_filter.domains:
        domain_clauses = []
        for dom in page_filter.domains:
            if not dom:
                continue
            domain_clauses.append("b.host LIKE ? ESCAPE '\\'")
            params.append("%" + _escape_like(dom.lower()) + "%")
        if domain_clauses:
            clauses.append("(" + " OR ".join(domain_clauses) + ")")

    if page_filter.keyword:
        kw_pattern = "%" + _escape_like(page_filter.keyword.lower()) + "%"
        if page_filter.title_only:
            clauses.append("LOWER(b.title) LIKE ? ESCAPE '\\'")
            params.append(kw_pattern)
        elif page_filter.url_only:
            clauses.append("LOWER(b.url) LIKE ? ESCAPE '\\'")
            params.append(kw_pattern)
        else:
            clauses.append(
                "(LOWER(b.title) LIKE ? ESCAPE '\\'"
                " OR LOWER(b.url) LIKE ? ESCAPE '\\'"
                " OR EXISTS (SELECT 1 FROM bookmark_tags bt"
                "            WHERE bt.bookmark_id = b.id AND LOWER(bt.tag) LIKE ? ESCAPE '\\'))"
            )
            params.extend([kw_pattern, kw_pattern, kw_pattern])

    for ex in page_filter.excludes:
        if not ex:
            continue
        ex_pat = "%" + _escape_like(ex.lower()) + "%"
        clauses.append("LOWER(b.title || ' ' || b.url) NOT LIKE ? ESCAPE '\\'")
        params.append(ex_pat)

    if cursor is not None:
        clauses.append("(b.bookmarked_at < ? OR (b.bookmarked_at = ? AND b.id < ?))")
        params.extend([cursor.bookmarked_at, cursor.bookmarked_at, cursor.id])

    return " AND ".join(clauses), params


def _bookmark_record_from_row(row) -> BookmarkRecord:
    return BookmarkRecord(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        tags=row["tags"].split(",") if row["tags"] else [],
        bookmarked_at=row["bookmarked_at"],
        history_id=row["history_id"],
    )


class _BookmarksMixin:
    """Bookmark and annotation CRUD."""

    # ── Bookmark CRUD ─────────────────────────────────────────

    def add_bookmark(self, url: str, title: str, tags: list[str], history_id: int | None = None) -> BookmarkRecord:
        """Insert or replace a bookmark. Returns the stored record."""
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        host = _extract_url_host(url) or ""
        now = int(time.time())
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """INSERT INTO bookmarks(url, title, tags, bookmarked_at, history_id, host)
                   VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       title=excluded.title,
                       tags=excluded.tags,
                       bookmarked_at=excluded.bookmarked_at,
                       history_id=excluded.history_id,
                       host=excluded.host""",
                (url, title, tags_str, now, history_id, host),
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
                "INSERT INTO deleted_bookmarks(url) VALUES(?) "
                "ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
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

        Retained for backwards compatibility with older callers and tests.
        New UI code should use :meth:`get_bookmarks_page` for keyset-paginated,
        SQL-side-filtered loading.

        Visibility semantics match :meth:`get_bookmarks_page`: when *hidden_mode*
        is False bookmarks pointing to hidden URLs/domains are excluded; when
        True only those bookmarks are returned.
        """
        visibility = _visibility_sql(hidden_mode)
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            if tag:
                rows = conn.execute(
                    f"""SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt2.tag, ',') AS tags
                       FROM bookmarks b
                       JOIN bookmark_tags bt  ON b.id = bt.bookmark_id  AND bt.tag = ?
                       LEFT JOIN bookmark_tags bt2 ON b.id = bt2.bookmark_id
                       WHERE {visibility}
                       GROUP BY b.id
                       ORDER BY b.bookmarked_at DESC, b.id DESC""",
                    (tag,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                              GROUP_CONCAT(bt.tag, ',') AS tags
                       FROM bookmarks b
                       LEFT JOIN bookmark_tags bt ON b.id = bt.bookmark_id
                       WHERE {visibility}
                       GROUP BY b.id
                       ORDER BY b.bookmarked_at DESC, b.id DESC"""
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

    def get_bookmarks_page(
        self,
        page_filter: BookmarkPageFilter,
        cursor: BookmarkCursor | None = None,
        limit: int = 100,
    ) -> list[BookmarkRecord]:
        """Return one keyset-paginated page of bookmarks matching *page_filter*.

        Ordered by ``(bookmarked_at DESC, id DESC)``.  When *cursor* is None
        the first page is returned; otherwise rows strictly after *cursor*
        in that ordering are returned.

        All filtering is performed in SQL — there is no Python-side post
        processing.  The query uses the materialised ``bookmarks.host`` column
        for visibility checks (no per-row UDF), and joins ``bookmark_tags``
        only when a tag filter is active so the tag-collection sub-query
        can be amortised over the actually-returned page.

        Tag aggregation is done with a correlated sub-query rather than a
        ``GROUP BY`` join so that ``LIMIT`` semantics remain correct
        regardless of how many tags a bookmark has.
        """
        if limit <= 0:
            return []

        where_sql, params = _bookmark_filter_parts(page_filter, cursor=cursor)
        sql = f"""
            SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                   (SELECT GROUP_CONCAT(bt.tag, ',')
                      FROM bookmark_tags bt
                     WHERE bt.bookmark_id = b.id) AS tags
              FROM bookmarks b
             WHERE {where_sql}
             ORDER BY b.bookmarked_at DESC, b.id DESC
             LIMIT ?
        """
        params.append(int(limit))

        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(sql, params).fetchall()
        return [_bookmark_record_from_row(r) for r in rows]

    def get_bookmark_for_filter(self, url: str, page_filter: BookmarkPageFilter) -> BookmarkRecord | None:
        """Return the bookmark if it currently matches *page_filter*, else None."""
        where_sql, params = _bookmark_filter_parts(page_filter, url=url)
        sql = f"""
            SELECT b.id, b.url, b.title, b.bookmarked_at, b.history_id,
                   (SELECT GROUP_CONCAT(bt.tag, ',')
                      FROM bookmark_tags bt
                     WHERE bt.bookmark_id = b.id) AS tags
              FROM bookmarks b
             WHERE {where_sql}
             LIMIT 1
        """
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            row = conn.execute(sql, params).fetchone()
        return _bookmark_record_from_row(row) if row is not None else None

    def count_bookmarks(self, page_filter: BookmarkPageFilter) -> int:
        """Return total rows matching *page_filter* (used for the count label).

        Cheaper than fetching all rows: no GROUP_CONCAT, no LIMIT, just COUNT(*).
        """
        where_sql, params = _bookmark_filter_parts(page_filter)
        sql = f"SELECT COUNT(*) FROM bookmarks b WHERE {where_sql}"

        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0)

    def get_all_bookmark_tags(self) -> list[str]:
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT DISTINCT tag FROM bookmark_tags ORDER BY tag").fetchall()
        return [r[0] for r in rows]

    def update_bookmark_tags(self, url: str, tags: list[str]) -> bool:
        clean_tags = [t.strip() for t in tags if t.strip()]
        tags_str = ",".join(clean_tags)  # kept for legacy column only
        host = _extract_url_host(url) or ""
        with self._conn() as conn:  # type: ignore[attr-defined]
            # Refresh the materialised host column too, in case this URL was
            # written by an older app version before the host column existed.
            cur = conn.execute("UPDATE bookmarks SET tags=?, host=? WHERE url=?", (tags_str, host, url))
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
                "INSERT INTO deleted_annotations(url) VALUES(?) "
                "ON CONFLICT(url) DO UPDATE SET deleted_at = strftime('%s','now')",
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

    def get_annotations_for_urls(self, urls: list[str]) -> dict[str, AnnotationRecord]:
        """Return ``{url: AnnotationRecord}`` for the subset of *urls* that have notes.

        Used by the bookmark page to fetch only the annotations relevant to the
        currently loaded page rather than the full annotation table.  Splits
        the URL list into chunks of 800 (well under the SQLite default
        ``SQLITE_MAX_VARIABLE_NUMBER`` of 999) so very large pages still work.
        """
        if not urls:
            return {}
        result: dict[str, AnnotationRecord] = {}
        chunk_size = 800
        with self._conn(write=False, strong_read=True) as conn:  # type: ignore[attr-defined]
            for start in range(0, len(urls), chunk_size):
                chunk = urls[start : start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""SELECT id, url, note, created_at, updated_at, history_id
                       FROM annotations
                      WHERE url IN ({placeholders}) AND note != ''""",
                    chunk,
                ).fetchall()
                for r in rows:
                    result[r["url"]] = AnnotationRecord(
                        id=r["id"],
                        url=r["url"],
                        note=r["note"],
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                        history_id=r["history_id"],
                    )
        return result


__all__ = [
    "BookmarkCursor",
    "BookmarkPageFilter",
    "_BookmarksMixin",
]
