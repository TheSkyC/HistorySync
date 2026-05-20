# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Merge a foreign HistorySync database into the local one.

Two entry points:

* :meth:`_MergeMixin.merge_from_db` streams history rows in batches and
  optionally chains :meth:`merge_user_data_from_db` afterwards.
* :meth:`_MergeMixin.merge_user_data_from_db` brings over bookmarks, tags,
  annotations, hidden_records / hidden_domains, and tombstones, re-resolving
  every foreign integer ID against the local tables by URL.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3

from src.models.history_record import HistoryRecord
from src.utils.constants import DB_BATCH_SIZE
from src.utils.i18n_core import _
from src.utils.logger import get_logger

log = get_logger("local_db")


class _MergeMixin:
    """WebDAV restore / cross-device merge support."""

    def merge_from_db(
        self,
        src_path: Path,
        progress_cb: Callable[[str], None] | None = None,
        include_user_data: bool = True,
    ) -> int:
        """Merge history records from *src_path* into this database.

        Rows are streamed from the source in batches of ``DB_BATCH_SIZE`` to
        avoid loading the entire backup into memory at once.

        When *include_user_data* is ``True`` (the default), bookmarks,
        annotations, hidden_records, and tombstones are also merged by calling
        :meth:`merge_user_data_from_db` automatically.  Pass ``False`` only
        when you need to merge history alone (e.g. plain import without user
        data).
        """

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)
            log.info("merge_from_db: %s", msg)

        _cb(_("Opening backup database for merge..."))
        src_conn = sqlite3.connect(str(src_path), timeout=30)
        src_conn.row_factory = sqlite3.Row
        try:
            integrity = src_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"Backup database failed integrity check: {integrity}")
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
                local_id = self.upsert_device(  # type: ignore[attr-defined]
                    uuid=dev["uuid"],
                    name=dev["name"],
                    plat=dev["platform"],
                    app_version=dev["app_version"],
                )
                remote_to_local_id[dev["id"]] = local_id

            total_src: int = src_conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            _cb(_("Merging {n} records from backup...").format(n=total_src))

            _remote_deleted_urls = {r[0] for r in remote_deleted}

            # Read local tombstones before streaming so we can skip already-deleted
            # URLs during batch construction, avoiding a write-then-delete FTS churn.
            with self._conn(write=False) as _ro:  # type: ignore[attr-defined]
                try:
                    _local_deleted_urls: set[str] = {
                        r[0] for r in _ro.execute("SELECT url FROM deleted_records").fetchall()
                    }
                except sqlite3.OperationalError:
                    _local_deleted_urls = set()

            _skip_urls = _remote_deleted_urls | _local_deleted_urls

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
                    if r["url"] not in _skip_urls
                ]
                inserted += self.upsert_records(records)  # type: ignore[attr-defined]

        finally:
            src_conn.close()

        # Absorb remote tombstones only when merging full user data.
        # Persisting tombstones during a plain import (include_user_data=False)
        # would silently block those URLs from being re-imported in the future.
        if include_user_data and remote_deleted:
            with self._conn() as conn:  # type: ignore[attr-defined]
                conn.executemany(
                    "INSERT INTO deleted_records(url, deleted_at) VALUES(?, ?) ON CONFLICT(url) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                    ((r[0], r[1]) for r in remote_deleted),
                )

        _cb(
            _("Merge complete: {inserted} new records added (of {total} in backup).").format(
                inserted=inserted, total=total_src
            )
        )
        if include_user_data:
            self.merge_user_data_from_db(src_path, progress_cb=progress_cb)
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
            remote_hidden_domains = _safe_fetch("SELECT domain, subdomain_only, hidden_at FROM hidden_domains")
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

        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]

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

            # 3b. Merge hidden_domains — IGNORE keeps the local entry if the same
            #     domain is already present (local intent wins on conflict).
            if remote_hidden_domains:
                conn.executemany(
                    "INSERT OR IGNORE INTO hidden_domains(domain, subdomain_only, hidden_at) VALUES(?, ?, ?)",
                    ((r["domain"], r["subdomain_only"], r["hidden_at"]) for r in remote_hidden_domains),
                )

            # 4. Merge bookmarks (skip tombstoned urls, keep newer bookmarked_at)
            deleted_bm_urls: set[str] = {r[0] for r in conn.execute("SELECT url FROM deleted_bookmarks").fetchall()}
            # Track urls where remote won (bookmarked_at was newer) so we can replace tags atomically
            tag_replace_urls: set[str] = set()

            # Pre-fetch history_id and existing bookmarked_at for all remote bookmark URLs in bulk
            remote_bm_urls = [bm["url"] for bm in remote_bookmarks if bm["url"] not in deleted_bm_urls]
            history_id_map: dict[str, int] = {}
            existing_bm_map: dict[str, int] = {}
            for _i in range(0, max(len(remote_bm_urls), 1), 900):
                _chunk = remote_bm_urls[_i : _i + 900]
                if not _chunk:
                    break
                _ph = ",".join("?" * len(_chunk))
                history_id_map.update(
                    (r["url"], r["id"])
                    for r in conn.execute(
                        f"SELECT url, id FROM history WHERE url IN ({_ph})",
                        _chunk,
                    ).fetchall()
                )
                existing_bm_map.update(
                    (r["url"], r["bookmarked_at"])
                    for r in conn.execute(
                        f"SELECT url, bookmarked_at FROM bookmarks WHERE url IN ({_ph})",
                        _chunk,
                    ).fetchall()
                )

            for bm in remote_bookmarks:
                url = bm["url"]
                if url in deleted_bm_urls:
                    continue
                history_id = history_id_map.get(url)
                remote_ts = bm["bookmarked_at"]
                existing_ts = existing_bm_map.get(url)
                if existing_ts is None or remote_ts > existing_ts:
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

            # Pre-fetch bookmark ids for all tag_replace_urls in bulk
            bm_id_map: dict[str, int] = {}
            if tag_replace_urls:
                _tag_url_list = list(tag_replace_urls)
                for _i in range(0, len(_tag_url_list), 900):
                    _chunk = _tag_url_list[_i : _i + 900]
                    _ph2 = ",".join("?" * len(_chunk))
                    bm_id_map.update(
                        (r["url"], r["id"])
                        for r in conn.execute(
                            f"SELECT url, id FROM bookmarks WHERE url IN ({_ph2})",
                            _chunk,
                        ).fetchall()
                    )

            for url in tag_replace_urls:
                bm_id = bm_id_map.get(url)
                if not bm_id:
                    continue
                # Atomically replace: delete existing tags, insert remote tags
                conn.execute("DELETE FROM bookmark_tags WHERE bookmark_id=?", (bm_id,))
                for tag in remote_tags_by_url.get(url, []):
                    conn.execute(
                        "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?)",
                        (bm_id, tag),
                    )

            # 6. Merge annotations (skip tombstoned urls, keep newer updated_at)
            deleted_ann_urls: set[str] = {r[0] for r in conn.execute("SELECT url FROM deleted_annotations").fetchall()}

            # Pre-fetch history ids for all annotation urls in bulk
            ann_urls = [ann["url"] for ann in remote_annotations if ann["url"] not in deleted_ann_urls]
            ann_history_id_map: dict[str, int] = {}
            for _i in range(0, max(len(ann_urls), 1), 900):
                _chunk = ann_urls[_i : _i + 900]
                if not _chunk:
                    break
                _ph3 = ",".join("?" * len(_chunk))
                ann_history_id_map.update(
                    (r["url"], r["id"])
                    for r in conn.execute(
                        f"SELECT url, id FROM history WHERE url IN ({_ph3})",
                        _chunk,
                    ).fetchall()
                )

            for ann in remote_annotations:
                url = ann["url"]
                if url in deleted_ann_urls:
                    continue
                history_id = ann_history_id_map.get(url)
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
