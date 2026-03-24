# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)

from src.models.history_record import HistoryRecord
from src.services.favicon_manager import FaviconManager
from src.services.local_db import LocalDatabase
from src.utils.i18n import _
from src.utils.icon_helper import get_browser_icon, get_browser_pixmap
from src.utils.logger import get_logger

log = get_logger("viewmodel.history")

# 每次从数据库预取的页面大小
PAGE_SIZE = 200
CACHE_PAGE_SIZE = PAGE_SIZE
# 最多在内存中保留多少页
MAX_CACHED_PAGES = 10

# Column indices
COL_TITLE = 0
COL_URL = 1
COL_BROWSER = 2
COL_TIME = 3
COLUMN_COUNT = 4


class HistoryTableModel(QAbstractTableModel):
    """
    虚拟化历史记录表格模型（Virtual Scrolling）。
    """

    total_count_changed = Signal(int)

    def __init__(self, db: LocalDatabase, favicon_manager: FaviconManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._favicon_manager = favicon_manager

        # 过滤参数
        self._keyword = ""
        self._browser_type = ""
        self._date_from: int | None = None
        self._date_to: int | None = None
        self._hidden_ids: set[int] = set()

        # 虚拟化状态
        self._total_count = 0
        self._page_cache: dict[int, list[HistoryRecord]] = {}
        self._page_lru: OrderedDict[int, None] = OrderedDict()

        self._favicon_manager.favicons_updated.connect(self._on_favicons_updated)

    # ── Public API ───────────────────────────────────────────

    def set_hidden_ids(self, ids: set[int]) -> None:
        self._hidden_ids = ids
        self.reload()

    # ── QAbstractTableModel interface ────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return self._total_count

    def columnCount(self, parent=QModelIndex()) -> int:
        return COLUMN_COUNT

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                labels = [_("Page Title"), _("URL"), "", _("Visit Time")]
                return labels[section]
            if role == Qt.DecorationRole and section == COL_BROWSER:
                return get_browser_icon("web", size=16)
            if role == Qt.ToolTipRole and section == COL_BROWSER:
                return _("Browser")
            if role == Qt.TextAlignmentRole and section == COL_BROWSER:
                return Qt.AlignCenter
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role not in (
            Qt.DisplayRole,
            Qt.DecorationRole,
            Qt.ToolTipRole,
            Qt.UserRole,
            Qt.TextAlignmentRole,
        ):
            return None

        row = index.row()
        record = self._get_record_at(row)
        if record is None:
            return None

        col = index.column()

        if role == Qt.DisplayRole:
            if col == COL_TITLE:
                return record.title or record.url
            if col == COL_URL:
                return record.url
            if col == COL_BROWSER:
                return ""
            if col == COL_TIME:
                return _format_time(record.visit_time)

        elif role == Qt.DecorationRole:
            if col == COL_TITLE:
                return self._favicon_manager.get_pixmap(record.url, size=16)
            if col == COL_BROWSER:
                return get_browser_pixmap(record.browser_type or "web", size=20)

        elif role == Qt.ToolTipRole:
            if col == COL_TITLE:
                return record.metadata or record.title
            if col == COL_URL:
                return record.url
            if col == COL_BROWSER:
                return _browser_display_name(record.browser_type)

        elif role == Qt.UserRole:
            return record

        elif role == Qt.TextAlignmentRole:
            if col == COL_TIME:
                return Qt.AlignCenter

        return None

    # ── Data loading ─────────────────────────────────────────

    def set_filter(
        self,
        keyword: str = "",
        browser_type: str = "",
        date_from: int | None = None,
        date_to: int | None = None,
    ):
        self._keyword = keyword
        self._browser_type = browser_type
        self._date_from = date_from
        self._date_to = date_to
        self.reload()

    def reload(self):
        """重置缓存并重新查询总数，触发视图完整刷新。"""
        self._page_cache.clear()
        self._page_lru.clear()

        new_count = self._db.get_filtered_count(
            keyword=self._keyword,
            browser_type=self._browser_type,
            date_from=self._date_from,
            date_to=self._date_to,
            excluded_ids=self._hidden_ids,
        )

        self.beginResetModel()
        self._total_count = new_count
        self.endResetModel()

        self.total_count_changed.emit(self._total_count)

        if self._total_count > 0:
            self._fetch_page(0, defer_pixmaps=True)

    def load_more(self) -> bool:
        """虚拟化模式下无需手动 load_more，保留接口兼容性。"""
        return False

    def refresh_icons(self, view=None) -> None:
        """主题切换后仅失效图标列，不触发 beginResetModel。

        传入 QTableView 时只通知当前可见行范围；未传入时限制在前 200 行。
        禁止对全表发射 dataChanged，否则 Qt 会对数十万行逐行回调 data()。
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

        self.dataChanged.emit(
            self.index(first_row, COL_TITLE),
            self.index(last_row, COL_BROWSER),
            [Qt.DecorationRole],
        )

    @property
    def total_count(self) -> int:
        return self._total_count

    def get_record_at(self, row: int) -> HistoryRecord | None:
        return self._get_record_at(row)

    # ── Internal: virtual page cache ─────────────────────────

    def _get_record_at(self, row: int) -> HistoryRecord | None:
        if row < 0 or row >= self._total_count:
            return None
        page_index = row // CACHE_PAGE_SIZE
        page = self._get_or_fetch_page(page_index)
        local_row = row % CACHE_PAGE_SIZE
        if local_row < len(page):
            return page[local_row]
        return None

    def _get_or_fetch_page(self, page_index: int) -> list[HistoryRecord]:
        if page_index in self._page_cache:
            # O(1) LRU 更新：移到末尾表示最近使用
            self._page_lru.move_to_end(page_index)
            return self._page_cache[page_index]
        return self._fetch_page(page_index)

    def _fetch_page(self, page_index: int, defer_pixmaps: bool = False) -> list[HistoryRecord]:
        """
        从数据库拉取一页，写入 LRU 缓存。
        """
        offset = page_index * CACHE_PAGE_SIZE
        records = self._db.get_records(
            keyword=self._keyword,
            browser_type=self._browser_type,
            date_from=self._date_from,
            date_to=self._date_to,
            limit=CACHE_PAGE_SIZE,
            offset=offset,
            excluded_ids=self._hidden_ids,
        )

        self._page_cache[page_index] = records
        # LRU 写入
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
        self.dataChanged.emit(
            self.index(first_row, COL_TITLE),
            self.index(last_row, COL_TITLE),
            [Qt.DecorationRole],
        )


# ── ViewModel ────────────────────────────────────────────────


class HistoryViewModel(QObject):
    """Mediates between HistoryPage view and HistoryTableModel."""

    model_ready = Signal()
    browser_list_changed = Signal(list)
    status_message = Signal(str)

    def __init__(self, db: LocalDatabase, favicon_manager: FaviconManager, parent=None):
        super().__init__(parent)
        self._db = db
        self._initialized = False
        self.table_model = HistoryTableModel(db, favicon_manager)

    def initialize(self):
        self._initialized = True
        self.table_model.reload()
        self._refresh_browser_list()
        self.model_ready.emit()

    def search(self, keyword: str, browser_type: str, date_from: int | None, date_to: int | None):
        self.table_model.set_filter(keyword, browser_type, date_from, date_to)
        count = self.table_model.total_count
        self.status_message.emit(_("{total} records").format(total=f"{count:,}"))

    def load_more(self) -> bool:
        return False

    def refresh(self):
        self.table_model.reload()
        self._refresh_browser_list()

    def set_hidden_ids(self, ids: set[int]) -> None:
        if self._initialized:
            self.table_model.set_hidden_ids(ids)
        else:
            self.table_model._hidden_ids = ids

    def _refresh_browser_list(self):
        self.browser_list_changed.emit(self._db.get_browser_types())


# ── Utilities ────────────────────────────────────────────────

_BROWSER_NAMES: dict[str, str] = {
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "brave": "Brave",
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
