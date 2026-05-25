# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Bookmark page rewritten on top of QListView + QStyledItemDelegate.

Architecture overview
---------------------

Old (legacy):
    QScrollArea + N QFrame "cards", each ~15 widgets, rebuilt on every page
    show / filter change / mutation.  Memory and paint cost O(N).

New (this module):
    QListView (virtual scroll) + BookmarkDelegate (paints with QPainter)
    + BookmarkListModel (keyset-paginated QAbstractListModel).  Memory and
    paint cost O(visible rows) regardless of how many bookmarks exist.

Public surface preserved
------------------------

The class signature, signals, and public methods stay 1:1 with the legacy
page so MainWindow doesn't need any changes that depend on internals:

    Signals:
        navigate_to_history(BookmarkRecord, hidden_mode: bool)
        bookmark_changed()                 -- emitted on local mutation
    Methods:
        refresh()
        set_hidden_mode(enabled)
        leave_hidden_mode()
        apply_keybindings()
        _focus_search()                    -- called by MainWindow
        apply_external_bookmark_change()   -- NEW: called by MainWindow when
                                              the change came from another page
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.models.history_record import BookmarkRecord
from src.services.local_db import LocalDatabase
from src.services.local_db.bookmarks import BookmarkPageFilter
from src.utils.dialog_utils import exec_centered
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.styled_menu import StyledMenu
from src.utils.theme_manager import ThemeManager
from src.views.annotation_dialog import AnnotationDialog
from src.views.bookmark_delegate import BookmarkDelegate
from src.views.bookmark_list_model import BookmarkListModel

log = get_logger("view.bookmarks")


# ── Internal QListView subclass with per-card keyboard / hover handling ──────


class _BookmarkListView(QListView):
    """QListView wired up for bookmark-card UX.

    Adds:
    - per-card keyboard shortcuts (Enter/Del/Ctrl+C/Ctrl+N/Ctrl+L) that
      translate to the same action vocabulary as the delegate's button
      clicks, so the page can route both via a single slot.
    - mouse-hover tracking on the viewport that updates the delegate's
      hovered-button state, so individual buttons can highlight.
    """

    # Same vocabulary as BookmarkDelegate.action_requested.
    action_triggered = Signal(str, object)  # (action, BookmarkRecord)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._delegate: BookmarkDelegate | None = None

    def set_delegate(self, delegate: BookmarkDelegate) -> None:
        self._delegate = delegate

    # ── Hover ─────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._delegate is None:
            return
        idx = self.indexAt(event.position().toPoint() if hasattr(event, "position") else event.pos())
        row = idx.row() if idx.isValid() else -1
        button_index = -1
        if idx.isValid():
            bm = idx.data(BookmarkListModel.BookmarkRole)
            ann = idx.data(BookmarkListModel.AnnotationRole)
            if bm is not None:
                from PySide6.QtWidgets import QStyleOptionViewItem

                opt = QStyleOptionViewItem()
                opt.initFrom(self)
                opt.rect = self.visualRect(idx)
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                layout = self._delegate._compute_layout(opt.rect, opt, bm, ann)
                for i, br in enumerate(layout.button_rects):
                    if br.contains(pos):
                        button_index = i
                        break
        self._delegate.set_hover(row, button_index)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._delegate is not None:
            self._delegate.set_hover(-1, -1)

    # ── Keyboard shortcuts on the focused row ─────────────

    def keyPressEvent(self, event):
        idx = self.currentIndex()
        if idx.isValid():
            bm = idx.data(BookmarkListModel.BookmarkRole)
            if bm is not None:
                key = event.key()
                mods = event.modifiers()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self.action_triggered.emit("open", bm)
                    event.accept()
                    return
                if key == Qt.Key_Delete:
                    self.action_triggered.emit("remove", bm)
                    event.accept()
                    return
                if key == Qt.Key_C and mods & Qt.ControlModifier:
                    self.action_triggered.emit("copy_url", bm)
                    event.accept()
                    return
                if key == Qt.Key_N and mods & Qt.ControlModifier:
                    self.action_triggered.emit("edit_note", bm)
                    event.accept()
                    return
                if key == Qt.Key_L and mods & Qt.ControlModifier:
                    self.action_triggered.emit("locate", bm)
                    event.accept()
                    return
        super().keyPressEvent(event)


# ── BookmarksPage ────────────────────────────────────────────────────────────


class BookmarksPage(QWidget):
    """Bookmark management page using virtual-scroll QListView + delegate.

    Compared to the legacy QScrollArea+QFrame implementation, this version:
    - Allocates O(visible rows) widgets instead of O(N) cards.
    - Pushes ALL filtering (tag / keyword / has_note / hidden_mode / dates /
      domain / excludes) into SQL via BookmarkPageFilter; no Python-side
      linear scan of records on every keystroke.
    - Drops the showEvent/hideEvent destroy-and-rebuild pattern: the model
      stays alive across visibility transitions so re-opening the page is
      instantaneous.
    - Replaces the ad-hoc render generation counter / chunked QTimer
      rendering with the model's built-in fetchMore / generation guard.
    """

    # Public signals — same shape as the legacy class so MainWindow doesn't
    # need to know we rewrote anything.
    navigate_to_history = Signal(object, bool)  # (BookmarkRecord, hidden_mode)
    bookmark_changed = Signal()

    # Search debounce delay in ms — matches the legacy 200 ms behaviour.
    _SEARCH_DEBOUNCE_MS = 200

    def __init__(self, db: LocalDatabase, config=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config

        # Filter state — assembled into a BookmarkPageFilter on every change.
        self._active_tag: str = ""
        self._show_annotated_only: bool = False
        self._search_text: str = ""
        self._hidden_mode: bool = False

        # Page-level shortcuts (currently empty; reserved for forward compat).
        self._page_shortcuts: list[QShortcut] = []

        # Search debounce timer — fires once after the user stops typing.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self._SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._on_search_timer)

        # Model + delegate — created BEFORE _build_ui so wiring is simple.
        self._model = BookmarkListModel(self._db, parent=self)
        self._model.loading_changed.connect(self._on_loading_changed)
        self._model.total_count_changed.connect(self._on_total_count_changed)
        self._model.tags_changed.connect(self._on_tags_changed)

        self._build_ui()
        self._setup_shortcuts()

        # Wire up theme handling (the delegate also handles its own cache
        # invalidation; we just nudge the QListWidget tag sidebar).
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        # Initial load — kicks off both the first page fetch and the count
        # query.  Does NOT block the constructor; results arrive on signals.
        self._reload_with_current_filter()
        self._model.refresh_tags()

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_main_area())
        splitter.setSizes([180, 600])
        root.addWidget(splitter)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("bm_sidebar")
        sidebar.setFixedWidth(180)

        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 12, 8, 8)
        sb_layout.setSpacing(6)

        sb_title = QLabel(_("Tags"))
        sb_title.setObjectName("sidebar_section_title")
        sb_layout.addWidget(sb_title)

        self._tag_list = QListWidget()
        self._tag_list.setObjectName("tag_list")
        self._tag_list.currentRowChanged.connect(self._on_tag_selected)
        sb_layout.addWidget(self._tag_list, 1)

        # Initial sidebar state: just "All Bookmarks" until tags load.
        self._populate_tag_sidebar([])

        return sidebar

    def _build_main_area(self) -> QWidget:
        main_area = QWidget()
        ma_layout = QVBoxLayout(main_area)
        ma_layout.setContentsMargins(12, 12, 12, 12)
        ma_layout.setSpacing(8)

        # Toolbar: search + has-note toggle.
        bar = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_("Search bookmarks… (tag:work, after:2024-01-01, has:note)"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        bar.addWidget(self._search_edit, 1)

        self._btn_all = QPushButton(_("All"))
        self._btn_all.setCheckable(True)
        self._btn_all.setChecked(True)
        self._btn_all.setObjectName("filter_chip")
        self._btn_all.clicked.connect(lambda: self._set_annotated_filter(False))
        bar.addWidget(self._btn_all)

        self._btn_has_note = QPushButton(get_icon("message-square"), _("Has Note"))
        self._btn_has_note.setCheckable(True)
        self._btn_has_note.setObjectName("filter_chip")
        self._btn_has_note.clicked.connect(lambda: self._set_annotated_filter(True))
        bar.addWidget(self._btn_has_note)

        ma_layout.addLayout(bar)

        # Hidden-mode banner (shown only when hidden mode is on).
        self._hidden_banner = QFrame()
        self._hidden_banner.setObjectName("hidden_mode_banner")
        self._hidden_banner.setStyleSheet(
            "QFrame#hidden_mode_banner { background: rgba(255,140,0,0.15);"
            " border: 1px solid rgba(255,140,0,0.5); border-radius: 4px; }"
        )
        banner_layout = QHBoxLayout(self._hidden_banner)
        banner_layout.setContentsMargins(10, 4, 10, 4)
        banner_icon = QLabel()
        banner_icon.setPixmap(get_icon("eye").pixmap(14, 14))
        banner_layout.addWidget(banner_icon)
        banner_lbl = QLabel(_("Hidden mode — showing only bookmarks pointing to hidden records"))
        banner_lbl.setObjectName("muted")
        banner_layout.addWidget(banner_lbl, 1)
        self._hidden_banner.hide()
        ma_layout.addWidget(self._hidden_banner)

        # Count label (Loading… until count_ready arrives).
        self._count_lbl = QLabel(_("Loading…"))
        self._count_lbl.setObjectName("muted")
        ma_layout.addWidget(self._count_lbl)

        # The bookmark list view — the centrepiece of the rewrite.
        self._view = _BookmarkListView()
        self._view.setObjectName("bookmark_list_view")
        self._view.setModel(self._model)
        self._delegate = BookmarkDelegate(self._view)
        self._view.setItemDelegate(self._delegate)
        self._view.set_delegate(self._delegate)
        self._view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setUniformItemSizes(False)
        self._view.setSpacing(8)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        self._view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # A resize on the viewport invalidates per-width sizeHint cache so
        # rows wrap correctly to the new available width.
        self._view.viewport().installEventFilter(self)

        # Wire delegate / view actions to the same dispatcher.
        self._delegate.action_requested.connect(self._on_card_action)
        self._delegate.activated.connect(lambda bm: self._open_url(bm.url))
        self._view.action_triggered.connect(self._on_card_action)
        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.activated.connect(self._on_view_activated)

        ma_layout.addWidget(self._view, 1)

        return main_area

    # ── Filter assembly ───────────────────────────────────────

    def _build_filter(self) -> BookmarkPageFilter:
        """Translate the live UI state into a BookmarkPageFilter."""
        query = parse_query(self._search_text)
        # bookmark_tag from search query overrides sidebar selection (matches legacy behaviour).
        effective_tag = query.bookmark_tag if query.bookmark_tag else self._active_tag
        has_ann = self._show_annotated_only or query.has_annotation
        return BookmarkPageFilter(
            tag=effective_tag,
            keyword=query.keyword,
            title_only=query.title_only,
            url_only=query.url_only,
            has_annotation=has_ann,
            excludes=tuple(query.excludes),
            domains=tuple(query.domains),
            after=query.after,
            before=query.before,
            hidden_mode=self._hidden_mode,
        )

    def _reload_with_current_filter(self) -> None:
        self._model.reset_filter(self._build_filter())

    # ── Search / filter input handlers ────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text
        self._search_timer.start()

    def _on_search_timer(self) -> None:
        self._reload_with_current_filter()

    def _set_annotated_filter(self, only_annotated: bool) -> None:
        self._show_annotated_only = only_annotated
        self._btn_all.setChecked(not only_annotated)
        self._btn_has_note.setChecked(only_annotated)
        self._reload_with_current_filter()

    def _on_tag_selected(self, row: int) -> None:
        if row < 0:
            return
        item = self._tag_list.item(row)
        new_tag = item.data(Qt.UserRole) if item else ""
        if new_tag == self._active_tag:
            return
        self._active_tag = new_tag
        self._reload_with_current_filter()

    # ── Tag sidebar ───────────────────────────────────────────

    def _populate_tag_sidebar(self, tags: list[str]) -> None:
        """Rebuild the tag QListWidget while preserving the active selection."""
        self._tag_list.blockSignals(True)
        self._tag_list.clear()

        all_item = QListWidgetItem(get_icon("bookmark"), _("All Bookmarks"))
        all_item.setData(Qt.UserRole, "")
        self._tag_list.addItem(all_item)

        for tag in tags:
            item = QListWidgetItem(get_icon("tag"), f"#{tag}")
            item.setData(Qt.UserRole, tag)
            self._tag_list.addItem(item)

        # Restore selection on the active tag (or fall back to "All").
        target_row = 0
        for i in range(self._tag_list.count()):
            if self._tag_list.item(i).data(Qt.UserRole) == self._active_tag:
                target_row = i
                break
        self._tag_list.setCurrentRow(target_row)
        self._tag_list.blockSignals(False)

    def _on_tags_changed(self, tags: list) -> None:
        self._populate_tag_sidebar(list(tags))

    # ── Model state handlers ──────────────────────────────────

    def _on_loading_changed(self, loading: bool) -> None:
        if loading:
            self._count_lbl.setText(_("Loading…"))
        else:
            # When loading ends, render the count we last received from the
            # count worker.  total_count_changed may have arrived before the
            # final loading_changed(False), in which case _on_total_count_changed
            # already set the label; calling it again is idempotent.
            self._on_total_count_changed(self._model.total_count)

    def _on_total_count_changed(self, n: int) -> None:
        if self._model.is_loading:
            return
        self._count_lbl.setText(_("{n} bookmarks").format(n=n))

    # ── Card action dispatch ──────────────────────────────────

    def _on_card_action(self, action: str, bm: BookmarkRecord) -> None:
        """Single dispatcher for every clickable / keyboard-triggered action."""
        if action in ("open", "title"):
            self._open_url(bm.url)
        elif action in ("edit_tags", "tag_area"):
            self._edit_tags(bm)
        elif action in ("edit_note", "note"):
            self._edit_note(bm)
        elif action == "locate":
            self._locate_in_history(bm)
        elif action == "remove":
            self._remove_bookmark(bm)
        elif action == "copy_url":
            QApplication.clipboard().setText(bm.url)
        else:
            log.debug("Unknown bookmark action: %s", action)

    def _on_double_clicked(self, idx: QModelIndex) -> None:
        bm = idx.data(BookmarkListModel.BookmarkRole)
        if bm is not None:
            self._open_url(bm.url)

    def _on_view_activated(self, idx: QModelIndex) -> None:
        # Triggered by Enter/Return on the focused row when not consumed
        # by _BookmarkListView.keyPressEvent (defensive double-handler).
        bm = idx.data(BookmarkListModel.BookmarkRole)
        if bm is not None:
            self._open_url(bm.url)

    # ── Mutations (DB writes + optimistic model updates) ──────

    def _open_url(self, url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("Failed to open URL")

    def _edit_tags(self, bm: BookmarkRecord) -> None:
        current = ", ".join(bm.tags)
        text, ok = QInputDialog.getText(
            self,
            _("Edit Tags"),
            _("Tags (comma-separated):"),
            QLineEdit.Normal,
            current,
        )
        if not ok:
            return
        tags = [t.strip() for t in text.split(",") if t.strip()]
        old_tags = set(bm.tags)
        new_tags = set(tags)
        try:
            self._db.update_bookmark_tags(bm.url, tags)
        except Exception:
            log.exception("update_bookmark_tags failed")
            return
        self._model.update_tags(bm.url, tags)
        self.bookmark_changed.emit()
        if old_tags != new_tags:
            self._model.refresh_tags()

    def _edit_note(self, bm: BookmarkRecord) -> None:
        existing = self._db.get_annotation(bm.url)
        dlg = AnnotationDialog(bm.url, bm.title or bm.url, existing, parent=self)
        if not exec_centered(dlg, self):
            return
        note = dlg.get_note()
        try:
            if note.strip():
                ann = self._db.upsert_annotation(bm.url, note)
            else:
                self._db.delete_annotation(bm.url)
                ann = None
        except Exception:
            log.exception("annotation write failed")
            return
        self._model.update_note(bm.url, ann)
        self.bookmark_changed.emit()
        # When filter is "Has Note" and we just removed the note, the row
        # should disappear; reload to apply the filter consistently.
        if self._show_annotated_only and ann is None:
            self._reload_with_current_filter()

    def _remove_bookmark(self, bm: BookmarkRecord) -> None:
        reply = QMessageBox.question(
            self,
            _("Remove Bookmark"),
            _("Remove bookmark for:\n{title}").format(title=bm.title or bm.url),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._db.remove_bookmark(bm.url)
        except Exception:
            log.exception("remove_bookmark failed")
            return
        self._model.remove_url(bm.url)
        self.bookmark_changed.emit()
        self._model.refresh_tags()

    def _locate_in_history(self, bm: BookmarkRecord) -> None:
        self.navigate_to_history.emit(bm, self._hidden_mode)

    # ── Context menu ──────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        bm = idx.data(BookmarkListModel.BookmarkRole)
        if bm is None:
            return
        menu = StyledMenu(self)
        entries = [
            ("corner-up-right", _("Open in Browser"), lambda _bm=bm: self._open_url(_bm.url)),
            ("copy", _("Copy URL"), lambda _bm=bm: QApplication.clipboard().setText(_bm.url)),
            None,
            ("tag", _("Edit Tags"), lambda _bm=bm: self._edit_tags(_bm)),
            ("edit-2", _("Edit Note"), lambda _bm=bm: self._edit_note(_bm)),
            None,
            ("crosshair", _("Locate in History"), lambda _bm=bm: self._locate_in_history(_bm)),
            None,
            ("trash", _("Remove Bookmark"), lambda _bm=bm: self._remove_bookmark(_bm)),
        ]
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            icon_name, label, cb = entry
            act = QAction(get_icon(icon_name), label, self)
            # QAction.triggered emits checked(bool) as its first arg; absorb it.
            act.triggered.connect(lambda _checked=False, _cb=cb: _cb())
            menu.addAction(act)
        menu.exec(self._view.viewport().mapToGlobal(pos))

    # ── Theme handling ────────────────────────────────────────

    def _on_theme_changed(self, _resolved: str) -> None:
        # Tag list — re-polish so its item palette refreshes (matches legacy).
        style = self._tag_list.style()
        style.unpolish(self._tag_list)
        style.polish(self._tag_list)
        self._tag_list.viewport().update()
        # Bookmark list — delegate already cleared its cache on the same
        # signal, so we just nudge the viewport to repaint.
        self._view.viewport().update()

    # ── Keyboard shortcuts ────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        """Page-level shortcuts (currently empty; kept for forward-compat).

        Per-card shortcuts (Enter, Del, Ctrl+C/N/L) live in
        :class:`_BookmarkListView.keyPressEvent` so they only fire when the
        list view itself has focus, preventing cross-page conflicts.
        """
        for sc in self._page_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._page_shortcuts.clear()

    def apply_keybindings(self) -> None:
        """Re-apply keyboard shortcuts after a settings change."""
        self._setup_shortcuts()

    def _focus_search(self) -> None:
        """Focus the bookmark search bar and select existing text."""
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # ── Viewport eventFilter (resize → invalidate sizeHint cache) ──

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._view.viewport() and event.type() == QEvent.Resize:
            # Width changed → cached sizeHints (keyed by width) are stale.
            # The delegate's cache also keys on width so most entries stay
            # fresh, but we still poke the layout to re-query.
            self._delegate.invalidate_cache()
            self._view.scheduleDelayedItemsLayout()
        return super().eventFilter(obj, event)

    # ── Public API ────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload bookmarks (and tags) from the database with the active filter.

        Cheap with the new model: a single keyset page + a count query.
        Called by MainWindow on relevant external events.
        """
        self._model.refresh()
        self._model.refresh_tags()

    def apply_external_bookmark_change(self) -> None:
        """Slot called by MainWindow when another page mutates a bookmark.

        The current page state is unchanged; we just re-fetch so any new /
        removed / edited rows show up.  Internal mutations from this page
        already update the model optimistically and do NOT need this path.
        """
        self.refresh()

    def set_hidden_mode(self, enabled: bool) -> None:
        """Switch between normal and hidden-record bookmark views."""
        if self._hidden_mode == enabled:
            return
        self._hidden_mode = enabled
        self._hidden_banner.setVisible(enabled)
        self._reload_with_current_filter()

    def leave_hidden_mode(self) -> None:
        """Return to normal mode (no-op if already in normal mode)."""
        self.set_hidden_mode(False)

    # ── Lifecycle ─────────────────────────────────────────────

    def closeEvent(self, event):
        # Wait for in-flight workers so we don't leave QThreads dangling.
        try:
            self._model.shutdown()
        except Exception:
            log.exception("model.shutdown() raised")
        super().closeEvent(event)
