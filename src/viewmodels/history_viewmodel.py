# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from functools import lru_cache
import re
import time as _time
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)

from src.models.history_record import HistoryRecord
from src.services.favicon_manager import FaviconManager
from src.services.local_db import LocalDatabase
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_browser_icon, get_browser_pixmap
from src.utils.logger import get_logger

log = get_logger("viewmodel.history")

# Custom model roles for badge display (bookmark / annotation indicators)
BOOKMARK_ROLE = Qt.UserRole + 1
ANNOTATION_ROLE = Qt.UserRole + 2

# Page size for each database prefetch
PAGE_SIZE = 200
CACHE_PAGE_SIZE = PAGE_SIZE
# Maximum number of pages to keep in memory
MAX_CACHED_PAGES = 10
# Batch size for regex incremental scanning: number of candidate records per pass
REGEX_SCAN_BATCH = 5000

# Column definitions - all available columns
ALL_COLUMNS = {
    "title": {"index": 0, "label_key": N_("Page Title"), "align": Qt.AlignLeft},
    "url": {"index": 1, "label_key": N_("URL"), "align": Qt.AlignLeft},
    "browser": {"index": 2, "label_key": N_("Browser"), "align": Qt.AlignCenter, "icon_only": True},
    "visit_time": {"index": 3, "label_key": N_("Visit Time"), "align": Qt.AlignCenter},
    "visit_count": {"index": 4, "label_key": N_("Visit Count"), "align": Qt.AlignCenter},
    "domain": {"index": 5, "label_key": N_("Domain"), "align": Qt.AlignLeft},
    "profile_name": {"index": 6, "label_key": N_("Profile"), "align": Qt.AlignLeft},
    "metadata": {"index": 7, "label_key": N_("Description"), "align": Qt.AlignLeft},
    "typed_count": {"index": 8, "label_key": N_("Typed Count"), "align": Qt.AlignCenter},
    "first_visit_time": {"index": 9, "label_key": N_("First Visit Time"), "align": Qt.AlignCenter},
    "transition_type": {"index": 10, "label_key": N_("Transition Type"), "align": Qt.AlignCenter},
    "visit_duration": {"index": 11, "label_key": N_("Visit Duration (s)"), "align": Qt.AlignCenter},
    "device_name": {"index": 12, "label_key": N_("Device"), "align": Qt.AlignLeft},
}

# Default visible columns
DEFAULT_VISIBLE_COLUMNS = ["title", "url", "browser", "visit_time", "visit_count", "domain", "profile_name"]


# ── Background worker ────────────────────────────────────────


class _ReloadWorker(QThread):
    """Run one reload DB query off the main thread.

    Emits ``done(generation, keyword_index, total_count, keyword_materialized)``
    on the thread that *started* this worker (i.e. the main thread), so the
    connected slot in :class:`HistoryTableModel` can safely mutate Qt objects.

    Parameters
    ----------
    db:
        The shared :class:`LocalDatabase` instance.
    params:
        A snapshot of all filter parameters (taken at the moment ``reload()``
        was called) so that a concurrent ``set_filter()`` cannot mutate them
        while the worker is running.
    use_id_index:
        When ``True``, call ``get_filtered_id_times`` and return the full
        ``(id, visit_time)`` index.  When ``False``, call ``get_filtered_count``
        and return an empty index.
    generation:
        Monotonic counter from the owning model; the model discards results
        whose generation does not match the current value.
    """

    # (generation, keyword_index, total_count, keyword_materialized)
    done: Signal = Signal(int, list, int, bool)

    def __init__(
        self,
        db: LocalDatabase,
        params: dict,
        use_id_index: bool,
        generation: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._params = params
        self._use_id_index = use_id_index
        self._generation = generation

    def run(self) -> None:  # executed in worker thread
        try:
            p = self._params
            kw = {
                "keyword": p["keyword"],
                "browser_type": p["browser_type"],
                "date_from": p["date_from"],
                "date_to": p["date_to"],
                "excluded_ids": p["excluded_ids"],
                "domain_ids": p["domain_ids"],
                "excludes": p["excludes"],
                "title_only": p["title_only"],
                "url_only": p["url_only"],
                "bookmarked_only": p["bookmarked_only"],
                "has_annotation": p["has_annotation"],
                "bookmark_tag": p["bookmark_tag"],
                "device_ids": p["device_ids"],
            }
            if self._use_id_index:
                index = self._db.get_filtered_id_times(**kw)
                self.done.emit(self._generation, index, len(index), True)
            else:
                count = self._db.get_filtered_count(**kw)
                self.done.emit(self._generation, [], count, False)
        except Exception:
            log.exception("_ReloadWorker failed (generation=%d)", self._generation)
            self.done.emit(self._generation, [], 0, False)


# ── Table model ──────────────────────────────────────────────


class HistoryTableModel(QAbstractTableModel):
    """Virtualised history table model with virtual scrolling support."""

    total_count_changed = Signal(int, bool)  # (count, has_more)
    columns_changed = Signal()
    # Emitted after every batch write to the page cache so the view can update
    # row heights for date-separator rows without iterating all records.
    # Payload: (base_row_index, records_in_batch)
    records_loaded = Signal(int, list)

    def __init__(self, db: LocalDatabase, favicon_manager: FaviconManager, visible_columns=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._favicon_manager = favicon_manager

        # Visible columns configuration
        self._visible_columns = visible_columns or DEFAULT_VISIBLE_COLUMNS
        self._update_column_mapping()

        # Filter parameters
        self._keyword = ""
        self._browser_type = ""
        self._date_from: int | None = None
        self._date_to: int | None = None
        self._hidden_ids: set[int] = set()

        # Extended search params
        self._domain_ids: list[int] | None = None
        self._excludes: list[str] | None = None
        self._title_only: bool = False
        self._url_only: bool = False
        self._use_regex: bool = False
        self._bookmarked_only: bool = False
        self._has_annotation: bool = False
        self._bookmark_tag: str = ""
        self._device_ids: list[int] | None = None

        # Device name map for display
        self._device_name_map: dict[int, str] = {}

        # Virtualization state
        self._total_count = 0
        self._page_cache: dict[int, list[HistoryRecord]] = {}
        self._page_lru: OrderedDict[int, None] = OrderedDict()

        # Regex incremental load state
        # Regex incremental / keyword search state
        self._regex_scan_offset: int = 0  # DB offset of already-scanned candidates
        self._regex_has_more: bool = False  # Whether more candidates remain to be scanned
        self._keyword_materialized: bool = False  # True when _keyword_index is populated
        self._keyword_index: list[tuple[int, int]] = []  # (id, visit_time) lightweight scroll index

        # Badge URL caches — bulk-loaded on each reload(), O(1) per-row lookup
        self._bookmarked_urls: set[str] = set()
        self._annotated_urls: set[str] = set()

        self._favicon_manager.favicons_updated.connect(self._on_favicons_updated)

        # ── Row-level cache ───────────────────────────────────────────────────
        # Qt calls data() once per column for the same row; cache the last
        # looked-up record so the 2nd-7th column calls skip the OrderedDict lookup.
        self._last_row: int = -1
        self._last_record: HistoryRecord | None = None

        # ── Prefetch debounce ─────────────────────────────────────────────────
        # Coalesce rapid prefetch_pixmaps calls (one per _fetch_page) into a
        # single batched call after a short idle period.  During fast scrolling
        # multiple pages may be fetched within one frame; without debouncing
        # each page would fire a separate DB round-trip inside prefetch_pixmaps.
        self._prefetch_pending: list[HistoryRecord] = []
        self._prefetch_timer = QTimer()
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(150)  # 150 ms idle before flushing
        self._prefetch_timer.timeout.connect(self._flush_prefetch)

    # ── Public API ───────────────────────────────────────────

    def _update_column_mapping(self):
        """Update column index mapping based on visible columns."""
        self._col_to_key = {}
        self._key_to_col = {}
        for display_idx, key in enumerate(self._visible_columns):
            self._col_to_key[display_idx] = key
            self._key_to_col[key] = display_idx

    def set_visible_columns(self, columns: list[str]) -> None:
        """Update which columns are visible."""
        self.beginResetModel()
        self._visible_columns = columns
        self._update_column_mapping()
        self.endResetModel()
        self.columns_changed.emit()

    def get_visible_columns(self) -> list[str]:
        """Get list of currently visible column keys."""
        return self._visible_columns.copy()

    def get_all_columns(self) -> dict:
        """Get all available column definitions."""
        return ALL_COLUMNS.copy()

    def set_hidden_ids(self, ids: set[int]) -> None:
        self._hidden_ids = ids
        self.reload()

    # ── QAbstractTableModel interface ────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return self._total_count

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._visible_columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal:
            if section >= len(self._visible_columns):
                return None

            col_key = self._col_to_key[section]
            col_def = ALL_COLUMNS.get(col_key, {})

            if role == Qt.DisplayRole:
                if col_def.get("icon_only"):
                    return ""
                return _(col_def.get("label_key", col_key.title()))

            if role == Qt.DecorationRole:
                if col_key == "browser":
                    return get_browser_icon("web", size=16)
                return None

            if role == Qt.ToolTipRole:
                if col_key == "browser":
                    return _("Browser")
                return _(col_def.get("label_key", col_key.title()))

            if role == Qt.TextAlignmentRole:
                align = col_def.get("align", Qt.AlignLeft)
                return int(align | Qt.AlignVCenter)

        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # noqa: PLR0911
        if not index.isValid():
            return None
        if role not in (
            Qt.DisplayRole,
            Qt.DecorationRole,
            Qt.ToolTipRole,
            Qt.UserRole,
            Qt.TextAlignmentRole,
            BOOKMARK_ROLE,
            ANNOTATION_ROLE,
        ):
            return None

        row = index.row()
        record = self._get_record_at(row)
        if record is None:
            return None

        col_idx = index.column()
        if col_idx >= len(self._visible_columns):
            return None

        col_key = self._col_to_key[col_idx]
        col_def = ALL_COLUMNS.get(col_key, {})

        if role == Qt.DisplayRole:
            if col_key == "title":
                return record.title or record.url
            if col_key == "url":
                return record.url
            if col_key == "browser":
                return ""
            if col_key == "visit_time":
                return _format_time(record.visit_time)
            if col_key == "visit_count":
                return str(record.visit_count)
            if col_key == "domain":
                return record.domain
            if col_key == "profile_name":
                return record.profile_name or ""
            if col_key == "metadata":
                return record.metadata or ""
            if col_key == "typed_count":
                return str(record.typed_count) if record.typed_count is not None else ""
            if col_key == "first_visit_time":
                return _format_time(record.first_visit_time) if record.first_visit_time else ""
            if col_key == "transition_type":
                return _format_transition(record.transition_type, record.browser_type)
            if col_key == "visit_duration":
                if record.visit_duration is not None:
                    return f"{record.visit_duration:.1f}s"
                return ""
            if col_key == "device_name":
                if record.device_id is not None:
                    return self._device_name_map.get(record.device_id, "")
                return ""

        elif role == Qt.DecorationRole:
            if col_key == "title":
                return self._favicon_manager.get_pixmap(record.url, size=16, domain=record.domain)
            if col_key == "browser":
                return get_browser_pixmap(record.browser_type or "web", size=20)

        elif role == Qt.ToolTipRole:
            if col_key == "title":
                return record.metadata or record.title
            if col_key == "url":
                return record.url
            if col_key == "browser":
                return _browser_display_name(record.browser_type)
            if col_key == "visit_count":
                return _("Visited {count} times").format(count=record.visit_count)
            if col_key == "domain":
                return record.domain
            if col_key == "profile_name":
                return _("Browser Profile: {profile}").format(profile=record.profile_name or _("Default"))
            if col_key == "metadata":
                return record.metadata or _("No description available")
            if col_key == "typed_count":
                if record.typed_count is not None:
                    return _("Manually typed in address bar {count} time(s)").format(count=record.typed_count)
                return _("Not available for this browser")
            if col_key == "first_visit_time":
                if record.first_visit_time:
                    return _("First visited: {t}").format(t=_format_time(record.first_visit_time))
                return _("Not available for this browser")
            if col_key == "transition_type":
                return _format_transition(record.transition_type, record.browser_type) or _("Not available")
            if col_key == "visit_duration":
                if record.visit_duration is not None:
                    return _("Time on page: {s:.1f} seconds").format(s=record.visit_duration)
                return _("Not available for this browser")

        elif role == Qt.UserRole:
            return record

        elif role == BOOKMARK_ROLE:
            return record.url in self._bookmarked_urls

        elif role == ANNOTATION_ROLE:
            return record.url in self._annotated_urls

        elif role == Qt.TextAlignmentRole:
            align = col_def.get("align", Qt.AlignLeft)
            # Add vertical centering to all columns
            return int(align | Qt.AlignVCenter)

        return None

    # ── Data loading ─────────────────────────────────────────

    def set_filter(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
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
    ):
        self._keyword = keyword
        self._browser_type = browser_type
        self._date_from = date_from
        self._date_to = date_to
        # Extended search params
        self._domain_ids = domain_ids
        self._excludes = excludes
        self._title_only = title_only
        self._url_only = url_only
        self._use_regex = use_regex
        self._bookmarked_only = bookmarked_only
        self._has_annotation = has_annotation
        self._bookmark_tag = bookmark_tag
        self._device_ids = device_ids

        self.reload()

    def reload(self):
        """Reset cache and kick off an async DB query to get the new row count.

        The actual DB work runs in a background QThread (_ReloadWorker) so the
        main thread — and therefore the UI — is never blocked.  A monotonically
        increasing generation counter is used to discard results that arrive
        after a newer reload() has already been issued (e.g. rapid user input).
        """
        self._page_cache.clear()
        self._page_lru.clear()
        self._regex_scan_offset = 0
        self._regex_has_more = False
        self._keyword_materialized = False
        self._keyword_index.clear()
        self._last_row = -1
        self._last_record = None

        # Bump generation so any in-flight worker result is treated as stale.
        self._reload_generation: int = getattr(self, "_reload_generation", 0) + 1
        generation = self._reload_generation

        # Defer badge loading — only needed when rows are actually painted.
        QTimer.singleShot(0, self._load_badge_data)

        if self._use_regex and self._keyword:
            # Regex incremental mode runs synchronously (already batched / cheap).
            self._scan_regex_batch()
            self._apply_reload_result(
                generation=generation,
                keyword_index=list(self._keyword_index),
                total_count=len(self._keyword_index),
                keyword_materialized=False,
            )
            return

        # Snapshot filter params for the worker (avoids races if set_filter is
        # called again before the worker finishes).
        params = {
            "keyword": self._keyword,
            "browser_type": self._browser_type,
            "date_from": self._date_from,
            "date_to": self._date_to,
            "excluded_ids": frozenset(self._hidden_ids),
            "domain_ids": list(self._domain_ids) if self._domain_ids is not None else None,
            "excludes": list(self._excludes) if self._excludes is not None else None,
            "title_only": self._title_only,
            "url_only": self._url_only,
            "bookmarked_only": self._bookmarked_only,
            "has_annotation": self._has_annotation,
            "bookmark_tag": self._bookmark_tag,
            "device_ids": list(self._device_ids) if self._device_ids is not None else None,
        }
        use_id_index = bool(self._keyword)

        worker = _ReloadWorker(self._db, params, use_id_index, generation, parent=self)
        worker.done.connect(self._on_reload_done)
        worker.done.connect(worker.deleteLater)
        # Keep a reference so the thread is not garbage-collected mid-run.
        self._reload_worker = worker
        worker.start()

    @Slot(int, list, int, bool)
    def _on_reload_done(
        self,
        generation: int,
        keyword_index: list,
        total_count: int,
        keyword_materialized: bool,
    ) -> None:
        """Receive async reload result and update the model (main-thread slot)."""
        # Discard stale results from superseded reload() calls.
        if generation != self._reload_generation:
            return
        self._apply_reload_result(generation, keyword_index, total_count, keyword_materialized)

    def _apply_reload_result(
        self,
        generation: int,
        keyword_index: list,
        total_count: int,
        keyword_materialized: bool,
    ) -> None:
        """Apply a (possibly async) reload result to the model state."""
        if keyword_materialized:
            self._keyword_index = keyword_index
            self._keyword_materialized = True

        self.beginResetModel()
        self._total_count = total_count
        self.endResetModel()

        self.total_count_changed.emit(self._total_count, self._regex_has_more)

        # Defer first page fetch to avoid blocking the model reset.
        if not self._keyword_materialized and not (self._use_regex and self._keyword) and self._total_count > 0:
            QTimer.singleShot(0, lambda: self._fetch_page(0))

    def _load_badge_data(self):
        """Load badge URL sets for O(1) lookup during rendering (deferred)."""
        self._bookmarked_urls = self._db.get_bookmarked_urls()
        self._annotated_urls = self._db.get_annotated_urls()
        self._device_name_map = self._db.get_device_name_map()

    def load_more(self) -> bool:
        """In virtualised mode, delegate to load_more_regex() for regex searches; otherwise no manual loading needed."""
        if self._use_regex and self._keyword:
            return self.load_more_regex()
        return False

    def _scan_regex_batch(self) -> None:
        """Scan the next REGEX_SCAN_BATCH candidates and append matching (id, visit_time) to _keyword_index."""
        try:
            prog = re.compile(self._keyword, re.IGNORECASE)
        except Exception as exc:
            log.warning("Invalid regex '%s': %s", self._keyword, exc)
            self._regex_has_more = False
            return

        candidates = self._db.get_records(
            keyword="",
            browser_type=self._browser_type,
            date_from=self._date_from,
            date_to=self._date_to,
            limit=REGEX_SCAN_BATCH,
            offset=self._regex_scan_offset,
            excluded_ids=self._hidden_ids,
            domain_ids=self._domain_ids,
            excludes=self._excludes,
            title_only=False,  # Filter applied in the Python layer
            url_only=False,
            use_regex=False,
            bookmarked_only=self._bookmarked_only,
            has_annotation=self._has_annotation,
            bookmark_tag=self._bookmark_tag,
            device_ids=self._device_ids,
        )

        before = len(self._keyword_index)
        for r in candidates:
            if self._title_only:
                hit = bool(prog.search(r.title or ""))
            elif self._url_only:
                hit = bool(prog.search(r.url))
            else:
                hit = bool(prog.search(r.title or "") or prog.search(r.url))
            if hit:
                self._keyword_index.append((r.id, r.visit_time))

        self._regex_scan_offset += len(candidates)
        self._regex_has_more = len(candidates) >= REGEX_SCAN_BATCH

        new_count = len(self._keyword_index) - before
        if new_count:
            self.records_loaded.emit(before, [])  # notify view of new rows (no full records needed)

    def load_more_regex(self) -> bool:
        """Load the next batch of regex matches and append them to the model. Returns True if new rows were added."""
        if not self.can_load_more:
            return False

        old_count = len(self._keyword_index)
        self._scan_regex_batch()
        new_count = len(self._keyword_index)

        if new_count > old_count:
            self.beginInsertRows(QModelIndex(), old_count, new_count - 1)
            self._total_count = new_count
            self.endInsertRows()
            self.total_count_changed.emit(self._total_count, self._regex_has_more)
            return True

        # No new matches in this batch, but scan offset has advanced; notify view of has_more change
        self.total_count_changed.emit(self._total_count, self._regex_has_more)
        return False

    def refresh_icons(self, view=None) -> None:
        """Invalidate only icon columns after a theme change, without triggering beginResetModel.

        When a QTableView is provided, only the currently visible row range is notified.
        Without one, the range is capped at the first 200 rows.
        Never emit dataChanged for the entire table — Qt would invoke data() for every row.
        """
        if self._total_count == 0:
            return

        first_row = 0
        last_row = min(self._total_count - 1, 199)

        if view is not None:
            try:
                vp_height = view.viewport().height()
                row_height = max(view.verticalHeader().defaultSectionSize(), 1)
                first_row = max(0, view.rowAt(0))
                visible_count = (vp_height // row_height) + 2
                last_row = min(self._total_count - 1, first_row + visible_count)
            except Exception:
                pass

        # Find columns that have icons
        icon_columns = []
        for col_idx, col_key in enumerate(self._visible_columns):
            if col_key in ["title", "browser"]:
                icon_columns.append(col_idx)

        if icon_columns:
            first_col = min(icon_columns)
            last_col = max(icon_columns)
            self.dataChanged.emit(
                self.index(first_row, first_col),
                self.index(last_row, last_col),
                [Qt.DecorationRole],
            )

    def invalidate_badge_cache(self, view=None) -> None:
        """Reload badge URL sets and emit dataChanged for title column to refresh badges.

        Only emits for visible rows to avoid performance issues with large datasets.
        """
        # Reload badge data from DB
        self._bookmarked_urls = self._db.get_bookmarked_urls()
        self._annotated_urls = self._db.get_annotated_urls()

        if self._total_count == 0:
            return

        # Determine visible row range
        first_row = 0
        last_row = min(self._total_count - 1, 199)

        if view is not None:
            try:
                vp_height = view.viewport().height()
                row_height = max(view.verticalHeader().defaultSectionSize(), 1)
                first_row = max(0, view.rowAt(0))
                visible_count = (vp_height // row_height) + 2
                last_row = min(self._total_count - 1, first_row + visible_count)
            except Exception:
                pass

        # Find title column index
        title_col = self._key_to_col.get("title")
        if title_col is not None:
            self.dataChanged.emit(
                self.index(first_row, title_col),
                self.index(last_row, title_col),
                [BOOKMARK_ROLE, ANNOTATION_ROLE],
            )

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def is_filtered(self) -> bool:
        """True when a keyword search is active (separators should be hidden)."""
        return bool(self._keyword)

    @property
    def can_load_more(self) -> bool:
        """True when the view can call load_more_regex() after scrolling to the bottom."""
        return self._regex_has_more and bool(self._use_regex and self._keyword)

    def get_record_at(self, row: int) -> HistoryRecord | None:
        return self._get_record_at(row)

    def get_visit_time_at_row(self, row: int) -> int | None:
        """Return only the visit_time for *row* in the current filtered set.
        Used by the scroll bubble to avoid loading full record pages."""
        if row < 0 or row >= self._total_count:
            return None
        # Regex or pre-materialized keyword mode: read visit_time from lightweight index
        if self._keyword_materialized or (self._use_regex and self._keyword):
            if row < len(self._keyword_index):
                return self._keyword_index[row][1]
            return None
        # Check page cache first to avoid a DB round-trip
        cached = self.peek_record_at(row)
        if cached is not None:
            return cached.visit_time
        return self._db.get_visit_time_at_offset(
            offset=row,
            keyword=self._keyword,
            browser_type=self._browser_type,
            date_from=self._date_from,
            date_to=self._date_to,
            excluded_ids=self._hidden_ids,
            domain_ids=self._domain_ids,
            excludes=self._excludes,
            title_only=self._title_only,
            url_only=self._url_only,
            bookmarked_only=self._bookmarked_only,
            has_annotation=self._has_annotation,
            bookmark_tag=self._bookmark_tag,
            device_ids=self._device_ids,
        )

    def peek_record_at(self, row: int) -> HistoryRecord | None:
        """Return the cached record at *row* without triggering a DB fetch.

        Used by the view layer (date-separator logic) to avoid recursive
        page-fetch cascades when checking the previous row at a page boundary.
        """
        if row < 0 or row >= self._total_count:
            return None
        page_index = row // CACHE_PAGE_SIZE
        page = self._page_cache.get(page_index)
        if page is None:
            return None
        local_row = row % CACHE_PAGE_SIZE
        return page[local_row] if local_row < len(page) else None

    # ── Internal: virtual page cache ─────────────────────────

    def _get_record_at(self, row: int) -> HistoryRecord | None:
        if row == self._last_row:
            return self._last_record
        if row < 0 or row >= self._total_count:
            return None
        # All modes (regex, keyword, full history) use the page cache for full records
        page_index = row // CACHE_PAGE_SIZE
        page = self._get_or_fetch_page(page_index)
        local_row = row % CACHE_PAGE_SIZE
        record = page[local_row] if local_row < len(page) else None
        self._last_row = row
        self._last_record = record
        return record

    def _get_or_fetch_page(self, page_index: int) -> list[HistoryRecord]:
        if page_index in self._page_cache:
            # O(1) LRU update: move to end to mark as most-recently used
            self._page_lru.move_to_end(page_index)
            return self._page_cache[page_index]
        return self._fetch_page(page_index)

    def _fetch_page(self, page_index: int) -> list[HistoryRecord]:
        """Fetch one page from the database and write it into the LRU cache."""
        start = page_index * CACHE_PAGE_SIZE
        if self._keyword_materialized or (self._use_regex and self._keyword):
            # Use the lightweight ID index: slice IDs for this page, fetch full records by PK.
            # WHERE id IN (...) uses the primary key index — O(1) per row, no full-table scan.
            ids = [entry[0] for entry in self._keyword_index[start : start + CACHE_PAGE_SIZE]]
            records = self._db.get_records_by_ids(ids)
        else:
            records = self._db.get_records(
                keyword=self._keyword,
                browser_type=self._browser_type,
                date_from=self._date_from,
                date_to=self._date_to,
                limit=CACHE_PAGE_SIZE,
                offset=start,
                excluded_ids=self._hidden_ids,
                domain_ids=self._domain_ids,
                excludes=self._excludes,
                title_only=self._title_only,
                url_only=self._url_only,
                use_regex=False,  # Regex filtering is done in Python; DB fetches unfiltered candidates
                bookmarked_only=self._bookmarked_only,
                has_annotation=self._has_annotation,
                bookmark_tag=self._bookmark_tag,
                device_ids=self._device_ids,
            )

        self._page_cache[page_index] = records
        # LRU write: evict after inserting so the newest page counts toward the limit
        self._page_lru.pop(page_index, None)
        self._page_lru[page_index] = None

        while len(self._page_lru) > MAX_CACHED_PAGES:
            oldest, _ = self._page_lru.popitem(last=False)
            self._page_cache.pop(oldest, None)

        if records:
            # Coalesce prefetch calls across rapid page fetches — a single
            # batched prefetch_pixmaps call fires after an 80 ms idle period
            # instead of one DB round-trip per page during fast scrolling.
            QTimer.singleShot(0, lambda r=records: self._schedule_prefetch(r))
            # Notify the view so it can resize date-separator rows
            self.records_loaded.emit(start, records)

        return records

    # ── Prefetch debounce ─────────────────────────────────────────────────────

    def _schedule_prefetch(self, records: list[HistoryRecord]) -> None:
        """Queue records for a debounced prefetch_pixmaps call.

        Multiple _fetch_page calls within 80 ms are coalesced into a single
        prefetch_pixmaps invocation, cutting repeated SQLite round-trips when
        the user fast-scrolls through uncached pages.
        """
        self._prefetch_pending.extend(records)
        self._prefetch_timer.start()  # restart the 80 ms countdown

    def _flush_prefetch(self) -> None:
        """Flush the pending prefetch batch after the debounce idle period."""
        if self._prefetch_pending:
            records, self._prefetch_pending = self._prefetch_pending, []
            self._favicon_manager.prefetch_pixmaps(records, size=16)

    # ── Favicon refresh ───────────────────────────────────────

    @Slot(object)
    def _on_favicons_updated(self, updated_domains: set) -> None:
        if not self._total_count or not updated_domains:
            return

        affected_rows: list[int] = []
        for page_index, records in self._page_cache.items():
            base = page_index * CACHE_PAGE_SIZE
            for local_idx, record in enumerate(records):
                if record.domain in updated_domains:
                    affected_rows.append(base + local_idx)

        if not affected_rows:
            return
        affected_rows.sort()
        start = prev = affected_rows[0]
        for row in affected_rows[1:]:
            if row == prev + 1:
                prev = row
            else:
                self._emit_decoration_changed(start, prev)
                start = prev = row
        self._emit_decoration_changed(start, prev)

    def _emit_decoration_changed(self, first_row: int, last_row: int) -> None:
        # Find title column index
        title_col = self._key_to_col.get("title")
        if title_col is not None:
            self.dataChanged.emit(
                self.index(first_row, title_col),
                self.index(last_row, title_col),
                [Qt.DecorationRole],
            )


# ── ViewModel ────────────────────────────────────────────────


class HistoryViewModel(QObject):
    """Mediates between HistoryPage view and HistoryTableModel."""

    model_ready = Signal()
    browser_list_changed = Signal(list)
    device_list_changed = Signal(list)  # list[str] — device names
    tag_list_changed = Signal(list)  # list[str] — tag strings
    status_message = Signal(str)
    ui_config_changed = Signal(list, dict)
    top_domains_loaded = Signal(list)  # list[tuple[str, int]]

    def __init__(self, db: LocalDatabase, favicon_manager: FaviconManager, visible_columns=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._favicon_manager = favicon_manager
        self._initialized = False
        self._use_regex = False  # Track regex search state for UI display
        self.table_model = HistoryTableModel(db, favicon_manager, visible_columns)

    def initialize(self):
        """Initialize the view model with progressive loading to avoid UI freeze.

        Phase 1: Mark as initialized and emit ready signal immediately
        Phase 2: Load data asynchronously in stages
        """
        self._initialized = True
        self.model_ready.emit()

        # Defer data loading to avoid blocking the UI thread
        QTimer.singleShot(0, self._load_initial_data)

    def _load_initial_data(self):
        """Load initial data in stages to keep UI responsive."""
        # Stage 1: Load the table data (most important)
        self.table_model.reload()

        # Stage 2: Load filter options (slightly delayed)
        QTimer.singleShot(50, self._refresh_browser_list)
        QTimer.singleShot(100, self._refresh_device_list)
        QTimer.singleShot(150, self._refresh_tag_list)

        # Stage 3: Load top domains (lowest priority, already async)
        QTimer.singleShot(200, self._load_top_domains_async)

    def _load_top_domains_async(self):
        """Fetch top domains in a background thread and emit top_domains_loaded."""
        db = self._db

        class _Worker(QThread):
            done = Signal(list)

            def run(self):
                try:
                    self.done.emit(db.get_top_domains(30))
                except Exception:
                    self.done.emit([])

        self._domain_worker = _Worker(self)
        self._domain_worker.done.connect(self.top_domains_loaded)
        self._domain_worker.done.connect(self._domain_worker.deleteLater)
        self._domain_worker.start()

    def search(
        self,
        keyword: str,
        browser_type: str,
        date_from: int | None,
        date_to: int | None,
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
    ):
        self._use_regex = use_regex  # Save for status message formatting
        self.table_model.set_filter(
            keyword,
            browser_type,
            date_from,
            date_to,
            domain_ids=domain_ids,
            excludes=excludes,
            title_only=title_only,
            url_only=url_only,
            use_regex=use_regex,
            bookmarked_only=bookmarked_only,
            has_annotation=has_annotation,
            bookmark_tag=bookmark_tag,
            device_ids=device_ids,
        )
        count = self.table_model.total_count
        has_more = self.table_model.can_load_more
        # When regex search has more unscanned results, show "N+" instead of an exact count
        if use_regex and has_more:
            self.status_message.emit(_("{total}+ records").format(total=f"{count:,}"))
        else:
            self.status_message.emit(_("{total} records").format(total=f"{count:,}"))

    def load_more(self) -> bool:
        """Called when the user scrolls to the bottom; triggers regex incremental loading.
        No manual loading is needed in non-regex mode."""
        if self._use_regex:
            result = self.table_model.load_more_regex()
            count = self.table_model.total_count
            has_more = self.table_model.can_load_more
            if has_more:
                self.status_message.emit(_("{total}+ records").format(total=f"{count:,}"))
            else:
                self.status_message.emit(_("{total} records").format(total=f"{count:,}"))
            return result
        return False

    def refresh(self):
        self.table_model.reload()
        self._refresh_browser_list()
        self._refresh_device_list()
        self._refresh_tag_list()

    def set_hidden_ids(self, ids: set[int]) -> None:
        if self._initialized:
            self.table_model.set_hidden_ids(ids)
        else:
            self.table_model._hidden_ids = ids

    def resolve_domain_ids(self, domains: list[str]) -> list[int]:
        return self._db.resolve_domain_ids(domains)

    def resolve_device_ids(self, name_or_uuid: str) -> list[int]:
        return self._db.resolve_device_ids(name_or_uuid)

    def _refresh_browser_list(self):
        self.browser_list_changed.emit(self._db.get_browser_types())

    def _refresh_device_list(self):
        devices = self._db.get_all_devices()
        self.device_list_changed.emit([d["name"] for d in devices if d.get("name")])

    def _refresh_tag_list(self):
        self.tag_list_changed.emit(self._db.get_all_bookmark_tags())


# ── Utilities ────────────────────────────────────────────────

_BROWSER_NAMES: dict[str, str] = {
    "chrome": "Google Chrome",
    "chrome_beta": "Google Chrome Beta",
    "chrome_canary": "Google Chrome Canary",
    "chrome_dev": "Google Chrome Dev",
    "chrome_for_testing": "Google Chrome for Testing",
    "edge": "Microsoft Edge",
    "edge_beta": "Microsoft Edge Beta",
    "edge_dev": "Microsoft Edge Dev",
    "edge_canary": "Microsoft Edge Canary",
    "brave": "Brave",
    "brave_beta": "Brave Beta",
    "brave_dev": "Brave Dev",
    "brave_nightly": "Brave Nightly",
    "firefox": "Mozilla Firefox",
    "opera": "Opera",
    "opera_gx": "Opera GX",
    "vivaldi": "Vivaldi",
    "arc": "Arc",
    "safari": "Safari",
    "chromium": "Chromium",
    "yandex": "Yandex Browser",
    "whale": "Naver Whale",
    "waterfox": "Waterfox",
    "librewolf": "LibreWolf",
    "seamonkey": "SeaMonkey",
}


def _browser_display_name(bt: str) -> str:
    return _BROWSER_NAMES.get(bt, bt.title())


@lru_cache(maxsize=4096)
def _format_time_cached(ts: int, tz_offset_seconds: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return str(ts)


# Cache timezone offset — refreshed at most once per 60 s to catch DST transitions
# without paying the cost of 3 datetime allocations on every cell render.
# [offset_seconds, monotonic_timestamp]
_tz_cache: list[int | float] = [0, 0.0]


def _format_time(ts: int) -> str:
    now = _time.monotonic()
    if now - _tz_cache[1] > 60:
        _tz_cache[0] = int(datetime.now(UTC).astimezone().utcoffset().total_seconds())
        _tz_cache[1] = now
    return _format_time_cached(ts, _tz_cache[0])


_CHROMIUM_TRANSITION_LABELS = {
    0: "Link",
    1: "Typed",
    2: "Auto Bookmark",
    3: "Auto Subframe",
    4: "Manual Subframe",
    5: "Generated",
    6: "Auto Toplevel",
    7: "Form Submit",
    8: "Reload",
    9: "Keyword",
    10: "Keyword Generated",
}
_FIREFOX_TRANSITION_LABELS = {
    1: "Link",
    2: "Typed",
    3: "Bookmark",
    4: "Embed",
    5: "Redirect Permanent",
    6: "Redirect Temporary",
    7: "Download",
    8: "Framed Link",
    9: "Reload",
}


def _format_transition(value: int | None, browser_type: str) -> str:
    if value is None:
        return ""
    if browser_type in ("firefox", "librewolf", "floorp", "waterfox"):
        return _FIREFOX_TRANSITION_LABELS.get(value, str(value))
    return _CHROMIUM_TRANSITION_LABELS.get(value, str(value))
