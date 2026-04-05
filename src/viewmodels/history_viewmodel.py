# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
import re
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


class HistoryTableModel(QAbstractTableModel):
    """Virtualised history table model with virtual scrolling support."""

    total_count_changed = Signal(int, bool)  # (count, has_more)
    columns_changed = Signal()

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
        self._regex_results: list[HistoryRecord] = []  # Matched records (in-memory cache)
        self._regex_scan_offset: int = 0  # DB offset of already-scanned candidates
        self._regex_has_more: bool = False  # Whether more candidates remain to be scanned

        # Badge URL caches — bulk-loaded on each reload(), O(1) per-row lookup
        self._bookmarked_urls: set[str] = set()
        self._annotated_urls: set[str] = set()

        self._favicon_manager.favicons_updated.connect(self._on_favicons_updated)

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
                return self._extract_domain(record.url)
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
                return self._favicon_manager.get_pixmap(record.url, size=16)
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
                return self._extract_domain(record.url)
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

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse

            netloc = urlparse(url).netloc or ""
            # Strip port
            domain = netloc.rsplit(":", 1)[0] if ":" in netloc and not netloc.startswith("[") else netloc
            # Strip www.
            if domain.lower().startswith("www."):
                domain = domain[4:]
            return domain.lower()
        except Exception:
            return ""

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
        """Reset cache, re-query total count, and trigger a full view refresh."""
        self._page_cache.clear()
        self._page_lru.clear()
        self._regex_results.clear()
        self._regex_scan_offset = 0
        self._regex_has_more = False

        # Load badge URL sets for O(1) lookup during rendering
        self._bookmarked_urls = self._db.get_bookmarked_urls()
        self._annotated_urls = self._db.get_annotated_urls()
        self._device_name_map = self._db.get_device_name_map()

        if self._use_regex and self._keyword:
            # Regex incremental mode: scan the first batch without blocking on a full COUNT query
            self._scan_regex_batch()
            new_count = len(self._regex_results)
        else:
            new_count = self._db.get_filtered_count(
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

        self.beginResetModel()
        self._total_count = new_count
        self.endResetModel()

        self.total_count_changed.emit(self._total_count, self._regex_has_more)

        # Non-regex mode: prefetch the first page
        if not (self._use_regex and self._keyword) and self._total_count > 0:
            self._fetch_page(0, defer_pixmaps=True)

    def load_more(self) -> bool:
        """In virtualised mode, delegate to load_more_regex() for regex searches; otherwise no manual loading needed."""
        if self._use_regex and self._keyword:
            return self.load_more_regex()
        return False

    def _scan_regex_batch(self) -> None:
        """Scan the next REGEX_SCAN_BATCH candidates and append any matches to _regex_results."""
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

        before = len(self._regex_results)
        for r in candidates:
            if self._title_only:
                hit = bool(prog.search(r.title or ""))
            elif self._url_only:
                hit = bool(prog.search(r.url))
            else:
                hit = bool(prog.search(r.title or "") or prog.search(r.url))
            if hit:
                self._regex_results.append(r)

        self._regex_scan_offset += len(candidates)
        # If this batch was full, there may be more candidates remaining
        self._regex_has_more = len(candidates) >= REGEX_SCAN_BATCH

        new_matches = self._regex_results[before:]
        if new_matches:
            QTimer.singleShot(0, lambda r=new_matches: self._favicon_manager.prefetch_pixmaps(r, size=16))

    def load_more_regex(self) -> bool:
        """Load the next batch of regex matches and append them to the model. Returns True if new rows were added."""
        if not self.can_load_more:
            return False

        old_count = len(self._regex_results)
        self._scan_regex_batch()
        new_count = len(self._regex_results)

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
    def can_load_more(self) -> bool:
        """True when the view can call load_more_regex() after scrolling to the bottom."""
        return self._regex_has_more and bool(self._use_regex and self._keyword)

    def get_record_at(self, row: int) -> HistoryRecord | None:
        return self._get_record_at(row)

    # ── Internal: virtual page cache ─────────────────────────

    def _get_record_at(self, row: int) -> HistoryRecord | None:
        if row < 0 or row >= self._total_count:
            return None
        # Regex incremental mode: read directly from the in-memory results list
        if self._use_regex and self._keyword:
            if row < len(self._regex_results):
                return self._regex_results[row]
            return None
        # Normal mode: use the page cache
        page_index = row // CACHE_PAGE_SIZE
        page = self._get_or_fetch_page(page_index)
        local_row = row % CACHE_PAGE_SIZE
        if local_row < len(page):
            return page[local_row]
        return None

    def _get_or_fetch_page(self, page_index: int) -> list[HistoryRecord]:
        if page_index in self._page_cache:
            # O(1) LRU update: move to end to mark as most-recently used
            self._page_lru.move_to_end(page_index)
            return self._page_cache[page_index]
        return self._fetch_page(page_index)

    def _fetch_page(self, page_index: int, defer_pixmaps: bool = False) -> list[HistoryRecord]:
        """Fetch one page from the database and write it into the LRU cache."""
        offset = page_index * CACHE_PAGE_SIZE
        records = self._db.get_records(
            keyword=self._keyword,
            browser_type=self._browser_type,
            date_from=self._date_from,
            date_to=self._date_to,
            limit=CACHE_PAGE_SIZE,
            offset=offset,
            excluded_ids=self._hidden_ids,
            domain_ids=self._domain_ids,
            excludes=self._excludes,
            title_only=self._title_only,
            url_only=self._url_only,
            use_regex=False,  # Regex mode uses _regex_results directly, never this page cache path
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
            if defer_pixmaps:
                QTimer.singleShot(0, lambda r=records: self._favicon_manager.prefetch_pixmaps(r, size=16))
            else:
                self._favicon_manager.prefetch_pixmaps(records, size=16)

        return records

    # ── Favicon refresh ───────────────────────────────────────

    @Slot(object)
    def _on_favicons_updated(self, updated_domains: set) -> None:
        if not self._total_count or not updated_domains:
            return
        from src.services.extractors.favicon_extractor import extract_domain

        affected_rows: list[int] = []
        for page_index, records in self._page_cache.items():
            base = page_index * CACHE_PAGE_SIZE
            for local_idx, record in enumerate(records):
                if extract_domain(record.url) in updated_domains:
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
        self._initialized = True
        self.table_model.reload()
        self._refresh_browser_list()
        self._refresh_device_list()
        self._refresh_tag_list()
        self.model_ready.emit()
        self._load_top_domains_async()

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
def _format_time(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return str(ts)


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
