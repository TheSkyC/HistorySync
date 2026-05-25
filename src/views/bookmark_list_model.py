# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
QAbstractListModel-based bookmark model with keyset-paginated lazy loading.

This module replaces the legacy "load all bookmarks into memory then build
N QFrame widgets" pattern with a true Model/View architecture:

    [SQL keyset pagination] -> [BookmarkListModel] -> [QListView + delegate]
                                                         ^
                                                         only ~10 rows are
                                                         ever painted at once

Design highlights
-----------------

1. **Lazy loading** -- `canFetchMore` / `fetchMore` only request the next page
   from SQL when the view scrolls past the loaded range. Initial page load is
   triggered by `reset_filter()`.

2. **Background SQL** -- `_BookmarkPageWorker` and `_BookmarkCountWorker`
   subclass `QThread` directly (mirroring the project's existing pattern) so
   the C++ object lives on the main thread, eliminating a class of refcount
   races that the previous code had to defend against.

3. **Generation guard** -- every filter change bumps `_generation`. In-flight
   worker results that arrive after a bump are silently discarded, so rapid
   tag/keyword changes never produce ordering glitches.

4. **Optimistic mutations** -- `remove_url`, `update_tags`, `update_note`,
   `add_or_update` mutate the in-memory list and emit the appropriate
   `dataChanged` / `beginRemoveRows` signals so the view re-paints just the
   affected rows without a full reload.

5. **Per-page annotation prefetch** -- `get_annotations_for_urls` is called
   for every loaded page so each row has its annotation ready without an
   extra round-trip when the delegate paints.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QThread, Signal

from src.models.history_record import AnnotationRecord, BookmarkRecord
from src.services.local_db import LocalDatabase
from src.services.local_db.bookmarks import BookmarkCursor, BookmarkPageFilter
from src.utils.logger import get_logger

log = get_logger("view.bookmarks.model")

# Page size for keyset-paginated SQL fetches.  Big enough that scrolling rarely
# blocks for a fetch, small enough that the first fetch is cheap.
_PAGE_SIZE = 100


# ── Background workers ───────────────────────────────────────────────────────


class _BookmarkPageWorker(QThread):
    """Loads one keyset page of bookmarks plus their annotations."""

    page_ready = Signal(list, dict, int)  # (records, {url: AnnotationRecord}, generation)

    def __init__(
        self,
        db: LocalDatabase,
        page_filter: BookmarkPageFilter,
        cursor: BookmarkCursor | None,
        limit: int,
        generation: int,
        parent=None,
    ):
        super().__init__(parent)
        self._db = db
        self._filter = page_filter
        self._cursor = cursor
        self._limit = limit
        self._generation = generation

    def run(self):
        try:
            records = self._db.get_bookmarks_page(self._filter, self._cursor, self._limit)
            ann_map: dict[str, AnnotationRecord] = (
                self._db.get_annotations_for_urls([r.url for r in records]) if records else {}
            )
            self.page_ready.emit(records, ann_map, self._generation)
        except Exception:
            log.exception("_BookmarkPageWorker.run failed")
            self.page_ready.emit([], {}, self._generation)


class _BookmarkCountWorker(QThread):
    """Computes total matching count for the current filter."""

    count_ready = Signal(int, int)  # (count, generation)

    def __init__(self, db: LocalDatabase, page_filter: BookmarkPageFilter, generation: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._filter = page_filter
        self._generation = generation

    def run(self):
        try:
            n = self._db.count_bookmarks(self._filter)
            self.count_ready.emit(n, self._generation)
        except Exception:
            log.exception("_BookmarkCountWorker.run failed")
            self.count_ready.emit(0, self._generation)


class _TagListWorker(QThread):
    """Loads the distinct tag list for the sidebar."""

    tags_ready = Signal(list, int)  # (tags, generation)

    def __init__(self, db: LocalDatabase, generation: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._generation = generation

    def run(self):
        try:
            tags = self._db.get_all_bookmark_tags()
            self.tags_ready.emit(tags, self._generation)
        except Exception:
            log.exception("_TagListWorker.run failed")
            self.tags_ready.emit([], self._generation)


# ── Model ────────────────────────────────────────────────────────────────────


class BookmarkListModel(QAbstractListModel):
    """List model exposing :class:`BookmarkRecord` rows for ``QListView``.

    Custom roles
    ------------
    - :data:`BookmarkRole`   : returns the underlying ``BookmarkRecord``.
    - :data:`AnnotationRole` : returns the matching ``AnnotationRecord`` or None.

    Signals
    -------
    - ``loading_changed(bool)``     : True when a page or count worker is in flight.
    - ``total_count_changed(int)``  : new total row count for the current filter.
    - ``tags_changed(list[str])``   : tag sidebar refreshed (after mutations).
    """

    # Custom item-data roles.
    BookmarkRole = Qt.UserRole + 1
    AnnotationRole = Qt.UserRole + 2

    loading_changed = Signal(bool)
    total_count_changed = Signal(int)
    tags_changed = Signal(list)

    def __init__(self, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._db = db

        self._items: list[BookmarkRecord] = []
        self._annotations: dict[str, AnnotationRecord] = {}

        self._filter = BookmarkPageFilter()
        self._cursor: BookmarkCursor | None = None
        self._has_more = True
        self._is_loading = False
        self._total_count = 0
        self._tags: list[str] = []

        # Generation counter — bumped on every filter change so stale worker
        # callbacks can be detected and ignored.
        self._generation = 0

        # In-flight worker handles.  Kept as Python attributes so the wrapper
        # is not GC'd while ``run()`` is still executing on the QThread.
        self._page_worker: _BookmarkPageWorker | None = None
        self._count_worker: _BookmarkCountWorker | None = None
        self._tag_worker: _TagListWorker | None = None

    # ── Qt model API ──────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        row = index.row()
        if not (0 <= row < len(self._items)):
            return None
        bm = self._items[row]
        if role == self.BookmarkRole:
            return bm
        if role == self.AnnotationRole:
            return self._annotations.get(bm.url)
        if role == Qt.DisplayRole:
            return bm.title or bm.url
        if role == Qt.ToolTipRole:
            return bm.url
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:
        if parent.isValid():
            return False
        return self._has_more and not self._is_loading

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:
        if parent.isValid() or not self.canFetchMore():
            return
        self._start_page_load()

    # ── Public API ────────────────────────────────────────────

    @property
    def db(self) -> LocalDatabase:
        return self._db

    @property
    def current_filter(self) -> BookmarkPageFilter:
        return self._filter

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def has_more(self) -> bool:
        return self._has_more

    @property
    def loaded_count(self) -> int:
        return len(self._items)

    @property
    def tags(self) -> list[str]:
        return list(self._tags)

    def get_annotation(self, url: str) -> AnnotationRecord | None:
        return self._annotations.get(url)

    def get_bookmark(self, row: int) -> BookmarkRecord | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def find_row_for_url(self, url: str) -> int:
        """Linear scan for the row holding *url*; returns -1 if not loaded."""
        for i, bm in enumerate(self._items):
            if bm.url == url:
                return i
        return -1

    def reset_filter(self, page_filter: BookmarkPageFilter) -> None:
        """Switch to a new filter; clear all loaded rows and restart pagination.

        Always issues fresh page+count workers so the view becomes consistent
        with *page_filter* even if a previous worker is still in flight (its
        result will be discarded by the generation guard).
        """
        self.beginResetModel()
        self._items.clear()
        self._annotations.clear()
        self._cursor = None
        self._has_more = True
        # Discard any in-flight loading state from the previous filter so
        # _start_page_load() doesn't bail out with "already loading".
        self._is_loading = False
        self._filter = page_filter
        self._generation += 1
        self.endResetModel()

        self.loading_changed.emit(True)
        self._start_page_load()
        self._start_count_load()

    def refresh(self) -> None:
        """Reload from DB without changing the active filter."""
        self.reset_filter(self._filter)

    def refresh_tags(self) -> None:
        """Reload the distinct-tag list for the sidebar (background)."""
        gen = self._generation
        # Replace any in-flight worker — slightly wasteful but prevents stacking.
        worker = _TagListWorker(self._db, gen, parent=self)
        worker.tags_ready.connect(self._on_tags_ready)
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.finished.connect(lambda w=worker: self._clear_tag_worker_ref(w))
        self._tag_worker = worker
        worker.start()

    # ── Optimistic mutations ──────────────────────────────────

    def remove_url(self, url: str) -> bool:
        """Remove the row matching *url* (no-op if not currently loaded)."""
        row = self.find_row_for_url(url)
        if row < 0:
            self._adjust_total(-1)  # still adjust total — the row exists in DB
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()
        self._annotations.pop(url, None)
        self._adjust_total(-1)
        return True

    def update_tags(self, url: str, tags: list[str]) -> bool:
        """Replace tags on the loaded row matching *url*."""
        row = self.find_row_for_url(url)
        if row < 0:
            return False
        self._items[row].tags = list(tags)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.BookmarkRole])
        return True

    def update_note(self, url: str, ann: AnnotationRecord | None) -> bool:
        """Update / clear the annotation for the loaded row matching *url*."""
        if ann is not None and ann.note:
            self._annotations[url] = ann
        else:
            self._annotations.pop(url, None)
        row = self.find_row_for_url(url)
        if row < 0:
            return False
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.AnnotationRole])
        return True

    def replace_record(self, bm: BookmarkRecord, ann: AnnotationRecord | None = None) -> bool:
        """Replace the record (and annotation) at the row matching ``bm.url``."""
        row = self.find_row_for_url(bm.url)
        if row < 0:
            return False
        self._items[row] = bm
        if ann is not None:
            self._annotations[bm.url] = ann
        else:
            self._annotations.pop(bm.url, None)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.BookmarkRole, self.AnnotationRole])
        return True

    def insert_at_top(self, bm: BookmarkRecord, ann: AnnotationRecord | None = None) -> None:
        """Insert *bm* at row 0 (most-recent position).

        Used after an external add (e.g. user toggled a bookmark on the
        history page) so the new entry appears immediately without waiting
        for a full reload.  Caller must ensure the bookmark passes the
        currently-active filter, otherwise it will appear until the next
        ``refresh()``.
        """
        existing_row = self.find_row_for_url(bm.url)
        if existing_row >= 0:
            # Treat as update if already loaded.
            self.replace_record(bm, ann)
            return
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, bm)
        if ann is not None:
            self._annotations[bm.url] = ann
        self.endInsertRows()
        self._adjust_total(+1)

    # ── Internal helpers ──────────────────────────────────────

    def _adjust_total(self, delta: int) -> None:
        new_total = max(0, self._total_count + delta)
        if new_total != self._total_count:
            self._total_count = new_total
            self.total_count_changed.emit(new_total)

    def _start_page_load(self) -> None:
        if self._is_loading or not self._has_more:
            return
        self._is_loading = True
        self.loading_changed.emit(True)
        gen = self._generation
        worker = _BookmarkPageWorker(self._db, self._filter, self._cursor, _PAGE_SIZE, gen, parent=self)
        worker.page_ready.connect(self._on_page_ready)
        # Schedule deleteLater AFTER the QThread exits so the C++ object is
        # never destroyed under a still-running run().  Identity-keyed clear
        # ensures we only drop the ref for THIS worker.
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.finished.connect(lambda w=worker: self._clear_page_worker_ref(w))
        self._page_worker = worker
        worker.start()

    def _start_count_load(self) -> None:
        gen = self._generation
        worker = _BookmarkCountWorker(self._db, self._filter, gen, parent=self)
        worker.count_ready.connect(self._on_count_ready)
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.finished.connect(lambda w=worker: self._clear_count_worker_ref(w))
        self._count_worker = worker
        worker.start()

    def _on_page_ready(self, records: list, ann_map: dict, gen: int) -> None:
        # Always release the loading flag for THIS load, even on stale gen.
        if gen == self._generation:
            self._is_loading = False
            self.loading_changed.emit(False)
            if not records:
                self._has_more = False
                return
            if len(records) < _PAGE_SIZE:
                self._has_more = False
            last = records[-1]
            # Cursor uses (bookmarked_at, id); cast to int because BookmarkRecord.id
            # is typed `int | None` even though DB-loaded rows always have it set.
            self._cursor = BookmarkCursor(bookmarked_at=int(last.bookmarked_at), id=int(last.id or 0))
            start_row = len(self._items)
            end_row = start_row + len(records) - 1
            self.beginInsertRows(QModelIndex(), start_row, end_row)
            self._items.extend(records)
            self._annotations.update(ann_map)
            self.endInsertRows()
        # On stale gen, drop result silently — a newer load is already running.

    def _on_count_ready(self, count: int, gen: int) -> None:
        if gen != self._generation:
            return
        if count != self._total_count:
            self._total_count = count
            self.total_count_changed.emit(count)

    def _on_tags_ready(self, tags: list, gen: int) -> None:
        # Tag list is global (not filter-scoped) so we always apply the latest
        # successful result, even if the model has since changed filter.
        # We do still discard if a NEWER tag-load won the race.
        if self._tag_worker is not None and self._tag_worker.isRunning():
            # A new tag-load is already in flight; let its result win.
            if gen < self._generation:
                return
        self._tags = list(tags)
        self.tags_changed.emit(self._tags)

    def _clear_page_worker_ref(self, w: _BookmarkPageWorker) -> None:
        if self._page_worker is w:
            self._page_worker = None

    def _clear_count_worker_ref(self, w: _BookmarkCountWorker) -> None:
        if self._count_worker is w:
            self._count_worker = None

    def _clear_tag_worker_ref(self, w: _TagListWorker) -> None:
        if self._tag_worker is w:
            self._tag_worker = None

    # ── Lifecycle ─────────────────────────────────────────────

    def shutdown(self) -> None:
        """Wait for in-flight workers to finish; safe to call from close paths.

        Bumping the generation first ensures any results that arrive before
        we have a chance to ``wait()`` are silently dropped.
        """
        self._generation += 1
        for w in (self._page_worker, self._count_worker, self._tag_worker):
            if w is not None and w.isRunning():
                w.wait(2000)
        self._page_worker = None
        self._count_worker = None
        self._tag_worker = None


__all__ = ["BookmarkListModel"]
