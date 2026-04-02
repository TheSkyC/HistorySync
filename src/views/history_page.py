# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from urllib.parse import urlparse
import webbrowser

from PySide6.QtCore import QDate, QItemSelectionModel, QRect, QSize, Qt, QTimer, Signal
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
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_browser_icon, get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.theme_manager import ThemeManager
from src.viewmodels.history_viewmodel import ANNOTATION_ROLE, BOOKMARK_ROLE, HistoryViewModel
from src.views.annotation_dialog import AnnotationDialog
from src.views.search_autocomplete import SmartSearchLineEdit

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


class BookmarkBadgeDelegate(QStyledItemDelegate):
    """Custom delegate that renders favicon + badge icons for bookmarks/annotations."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model
        self._badge_size = 14  # Increased from 12 to 14 for better visibility
        self._badge_spacing = 3

    def _colorize_icon(self, icon: QIcon, color, size: int):
        """Create a colored version of an icon."""
        from PySide6.QtGui import QColor, QPainter, QPixmap

        if icon.isNull():
            return QPixmap()

        # Get the original pixmap
        pixmap = icon.pixmap(size, size)
        if pixmap.isNull():
            return pixmap

        # Create a new pixmap with the same size
        colored = QPixmap(pixmap.size())
        colored.fill(Qt.transparent)

        # Paint the color with the original alpha mask
        painter = QPainter(colored)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(colored.rect(), QColor(color))
        painter.end()

        return colored

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Draw favicon and badge icons if present."""
        from PySide6.QtGui import QPixmap

        # Let the default delegate draw the background and selection
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""  # We'll draw text manually
        opt.icon = QIcon()  # We'll draw icon manually
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)

        # Get data
        display_text = index.data(Qt.DisplayRole) or ""
        favicon = index.data(Qt.DecorationRole)
        has_bookmark = index.data(BOOKMARK_ROLE) or False
        has_annotation = index.data(ANNOTATION_ROLE) or False

        painter.save()

        # Calculate layout
        rect = option.rect
        x = rect.x() + 4
        y = rect.y() + (rect.height() - 16) // 2

        # Draw favicon (can be QIcon or QPixmap)
        if isinstance(favicon, QPixmap) and not favicon.isNull():
            painter.drawPixmap(x, y, 16, 16, favicon)
        elif isinstance(favicon, QIcon) and not favicon.isNull():
            favicon.paint(painter, x, y, 16, 16)
        x += 16 + 4

        # Draw badge icons
        if has_bookmark:
            bookmark_icon = get_icon("bookmark")
            if not bookmark_icon.isNull():
                badge_y = y + (16 - self._badge_size) // 2
                # Colorize bookmark icon in blue
                colored_pixmap = self._colorize_icon(bookmark_icon, "#3B82F6", self._badge_size)
                if not colored_pixmap.isNull():
                    painter.drawPixmap(x, badge_y, colored_pixmap)
            x += self._badge_size + self._badge_spacing

        if has_annotation:
            annotation_icon = get_icon("edit-2")
            if not annotation_icon.isNull():
                badge_y = y + (16 - self._badge_size) // 2
                # Colorize annotation icon in green
                colored_pixmap = self._colorize_icon(annotation_icon, "#10B981", self._badge_size)
                if not colored_pixmap.isNull():
                    painter.drawPixmap(x, badge_y, colored_pixmap)
            x += self._badge_size + self._badge_spacing

        # Draw text
        text_rect = QRect(x + 4, rect.y(), rect.width() - (x - rect.x()) - 4, rect.height())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, display_text)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        """Handle mouse clicks on badge icons."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent

        if not isinstance(event, QMouseEvent):
            return super().editorEvent(event, model, option, index)

        if event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            return super().editorEvent(event, model, option, index)

        # Calculate badge positions
        rect = option.rect
        x = rect.x() + 4 + 16 + 4  # favicon + spacing
        y = rect.y() + (rect.height() - self._badge_size) // 2

        has_bookmark = index.data(BOOKMARK_ROLE) or False
        has_annotation = index.data(ANNOTATION_ROLE) or False

        click_pos = event.pos()

        # Check bookmark badge click
        if has_bookmark:
            bookmark_rect = QRect(x, y, self._badge_size, self._badge_size)
            if bookmark_rect.contains(click_pos) and event.type() == QEvent.MouseButtonRelease:
                self._handle_bookmark_click(index)
                return True
            x += self._badge_size + self._badge_spacing

        # Check annotation badge click
        if has_annotation:
            annotation_rect = QRect(x, y, self._badge_size, self._badge_size)
            if annotation_rect.contains(click_pos) and event.type() == QEvent.MouseButtonRelease:
                self._handle_annotation_click(index)
                return True

        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):
        """Show tooltips when hovering over badges."""
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QToolTip

        if event.type() != QEvent.ToolTip:
            return super().helpEvent(event, view, option, index)

        # Calculate badge positions
        rect = option.rect
        x = rect.x() + 4 + 16 + 4
        y = rect.y() + (rect.height() - self._badge_size) // 2

        has_bookmark = index.data(BOOKMARK_ROLE) or False
        has_annotation = index.data(ANNOTATION_ROLE) or False

        hover_pos = event.pos()

        # Check bookmark badge hover
        if has_bookmark:
            bookmark_rect = QRect(x, y, self._badge_size, self._badge_size)
            if bookmark_rect.contains(hover_pos):
                QToolTip.showText(event.globalPos(), _("Bookmarked (click to edit)"), view)
                return True
            x += self._badge_size + self._badge_spacing

        # Check annotation badge hover
        if has_annotation:
            annotation_rect = QRect(x, y, self._badge_size, self._badge_size)
            if annotation_rect.contains(hover_pos):
                record = index.data(Qt.UserRole)
                if record:
                    # Get annotation from DB to show preview
                    page = self.parent()
                    if hasattr(page, "_vm"):
                        ann = page._vm._db.get_annotation(record.url)
                        if ann and ann.note:
                            preview = ann.note[:100] + "..." if len(ann.note) > 100 else ann.note
                            QToolTip.showText(event.globalPos(), _("Note: {note}").format(note=preview), view)
                            return True
                QToolTip.showText(event.globalPos(), _("Has note (click to edit)"), view)
                return True

        return super().helpEvent(event, view, option, index)

    def _handle_bookmark_click(self, index):
        """Open bookmark edit dialog."""
        page = self.parent()
        if not hasattr(page, "_vm"):
            return

        record = index.data(Qt.UserRole)
        if not record:
            return

        # Toggle bookmark (same as context menu action)
        db = page._vm._db
        if db.is_bookmarked(record.url):
            db.remove_bookmark(record.url)
        else:
            db.add_bookmark(record.url, record.title or record.url, [], history_id=record.id)

        # Refresh badge cache
        page._vm.table_model.invalidate_badge_cache(page._table)

    def _handle_annotation_click(self, index):
        """Open annotation edit dialog."""
        page = self.parent()
        if not hasattr(page, "_vm"):
            return

        record = index.data(Qt.UserRole)
        if not record:
            return

        # Open annotation dialog (same as context menu action)
        page._edit_annotation(record)


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
        self._search = SmartSearchLineEdit()
        self._search.setObjectName("search_box")
        self._search.textChanged.connect(lambda _: self._debounce.start(_DEBOUNCE_MS))
        self._search.regex_toggled.connect(self._do_search)
        self._search.search_submitted.connect(self._do_search)
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

        # Set badge delegate for title column
        self._setup_badge_delegate()

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

    def _setup_badge_delegate(self):
        """Set up badge delegate for title column. Safe to call multiple times."""
        # Clear existing delegates to avoid stale bindings
        for col_idx in range(self._table.model().columnCount()):
            self._table.setItemDelegateForColumn(col_idx, None)

        # Bind delegate to current title column logical index
        title_col_idx = self._vm.table_model._key_to_col.get("title")
        if title_col_idx is not None:
            badge_delegate = BookmarkBadgeDelegate(self._vm.table_model, self)
            self._table.setItemDelegateForColumn(title_col_idx, badge_delegate)

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

    def filter_by_url(self, url: str):
        """When navigating from 'Locate in History' in the bookmarks page, clear filters and scroll to the row containing the URL."""
        # Step 1: clear all filters so the full list is shown
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._browser_combo.blockSignals(True)
        self._browser_combo.setCurrentIndex(0)
        self._browser_combo.blockSignals(False)
        self._date_from.blockSignals(True)
        self._date_from.setDate(QDate(2020, 1, 1))
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.blockSignals(False)
        self._do_search()

        # Step 2: find the row offset for this URL in the unfiltered list
        row = self._vm._db.get_row_offset_for_url(url)
        if row < 0:
            # URL not found - fall back to a url: search so the user sees something
            self._search.setText(f"url:{url}")
            self._focus_search()
            self._do_search()
            return

        # Step 3: scroll to and select the row
        model = self._vm.table_model
        idx = model.index(row, 0)
        self._table.selectionModel().clearSelection()
        self._table.selectionModel().select(
            idx,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        self._table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._focus_search()

    def filter_by_browser(self, browser_type: str):
        """When navigating from the DashboardPage context menu, filter the list by browser type."""
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
        """Synchronize the visual column order after dragging to the model and save it, ensuring consistency on the next startup."""
        hh = self._table.horizontalHeader()
        new_order = []

        for visual_idx in range(hh.count()):
            logical_idx = hh.logicalIndex(visual_idx)
            col_key = self._vm.table_model._col_to_key[logical_idx]
            new_order.append(col_key)

        current_order = self._vm.table_model.get_visible_columns()
        if new_order != current_order:
            with self._batch_header_update() as hh:
                self._vm.table_model.set_visible_columns(new_order)
                for i in range(hh.count()):
                    v_idx = hh.visualIndex(i)
                    if v_idx != i:
                        hh.moveSection(v_idx, i)
            self._sync_ui_config()

    def _connect_vm(self):
        self._vm.table_model.total_count_changed.connect(self._on_total_count_changed)
        self._vm.browser_list_changed.connect(self._update_browser_combo)
        self._vm.status_message.connect(self._status_label.setText)
        self._vm.table_model.columns_changed.connect(self._on_columns_changed)
        self._vm.top_domains_loaded.connect(self._search.set_top_domains)
        self._vm.browser_list_changed.connect(self._search.set_available_browsers)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # Trigger regex incremental loading when scrolling to the bottom
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_check_load_more)

    def _on_scroll_check_load_more(self, value: int):
        """Trigger regex incremental loading when the scrollbar approaches the bottom."""
        if not self._vm.table_model.can_load_more:
            return
        sb = self._table.verticalScrollBar()
        # Trigger when less than 3 row heights away from the bottom
        row_h = max(self._table.verticalHeader().defaultSectionSize(), 1)
        threshold = sb.maximum() - row_h * 3
        if value >= threshold:
            self._vm.load_more()

    def _on_theme_changed(self, _theme: str) -> None:
        """Only repaint the visible viewport on theme change, bypassing full table dataChanged callbacks."""
        self._table.viewport().update()

    def _on_columns_changed(self):
        QTimer.singleShot(0, self._apply_column_widths)
        QTimer.singleShot(0, self._setup_badge_delegate)  # Rebind delegate after column order changes

    def _on_section_resized(self, logical_index, old_size, new_size):
        col_key = self._vm.table_model._col_to_key.get(logical_index)
        if col_key and col_key != "browser":
            self._current_widths[col_key] = new_size
            self._col_resize_timer.start(500)

    @contextmanager
    def _batch_header_update(self):
        """Block signals during batch header modifications, and force a geometry update for scrollbars afterwards."""
        hh = self._table.horizontalHeader()
        hh.blockSignals(True)
        try:
            yield hh
        finally:
            hh.blockSignals(False)
            self._table.updateGeometries()

    def _sync_ui_config(self):
        visible_cols = self._vm.table_model.get_visible_columns()
        self._vm.ui_config_changed.emit(visible_cols, self._current_widths)

    def _apply_column_widths(self):
        visible_cols = self._vm.table_model.get_visible_columns()
        default_widths = {
            "title": 360,
            "url": 440,
            "domain": 160,
            "metadata": 250,
        }

        with self._batch_header_update() as hh:
            for idx, col_key in enumerate(visible_cols):
                if col_key == "browser":
                    hh.setSectionResizeMode(idx, QHeaderView.Fixed)
                    hh.resizeSection(idx, 48)
                else:
                    hh.setSectionResizeMode(idx, QHeaderView.Interactive)
                    w = self._current_widths.get(col_key, default_widths.get(col_key, 120))
                    hh.resizeSection(idx, w)
            hh.setStretchLastSection(True)

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
                w = fm.horizontalAdvance(str(text)) + 24  # Reserve left and right margins
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

        with self._batch_header_update() as hh:
            self._vm.table_model.set_visible_columns(default_cols)
            for i in range(hh.count()):
                v_idx = hh.visualIndex(i)
                if v_idx != i:
                    hh.moveSection(v_idx, i)

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

        # ── 1. Column visibility toggles ──
        for col_key, col_def in all_cols.items():
            label = _(col_def.get("label_key", col_key.title()))
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col_key in visible_cols)
            action.setData(col_key)

            # Keep at least one column visible
            if len(visible_cols) == 1 and col_key in visible_cols:
                action.setEnabled(False)

        menu.addSeparator()

        # ── 2. Auto-fit column widths ──
        fit_this_act = menu.addAction(get_icon("maximize-2"), _("Auto-fit This Column"))
        if clicked_logical_index < 0:
            fit_this_act.setEnabled(False)

        fit_all_act = menu.addAction(get_icon("maximize"), _("Auto-fit All Columns"))

        menu.addSeparator()

        # ── 3. Restore defaults ──
        reset_act = menu.addAction(get_icon("rotate-ccw"), _("Restore Default View"))

        # ── Handle user clicks ──
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
            # Handle column visibility toggling
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
        return sorted([idx.row() for idx in self._table.selectionModel().selectedRows()])

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
            domain_ids = self._vm.resolve_domain_ids(query.domains)

        # Resolve device ids if device token is present
        device_ids = []
        if query.device:
            device_ids = self._vm.resolve_device_ids(query.device)

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
            bookmarked_only=query.bookmarked_only,
            has_annotation=query.has_annotation,
            bookmark_tag=query.bookmark_tag,
            device_ids=list(set(device_ids)) if device_ids else None,
        )

    def _reset_filters(self):
        self._search.clear()
        self._search._btn_regex.setChecked(False)
        self._browser_combo.setCurrentIndex(0)
        self._date_from.setDate(QDate(2020, 1, 1))
        self._date_to.setDate(QDate.currentDate())
        self._do_search()

    def _on_total_count_changed(self, count: int, has_more: bool = False):
        if has_more:
            self._count_label.setText(_("{total}+ records").format(total=f"{count:,}"))
        else:
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
            open_act = menu.addAction(get_icon("corner-up-right"), _("Open in Browser"))
            open_act.setShortcut("Double-click")
        else:
            open_act = menu.addAction(
                get_icon("corner-up-right"), _("Open All Selected in Browser ({n})").format(n=len(selected_records))
            )

        menu.addSeparator()

        # ── Bookmark ───────────────────────────────────────────
        if not multi:
            _db = self._vm._db
            _is_bm = _db.is_bookmarked(primary.url)
            if _is_bm:
                bookmark_act = menu.addAction(get_icon("bookmark"), _("Remove Bookmark"))
            else:
                bookmark_act = menu.addAction(get_icon("bookmark"), _("Add Bookmark"))
        else:
            bookmark_act = menu.addAction(
                get_icon("bookmark"), _("Bookmark All Selected ({n})").format(n=len(selected_records))
            )

        # ── Annotation ─────────────────────────────────────────
        if not multi:
            _ann = self._vm._db.get_annotation(primary.url)
            if _ann and _ann.note:
                annotation_act = menu.addAction(get_icon("edit-2"), _("Edit Note…"))
            else:
                annotation_act = menu.addAction(get_icon("edit-2"), _("Add Note…"))
        else:
            annotation_act = None

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

        elif action == bookmark_act:
            self._toggle_bookmark(selected_records, primary, multi)

        elif annotation_act and action == annotation_act:
            self._edit_annotation(primary)

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

    def _toggle_bookmark(self, selected_records, primary, multi):
        db = self._vm._db
        if multi:
            for r in selected_records:
                if not db.is_bookmarked(r.url):
                    db.add_bookmark(r.url, r.title or r.url, [], history_id=r.id)
        elif db.is_bookmarked(primary.url):
            db.remove_bookmark(primary.url)
        else:
            db.add_bookmark(primary.url, primary.title or primary.url, [], history_id=primary.id)

        # Refresh badge cache to show/hide bookmark icons
        self._vm.table_model.invalidate_badge_cache(self._table)

    def _edit_annotation(self, record):
        db = self._vm._db
        existing = db.get_annotation(record.url)
        dlg = AnnotationDialog(record.url, record.title or record.url, existing, parent=self)
        if dlg.exec():
            note = dlg.get_note()
            if note.strip():
                db.upsert_annotation(record.url, note, history_id=record.id)
            else:
                db.delete_annotation(record.url)

            # Refresh badge cache to show/hide annotation icons
            self._vm.table_model.invalidate_badge_cache(self._table)

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
            bookmarked_only=vm._bookmarked_only,
            has_annotation=vm._has_annotation,
            bookmark_tag=vm._bookmark_tag,
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
