# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse
import webbrowser

from PySide6.QtCore import QDate, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionHeader,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_browser_icon, get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.theme_manager import ThemeManager
from src.viewmodels.history_viewmodel import HistoryViewModel

log = get_logger("view.history")

_DEBOUNCE_MS = 350


class _IconHeaderView(QHeaderView):
    """Custom header view with icon support and right-click menu for column configuration."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_column_menu)
        self._page = None  # Will be set by HistoryPage

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        if not self.model():
            super().paintSection(painter, rect, logical_index)
            return

        # Check if this column has an icon decoration
        icon: QIcon = self.model().headerData(logical_index, Qt.Horizontal, Qt.DecorationRole)

        if not isinstance(icon, QIcon) or icon.isNull():
            super().paintSection(painter, rect, logical_index)
            return

        # Has icon decoration - paint header background without text, then draw icon
        painter.save()
        opt = QStyleOptionHeader()
        self.initStyleOptionForIndex(opt, logical_index)
        opt.rect = rect
        opt.text = ""
        opt.icon = QIcon()
        self.style().drawControl(QStyle.CE_Header, opt, painter, self)
        painter.restore()

        # Draw the icon centered
        size = 16
        x = rect.x() + (rect.width() - size) // 2
        y = rect.y() + (rect.height() - size) // 2
        target = QRect(x, y, size, size)

        dpr = self.devicePixelRatioF()
        px = icon.pixmap(QSize(round(size * dpr), round(size * dpr)))
        px.setDevicePixelRatio(dpr)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, px)
        painter.restore()

    def _show_column_menu(self, pos):
        """Show column visibility configuration menu."""
        if self._page:
            self._page._show_column_config_menu(self.mapToGlobal(pos), self.logicalIndexAt(pos))


class SearchLineEdit(QLineEdit):
    """Custom search box with regex toggle and help icons."""

    regex_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._use_regex = False
        self.setClearButtonEnabled(True)
        self.setPlaceholderText(_("Search title or URL..."))

        # Regex action
        self._regex_act = self.addAction(get_icon("regex"), QLineEdit.TrailingPosition)
        self._regex_act.setCheckable(True)
        self._regex_act.setToolTip(_("Regex Mode"))
        self._regex_act.toggled.connect(self._toggle_regex)

        # Help action
        self._help_act = self.addAction(get_icon("help-circle"), QLineEdit.TrailingPosition)
        self._help_act.setToolTip(_("Search Syntax Help"))
        self._help_act.triggered.connect(self._show_help)

    def _toggle_regex(self, checked: bool):
        self._use_regex = checked
        if checked:
            self.setPlaceholderText(_("Regex: e.g. github\\.com.*release"))
            self.setProperty("regex", True)
        else:
            self.setPlaceholderText(_("Search title or URL..."))
            self.setProperty("regex", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.regex_toggled.emit(checked)

    def _show_help(self):
        msg = _(
            "<b>Advanced Search Syntax:</b><br><br>"
            "• <code>domain:example.com</code> - Filter by domain<br>"
            "• <code>after:2023-01-01</code> - Visit after date<br>"
            "• <code>before:2023-12-31</code> - Visit before date<br>"
            "• <code>-keyword</code> - Exclude term<br>"
            "• <code>title:keyword</code> - Search only titles<br>"
            "• <code>url:keyword</code> - Search only URLs<br>"
            "• <code>browser:chrome</code> - Filter by browser type<br><br>"
            "<i>Tip: You can combine these tokens with regular text.</i>"
        )
        QMessageBox.information(self, _("Search Help"), msg)

    @property
    def use_regex(self) -> bool:
        return self._use_regex


class HistoryPage(QWidget):
    # Signals to parent for blacklist / hide changes
    blacklist_domain_requested = Signal(str)
    hide_records_requested = Signal(list)  # list of record IDs
    delete_records_requested = Signal(list)  # list of record IDs

    def __init__(self, vm: HistoryViewModel, config=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._config = config

        self._current_widths = getattr(config.ui, "column_widths", {}) if config and hasattr(config, "ui") else {}

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._do_search)

        self._col_move_timer = QTimer(self)
        self._col_move_timer.setSingleShot(True)
        self._col_move_timer.timeout.connect(self._sync_column_order)

        self._col_resize_timer = QTimer(self)
        self._col_resize_timer.setSingleShot(True)
        self._col_resize_timer.timeout.connect(self._sync_ui_config)

        self._init_ui()
        self._connect_vm()
        self._setup_shortcuts()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 16)
        root.setSpacing(16)

        # ── Header ────────────────────────────────────────────
        hdr = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._title_lbl = QLabel(_("History"))
        self._title_lbl.setObjectName("page_title")
        self._subtitle_lbl = QLabel(_("Double-click any row to open the link in browser"))
        self._subtitle_lbl.setObjectName("page_subtitle")
        title_col.addWidget(self._title_lbl)
        title_col.addWidget(self._subtitle_lbl)

        self._count_label = QLabel(_("0 total"))
        self._count_label.setObjectName("muted")
        self._count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        hdr.addLayout(title_col)
        hdr.addStretch()
        hdr.addWidget(self._count_label)
        root.addLayout(hdr)

        # ── Filter bar ────
        filter_frame = QFrame()
        filter_frame.setObjectName("card")
        fl = QVBoxLayout(filter_frame)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(0)
        self._search = SearchLineEdit()
        self._search.setObjectName("search_box")
        self._search.textChanged.connect(lambda _: self._debounce.start(_DEBOUNCE_MS))
        self._search.regex_toggled.connect(self._do_search)
        row1.addWidget(self._search)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self._browser_combo = QComboBox()
        self._browser_combo.addItem(_("All Browsers"), "")
        self._browser_combo.setMinimumWidth(140)
        self._browser_combo.currentIndexChanged.connect(self._do_search)

        date_lbl = QLabel(_("Date:"))
        date_lbl.setObjectName("muted")

        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setDate(QDate(2020, 1, 1))
        self._date_from.dateChanged.connect(self._do_search)

        dash = QLabel("→")
        dash.setObjectName("muted")

        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._do_search)

        self._reset_btn = QPushButton(_("Reset"))
        self._reset_btn.setIcon(get_icon("refresh"))
        self._reset_btn.clicked.connect(self._reset_filters)

        row2.addWidget(self._browser_combo)
        row2.addSpacing(4)
        row2.addWidget(date_lbl)
        row2.addWidget(self._date_from)
        row2.addWidget(dash)
        row2.addWidget(self._date_to)
        row2.addStretch()
        row2.addWidget(self._reset_btn)

        fl.addLayout(row1)
        fl.addLayout(row2)
        root.addWidget(filter_frame)

        # ── Table ─────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._vm.table_model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Multi-select
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        # Custom header with right-click menu support
        hh = _IconHeaderView()
        hh._page = self  # Link back to page for column config menu
        self._table.setHorizontalHeader(hh)
        hh.setHighlightSections(False)
        hh.setStretchLastSection(False)

        hh.setSectionsMovable(True)
        hh.setDragEnabled(True)
        hh.setDragDropMode(QAbstractItemView.InternalMove)
        hh.sectionMoved.connect(lambda: self._col_move_timer.start(500))
        hh.sectionResized.connect(self._on_section_resized)

        # Apply dynamic column widths
        self._apply_column_widths()

        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self._table.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)

        # ── Bottom bar ────────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setContentsMargins(4, 0, 4, 0)
        self._status_label = QLabel(_("Ready"))
        self._status_label.setObjectName("muted")
        self._selection_label = QLabel("")
        self._selection_label.setObjectName("muted")

        self._export_btn = QPushButton(_("Export…"))
        self._export_btn.setIcon(get_icon("download"))
        self._export_btn.setToolTip(_("Export current filtered results to CSV / JSON / HTML"))
        self._export_btn.clicked.connect(self._open_export_dialog)

        bottom.addWidget(self._status_label)
        bottom.addStretch()
        bottom.addWidget(self._export_btn)
        bottom.addSpacing(8)
        bottom.addWidget(self._selection_label)
        root.addLayout(bottom)

        # Connect selection change
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _setup_shortcuts(self):
        """Register Ctrl+F (focus search) and Ctrl+R (sync now)."""
        search_sc = QShortcut(QKeySequence("Ctrl+F"), self)
        search_sc.activated.connect(self._focus_search)

        refresh_sc = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh_sc.activated.connect(self._trigger_sync)

        # Delete key to delete selected
        del_sc = QShortcut(QKeySequence(Qt.Key_Delete), self._table)
        del_sc.activated.connect(self._delete_selected)

    def _focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def filter_by_browser(self, browser_type: str):
        """从 DashboardPage 右键菜单跳转过来时，按浏览器类型过滤列表。"""
        for i in range(self._browser_combo.count()):
            if self._browser_combo.itemData(i) == browser_type:
                self._browser_combo.setCurrentIndex(i)
                return
        self._browser_combo.setCurrentIndex(0)
        self._do_search()

    def _trigger_sync(self):
        """Find main window and trigger sync."""
        w = self.window()
        if hasattr(w, "_vm") and hasattr(w._vm, "trigger_sync"):
            w._vm.trigger_sync()
            self._status_label.setText(_("Sync triggered..."))

    def _sync_column_order(self):
        """将拖拽后的视觉顺序同步到模型并保存，确保下次启动时顺序一致。"""
        hh = self._table.horizontalHeader()
        new_order = []

        for visual_idx in range(hh.count()):
            logical_idx = hh.logicalIndex(visual_idx)
            col_key = self._vm.table_model._col_to_key[logical_idx]
            new_order.append(col_key)

        current_order = self._vm.table_model.get_visible_columns()
        if new_order != current_order:
            hh.blockSignals(True)
            self._vm.table_model.set_visible_columns(new_order)
            for i in range(hh.count()):
                v_idx = hh.visualIndex(i)
                if v_idx != i:
                    hh.moveSection(v_idx, i)
            hh.blockSignals(False)
            self._sync_ui_config()

    def _connect_vm(self):
        self._vm.table_model.total_count_changed.connect(self._on_total_count_changed)
        self._vm.browser_list_changed.connect(self._update_browser_combo)
        self._vm.status_message.connect(self._status_label.setText)
        self._vm.table_model.columns_changed.connect(self._on_columns_changed)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换后只重绘可见视口，完全绕开 dataChanged 全表回调。"""
        self._table.viewport().update()

    def _on_columns_changed(self):
        QTimer.singleShot(0, self._apply_column_widths)

    def _on_section_resized(self, logical_index, old_size, new_size):
        col_key = self._vm.table_model._col_to_key.get(logical_index)
        if col_key and col_key != "browser":
            self._current_widths[col_key] = new_size
            self._col_resize_timer.start(500)

    def _sync_ui_config(self):
        visible_cols = self._vm.table_model.get_visible_columns()
        self._vm.ui_config_changed.emit(visible_cols, self._current_widths)

    def _apply_column_widths(self):
        hh = self._table.horizontalHeader()
        visible_cols = self._vm.table_model.get_visible_columns()

        hh.blockSignals(True)

        default_widths = {
            "title": 350,
            "url": 400,
            "domain": 160,
            "metadata": 250,
        }

        for idx, col_key in enumerate(visible_cols):
            if col_key == "browser":
                hh.setSectionResizeMode(idx, QHeaderView.Fixed)
                hh.resizeSection(idx, 48)
            else:
                hh.setSectionResizeMode(idx, QHeaderView.Interactive)
                w = self._current_widths.get(col_key, default_widths.get(col_key, 120))
                hh.resizeSection(idx, w)

        hh.setStretchLastSection(True)
        hh.blockSignals(False)

    def _auto_fit_column(self, logical_index: int):
        if logical_index < 0:
            return

        col_key = self._vm.table_model._col_to_key.get(logical_index)
        if not col_key or col_key == "browser":
            return

        fm = self._table.fontMetrics()

        header_text = self._vm.table_model.headerData(logical_index, Qt.Horizontal, Qt.DisplayRole) or ""
        max_w = fm.horizontalAdvance(header_text) + 40

        rows_to_scan = min(self._vm.table_model.rowCount(), 200)
        for row in range(rows_to_scan):
            idx = self._vm.table_model.index(row, logical_index)
            text = self._vm.table_model.data(idx, Qt.DisplayRole)
            if text:
                w = fm.horizontalAdvance(str(text)) + 24  # 预留左右边距
                max_w = max(max_w, w)

        max_w = min(max_w, 600)

        hh = self._table.horizontalHeader()
        hh.resizeSection(logical_index, max_w)

        self._current_widths[col_key] = max_w
        self._col_resize_timer.start(500)

    def _auto_fit_new_column(self, col_key: str):
        for logical_idx, key in self._vm.table_model._col_to_key.items():
            if key == col_key:
                self._auto_fit_column(logical_idx)
                break

    def _reset_table_view(self):
        default_cols = ["title", "url", "browser", "visit_time"]

        self._current_widths.clear()

        hh = self._table.horizontalHeader()
        hh.blockSignals(True)

        self._vm.table_model.set_visible_columns(default_cols)

        for i in range(hh.count()):
            v_idx = hh.visualIndex(i)
            if v_idx != i:
                hh.moveSection(v_idx, i)

        hh.blockSignals(False)

        self._apply_column_widths()
        self._sync_ui_config()

    def _show_column_config_menu(self, global_pos, clicked_logical_index):
        """Show column visibility and configuration menu."""
        if self._col_move_timer.isActive():
            self._col_move_timer.stop()
            self._sync_column_order()

        menu = QMenu(self)

        all_cols = self._vm.table_model.get_all_columns()
        visible_cols = self._vm.table_model.get_visible_columns()

        # ── 1. 列显示/隐藏开关 ──
        for col_key, col_def in all_cols.items():
            label = _(col_def.get("label_key", col_key.title()))
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col_key in visible_cols)
            action.setData(col_key)

            # 至少保留一列可见
            if len(visible_cols) == 1 and col_key in visible_cols:
                action.setEnabled(False)

        menu.addSeparator()

        # ── 2. 自动适应列宽 ──
        fit_this_act = menu.addAction(get_icon("maximize-2"), _("Auto-fit This Column"))
        if clicked_logical_index < 0:
            fit_this_act.setEnabled(False)

        fit_all_act = menu.addAction(get_icon("maximize"), _("Auto-fit All Columns"))

        menu.addSeparator()

        # ── 3. 恢复默认 ──
        reset_act = menu.addAction(get_icon("rotate-ccw"), _("Restore Default View"))

        # ── 处理用户点击 ──
        action = menu.exec(global_pos)
        if not action:
            return

        if action == fit_this_act:
            self._auto_fit_column(clicked_logical_index)
        elif action == fit_all_act:
            for idx in range(self._table.horizontalHeader().count()):
                self._auto_fit_column(self._table.horizontalHeader().logicalIndex(idx))
        elif action == reset_act:
            self._reset_table_view()
        else:
            # 处理列的显示/隐藏切换
            col_key = action.data()
            new_visible = visible_cols.copy()
            is_first_time_add = False

            if col_key in new_visible:
                new_visible.remove(col_key)
            else:
                new_visible.append(col_key)
                if col_key not in self._current_widths:
                    is_first_time_add = True

            self._vm.table_model.set_visible_columns(new_visible)
            self._sync_ui_config()

            if is_first_time_add:
                QTimer.singleShot(50, lambda k=col_key: self._auto_fit_new_column(k))

    # ── Selection helpers ─────────────────────────────────────

    def _get_selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self._table.selectedIndexes()})

    def _get_selected_records(self):
        rows = self._get_selected_rows()
        return [r for r in (self._vm.table_model.get_record_at(row) for row in rows) if r]

    def _on_selection_changed(self):
        rows = self._get_selected_rows()
        n = len(rows)
        if n > 0:
            self._selection_label.setText(_("{n} rows selected").format(n=n))
        else:
            self._selection_label.setText("")

    # ── Event handlers ────────────────────────────────────────

    def _do_search(self):
        raw_text = self._search.text().strip()
        use_regex = self._search.use_regex

        # Use DSL parser to extract special tokens
        query = parse_query(raw_text)

        # Merge DSL results with UI controls
        # UI controls (combo, date) are used if the token is NOT present in the DSL string
        browser = query.browser or self._browser_combo.currentData() or ""

        # Dates: prioritize DSL tokens
        if query.after:
            date_from = int(datetime(query.after.year, query.after.month, query.after.day, 0, 0, 0).timestamp())
        else:
            date_from = _qdate_to_unix(self._date_from.date(), is_start=True)

        if query.before:
            date_to = int(datetime(query.before.year, query.before.month, query.before.day, 23, 59, 59).timestamp())
        else:
            date_to = _qdate_to_unix(self._date_to.date(), is_start=False)

        # Resolve domain ids if domains are present
        domain_ids = []
        if query.domains:
            from src.services.local_db import LocalDatabase

            with self._vm._db._lock:
                conn = self._vm._db._ensure_conn()
                for d in query.domains:
                    domain_ids.extend(LocalDatabase._domain_ids_for(conn, d))

        self._vm.search(
            query.keyword,
            browser,
            date_from,
            date_to,
            domain_ids=list(set(domain_ids)) if domain_ids else None,
            excludes=query.excludes,
            title_only=query.title_only,
            url_only=query.url_only,
            use_regex=use_regex,
        )

    def _reset_filters(self):
        self._search.clear()
        self._search._regex_act.setChecked(False)
        self._browser_combo.setCurrentIndex(0)
        self._date_from.setDate(QDate(2020, 1, 1))
        self._date_to.setDate(QDate.currentDate())
        self._do_search()

    def _on_total_count_changed(self, count: int):
        self._count_label.setText(_("{total} records").format(total=f"{count:,}"))

    def _update_browser_combo(self, browser_types: list[str]):
        current = self._browser_combo.currentData()
        self._browser_combo.blockSignals(True)
        self._browser_combo.clear()
        self._browser_combo.addItem(_("All Browsers"), "")
        labels = {
            "chrome": "Chrome",
            "chrome_beta": "Chrome Beta",
            "chrome_canary": "Chrome Canary",
            "chrome_dev": "Chrome Dev",
            "chrome_for_testing": "Chrome for Testing",
            "edge": "Edge",
            "edge_beta": "Edge Beta",
            "edge_dev": "Edge Dev",
            "edge_canary": "Edge Canary",
            "brave": "Brave",
            "brave_beta": "Brave Beta",
            "brave_dev": "Brave Dev",
            "brave_nightly": "Brave Nightly",
            "firefox": "Firefox",
            "opera": "Opera",
            "opera_gx": "Opera GX",
            "vivaldi": "Vivaldi",
            "arc": "Arc",
            "safari": "Safari",
            "chromium": "Chromium",
            "yandex": "Yandex",
            "whale": "Whale",
            "waterfox": "Waterfox",
            "librewolf": "LibreWolf",
            "uc": "UC Browser",
            "coccoc": "Cốc Cốc",
            "seamonkey": "SeaMonkey",
        }
        for bt in browser_types:
            icon = get_browser_icon(bt, size=16)
            label = labels.get(bt, bt.title())
            self._browser_combo.addItem(icon, label, bt)
        for i in range(self._browser_combo.count()):
            if self._browser_combo.itemData(i) == current:
                self._browser_combo.setCurrentIndex(i)
                break
        self._browser_combo.blockSignals(False)

    def _on_double_click(self, index):
        record = self._vm.table_model.get_record_at(index.row())
        if record and record.url:
            try:
                webbrowser.open(record.url)
            except Exception as exc:
                log.warning("Failed to open URL: %s", exc)

    # ── Context menu ──────────────────────────────────────────

    def _show_context_menu(self, pos):
        index = self._table.indexAt(pos)
        selected_records = self._get_selected_records()
        if not selected_records:
            return

        multi = len(selected_records) > 1
        # Use clicked record as primary, or first selected
        primary = self._vm.table_model.get_record_at(index.row()) if index.isValid() else selected_records[0]
        if not primary:
            return

        # Extract domain from primary record and normalise it
        # (strip www. and port) so the blacklist stores canonical entries.
        try:
            netloc = urlparse(primary.url).netloc or ""
            # Strip port
            primary_domain = netloc.rsplit(":", 1)[0] if ":" in netloc and not netloc.startswith("[") else netloc
            # Strip leading www. for a canonical key
            if primary_domain.lower().startswith("www."):
                primary_domain = primary_domain[4:]
            primary_domain = primary_domain.lower()
        except Exception:
            primary_domain = ""

        menu = QMenu(self)

        # ── Open ──────────────────────────────────────────────
        if not multi:
            open_act = menu.addAction(get_icon("arrow-right"), _("Open in Browser"))
            open_act.setShortcut("Double-click")
        else:
            open_act = menu.addAction(
                get_icon("arrow-right"), _("Open All Selected in Browser ({n})").format(n=len(selected_records))
            )

        menu.addSeparator()

        # ── Copy submenu ──────────────────────────────────────
        copy_menu = QMenu(_("Copy"), menu)
        copy_menu.setIcon(get_icon("copy"))

        if not multi:
            copy_url_act = copy_menu.addAction(get_icon("link"), _("Copy URL"))
            copy_title_act = copy_menu.addAction(get_icon("copy"), _("Copy Title"))
            copy_both_act = copy_menu.addAction(get_icon("copy"), _("Copy Title + URL"))
        else:
            copy_url_act = copy_menu.addAction(
                get_icon("copy"), _("Copy All URLs ({n})").format(n=len(selected_records))
            )
            copy_title_act = None
            copy_both_act = None

        menu.addMenu(copy_menu)

        menu.addSeparator()

        # ── Actions submenu ───────────────────────────────────
        actions_menu = QMenu(_("Actions"), menu)
        actions_menu.setIcon(get_icon("settings"))

        # Delete
        if multi:
            delete_act = actions_menu.addAction(
                get_icon("trash"), _("Delete Selected ({n} records)").format(n=len(selected_records))
            )
            delete_act.setShortcut("Del")
        else:
            delete_act = actions_menu.addAction(get_icon("trash"), _("Delete This Record"))
            delete_act.setShortcut("Del")

        # Hide
        if multi:
            hide_act = actions_menu.addAction(
                get_icon("eye"), _("Hide Selected ({n} records)").format(n=len(selected_records))
            )
        else:
            hide_act = actions_menu.addAction(get_icon("eye"), _("Hide This Record"))

        # Blacklist domain
        if primary_domain:
            actions_menu.addSeparator()
            blacklist_act = actions_menu.addAction(
                get_icon("shield"), _("Blacklist Domain: {domain}").format(domain=primary_domain)
            )
            blacklist_act.setToolTip(_("Deletes all records from this domain and adds it to blacklist"))
        else:
            blacklist_act = None

        menu.addMenu(actions_menu)

        # ── Search domain (top-level, single select only) ─────
        menu.addSeparator()

        if primary_domain and not multi:
            search_domain_act = menu.addAction(get_icon("search"), _("Search: {domain}").format(domain=primary_domain))
        else:
            search_domain_act = None

        action = menu.exec(QCursor.pos())

        ids = [r.id for r in selected_records if r.id is not None]

        if action == open_act:
            for r in selected_records:
                if r.url:
                    try:
                        webbrowser.open(r.url)
                    except Exception:
                        pass

        elif action == copy_url_act:
            if multi:
                QApplication.clipboard().setText("\n".join(r.url for r in selected_records))
            else:
                QApplication.clipboard().setText(primary.url)

        elif copy_title_act and action == copy_title_act:
            QApplication.clipboard().setText(primary.title or primary.url)

        elif copy_both_act and action == copy_both_act:
            QApplication.clipboard().setText(f"{primary.title or primary.url}\n{primary.url}")

        elif action == delete_act:
            self._confirm_delete(selected_records, ids)

        elif action == hide_act:
            self._hide_records(ids)

        elif blacklist_act and action == blacklist_act:
            self._blacklist_domain(primary_domain)

        elif search_domain_act and action == search_domain_act:
            self._search.setText(primary_domain)
            self._focus_search()

    def _confirm_delete(self, records, ids):
        n = len(records)
        reply = QMessageBox.warning(
            self,
            _("Delete Records"),
            _("Delete {n} record(s)? This cannot be undone.").format(n=n),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.delete_records_requested.emit(ids)

    def _hide_records(self, ids: list[int]):
        self.hide_records_requested.emit(ids)
        self._status_label.setText(_("Hidden {n} record(s). Manage in Settings → Privacy.").format(n=len(ids)))

    def _blacklist_domain(self, domain: str):
        reply = QMessageBox.warning(
            self,
            _("Blacklist Domain"),
            _("This will:\n• Delete ALL records from '{domain}'\n• Never sync this domain again\n\nContinue?").format(
                domain=domain
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.blacklist_domain_requested.emit(domain)

    def _delete_selected(self):
        records = self._get_selected_records()
        if records:
            ids = [r.id for r in records if r.id is not None]
            self._confirm_delete(records, ids)

    def refresh(self):
        self._vm.refresh()

    def _open_export_dialog(self):
        """Open the export dialog pre-filled with the current filter state (Entry A)."""
        from pathlib import Path

        from src.services.exporter import ResolvedExportParams
        from src.views.export_dialog import ExportDialog

        vm = self._vm.table_model  # HistoryTableModel

        # Retrieve favicon_cache from the FaviconManager the viewmodel holds
        favicon_cache = None
        try:
            favicon_cache = self._vm._favicon_manager._cache
        except AttributeError:
            pass

        params = ResolvedExportParams(
            output_path=Path(),  # user will choose inside dialog
            fmt="csv",
            columns=[],
            embed_icons=False,
            keyword=vm._keyword,
            browser_type=vm._browser_type,
            date_from=vm._date_from,
            date_to=vm._date_to,
            domain_ids=vm._domain_ids,
            excludes=vm._excludes,
            title_only=vm._title_only,
            url_only=vm._url_only,
            use_regex=vm._use_regex,
        )
        dlg = ExportDialog(
            db=self._vm._db,
            favicon_cache=favicon_cache,
            resolved_params=params,
            parent=self,
        )
        dlg.exec()


def _qdate_to_unix(qdate: QDate, is_start: bool) -> int | None:
    if not qdate.isValid():
        return None
    py_date = date(qdate.year(), qdate.month(), qdate.day())
    if is_start:
        return int(datetime(py_date.year, py_date.month, py_date.day, 0, 0, 0).timestamp())
    return int(datetime(py_date.year, py_date.month, py_date.day, 23, 59, 59).timestamp())
