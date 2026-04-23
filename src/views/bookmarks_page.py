# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
import webbrowser

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.models.history_record import AnnotationRecord, BookmarkRecord
from src.services.local_db import LocalDatabase
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.styled_menu import StyledMenu
from src.utils.theme_manager import ThemeManager
from src.views.annotation_dialog import AnnotationDialog

log = get_logger("view.bookmarks")

_CHUNK_SIZE = 20
_PAGE_SIZE = 50


def _extract_domain(url: str) -> str:
    """Extract the domain (netloc) from a given URL."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc.lower()
    except Exception:
        return url.lower()


# ===========================================================================
# Background Workers
# ===========================================================================


class _LoadWorker(QThread):
    """
    Background thread that loads bookmarks, annotations, and tags.

    Design Note:
        Subclassing QThread (rather than using a QObject + moveToThread) keeps
        the C++ object in the main thread. This ensures Python's reference
        counting can never delete the C++ instance from the wrong thread,
        preventing the 0xC0000005 access violation.

    Signals:
        result: Emits (bookmarks, annotations, tags). Named 'result' instead
                of 'finished' to avoid shadowing QThread.finished.
        error: Emits the error message as a string.
    """

    result = Signal(list, list, list)
    error = Signal(str)

    def __init__(self, db: LocalDatabase, tag: str, hidden_mode: bool = False, parent=None):
        super().__init__(parent)
        self._db = db
        self._tag = tag
        self._hidden_mode = hidden_mode

    def run(self):
        try:
            bookmarks = self._db.get_all_bookmarks(tag=self._tag, hidden_mode=self._hidden_mode)
            annotations = self._db.get_all_annotations()
            tags = self._db.get_all_bookmark_tags()
            self.result.emit(bookmarks, annotations, tags)
        except Exception as exc:
            log.exception("_LoadWorker.run failed")
            self.error.emit(str(exc))


class _TagRefreshWorker(QThread):
    """Background thread that refreshes the tag list only."""

    done = Signal(list)

    def __init__(self, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._db = db

    def run(self):
        try:
            self.done.emit(self._db.get_all_bookmark_tags())
        except Exception:
            log.exception("_TagRefreshWorker.run failed")
            self.done.emit([])


# ===========================================================================
# Bookmark Card Widget
# ===========================================================================


class _BookmarkCard(QFrame):
    """UI Widget representing a single bookmark card."""

    open_requested = Signal(str)
    edit_tags_requested = Signal(object)
    add_note_requested = Signal(object)
    remove_requested = Signal(object)
    copy_url_requested = Signal(str)
    locate_in_list_requested = Signal(object)
    # Emitted when the card receives focus via click, so the page can track it
    card_focused = Signal(object)  # emits self
    # Emitted by arrow-key press so the page can shift focus to adjacent card
    navigate_requested = Signal(object, int)  # (card, direction: -1 up / +1 down)

    def __init__(self, bm: BookmarkRecord, annotation: AnnotationRecord | None, parent=None):
        super().__init__(parent)
        self.setObjectName("bookmark_card")
        self.setFrameShape(QFrame.StyledPanel)
        # Allow the card to receive keyboard focus via mouse click
        self.setFocusPolicy(Qt.ClickFocus)

        self._bm = bm
        self._ann = annotation
        self._note_frame: QFrame | None = None
        self._note_lbl: QLabel | None = None

        self._build()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        menu = StyledMenu(self)

        # Note: QAction.triggered emits checked(bool) as the first positional arg.
        # Each lambda absorbs that arg (named `_`) so `bm` is never shadowed by True/False.
        entries = [
            ("corner-up-right", _("Open in Browser"), lambda _, bm=self._bm: self.open_requested.emit(bm.url)),
            ("copy", _("Copy URL"), lambda _, bm=self._bm: self.copy_url_requested.emit(bm.url)),
            None,
            ("tag", _("Edit Tags"), lambda _, bm=self._bm: self.edit_tags_requested.emit(bm)),
            ("edit-2", _("Edit Note"), lambda _, bm=self._bm: self.add_note_requested.emit(bm)),
            None,
            ("crosshair", _("Locate in History"), lambda _, bm=self._bm: self.locate_in_list_requested.emit(bm)),
            None,
            ("trash", _("Remove Bookmark"), lambda _, bm=self._bm: self.remove_requested.emit(bm)),
        ]

        for entry in entries:
            if entry is None:
                menu.addSeparator()
            else:
                icon_name, label, cb = entry
                act = QAction(get_icon(icon_name), label, self)
                act.triggered.connect(cb)
                menu.addAction(act)

        menu.exec(self.mapToGlobal(pos))

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # --- Top Row ---
        top = QHBoxLayout()
        top.setSpacing(6)

        title_text = self._bm.title or self._bm.url
        title_lbl = QLabel(f"<b>{title_text}</b>")
        title_lbl.setWordWrap(True)
        title_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_lbl.setCursor(Qt.PointingHandCursor)

        # Capture bm by value so clicks still work after _bm is mutated
        _url = self._bm.url

        def _title_press(event, url=_url):
            if event.button() == Qt.LeftButton:
                self.open_requested.emit(url)
            else:
                QLabel.mousePressEvent(title_lbl, event)

        title_lbl.mousePressEvent = _title_press
        top.addWidget(title_lbl, 1)

        # Note: QPushButton.clicked emits checked(bool) as the first positional arg.
        # Use `_` to absorb it so `bm` always receives the BookmarkRecord snapshot.
        _bm_snap = self._bm
        btn_specs = [
            ("corner-up-right", _("Open in browser"), lambda _, bm=_bm_snap: self.open_requested.emit(bm.url)),
            ("tag", _("Edit tags"), lambda _, bm=_bm_snap: self.edit_tags_requested.emit(bm)),
            ("edit-2", _("Edit note"), lambda _, bm=_bm_snap: self.add_note_requested.emit(bm)),
            ("crosshair", _("Locate in History"), lambda _, bm=_bm_snap: self.locate_in_list_requested.emit(bm)),
            ("trash", _("Remove bookmark"), lambda _, bm=_bm_snap: self.remove_requested.emit(bm)),
        ]

        for icon_name, tooltip, cb in btn_specs:
            btn = QPushButton()
            btn.setIcon(get_icon(icon_name))
            btn.setToolTip(tooltip)
            btn.setFixedSize(26, 26)
            btn.setObjectName("icon_btn")
            btn.clicked.connect(cb)
            top.addWidget(btn)

        layout.addLayout(top)

        # --- URL ---
        url_lbl = QLabel(self._bm.url)
        url_lbl.setObjectName("muted")
        url_lbl.setWordWrap(True)
        url_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        url_lbl.setContextMenuPolicy(Qt.NoContextMenu)
        layout.addWidget(url_lbl)

        # --- Tags ---
        self._tag_container = QWidget(self)
        self._tag_container.setObjectName("tag_container")
        self._tag_container.setAttribute(Qt.WA_TranslucentBackground)
        self._rebuild_tags_widget()
        layout.addWidget(self._tag_container)

        # --- Note ---
        note_text = (self._ann.note if (self._ann and self._ann.note) else "").strip()
        if note_text:
            self._insert_note_frame(note_text, layout)

        # --- Footer ---
        dt = datetime.fromtimestamp(self._bm.bookmarked_at).strftime("%Y-%m-%d %H:%M")
        footer_lbl = QLabel(_("Bookmarked: {dt}").format(dt=dt))
        footer_lbl.setObjectName("muted_small")
        layout.addWidget(footer_lbl)

    def _insert_note_frame(self, note: str, layout: QVBoxLayout):
        note_frame = QFrame()
        note_frame.setObjectName("note_frame")

        nf_layout = QHBoxLayout(note_frame)
        nf_layout.setContentsMargins(8, 4, 8, 4)

        note_icon = QLabel()
        note_icon.setPixmap(get_icon("message-square").pixmap(14, 14))
        nf_layout.addWidget(note_icon)

        note_lbl = QLabel(note)
        note_lbl.setWordWrap(True)
        note_lbl.setObjectName("note_text")
        nf_layout.addWidget(note_lbl, 1)

        layout.addWidget(note_frame)
        self._note_frame = note_frame
        self._note_lbl = note_lbl

    def _rebuild_tags_widget(self):
        layout = self._tag_container.layout()
        if layout is None:
            layout = QHBoxLayout(self._tag_container)
            layout.setContentsMargins(0, 2, 0, 0)
            layout.setSpacing(4)
        else:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        for tag in self._bm.tags:
            chip = QLabel(f"#{tag}")
            chip.setObjectName("inline_tag")
            layout.addWidget(chip)

        layout.addStretch()
        self._tag_container.setVisible(bool(self._bm.tags))

    def _rebuild_tags(self):
        self._rebuild_tags_widget()

    def update_note(self, ann: AnnotationRecord | None):
        self._ann = ann
        note_text = (ann.note if ann and ann.note else "").strip()

        if self._note_frame is not None:
            if note_text:
                self._note_lbl.setText(note_text)
            else:
                self.layout().removeWidget(self._note_frame)
                self._note_frame.deleteLater()
                self._note_frame = None
                self._note_lbl = None
        elif note_text:
            self._insert_note_frame(note_text, self.layout())

    # ── Focus / keyboard handling ─────────────────────────────

    def mousePressEvent(self, event):
        """Claim keyboard focus when the card is clicked."""
        super().mousePressEvent(event)
        self.setFocus()
        self.card_focused.emit(self)

    def focusInEvent(self, event):
        """Highlight the card border when it has keyboard focus."""
        super().focusInEvent(event)
        self.setStyleSheet("QFrame#bookmark_card { border: 2px solid palette(highlight); }")

    def focusOutEvent(self, event):
        """Restore default card style when focus is lost."""
        super().focusOutEvent(event)
        self.setStyleSheet("")

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts while the card has focus."""
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.open_requested.emit(self._bm.url)
            event.accept()
        elif key == Qt.Key_Delete:
            self.remove_requested.emit(self._bm)
            event.accept()
        elif key == Qt.Key_C and mods & Qt.ControlModifier:
            self.copy_url_requested.emit(self._bm.url)
            event.accept()
        elif key == Qt.Key_N and mods & Qt.ControlModifier:
            self.add_note_requested.emit(self._bm)
            event.accept()
        elif key == Qt.Key_L and mods & Qt.ControlModifier:
            self.locate_in_list_requested.emit(self._bm)
            event.accept()
        elif key == Qt.Key_Up:
            self.navigate_requested.emit(self, -1)
            event.accept()
        elif key == Qt.Key_Down:
            self.navigate_requested.emit(self, +1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def disconnect_all(self):
        """
        Sever all outbound signals before the card is deleted.

        Qt's deleteLater() is asynchronous. If a mouse event (e.g., a click
        still in the input queue) is processed between the Python-side
        'deleteLater()' call and the actual C++ destruction, Qt will try to
        emit a signal through the partially alive object. This corrupts memory
        and causes a 0xC0000005 crash on Windows.

        Disconnecting here is synchronous and immediate, preventing any signals
        from firing after we've decided to remove the card.
        """
        signals = [
            self.open_requested,
            self.copy_url_requested,
            self.edit_tags_requested,
            self.add_note_requested,
            self.remove_requested,
            self.locate_in_list_requested,
            self.card_focused,
            self.navigate_requested,
            self.customContextMenuRequested,
        ]
        for sig in signals:
            try:
                sig.disconnect()
            except RuntimeError:
                pass


# ===========================================================================
# Main Page
# ===========================================================================


class BookmarksPage(QWidget):
    """
    Bookmark management page.

    Crash Fixes Implemented:
        1. Timer Signal Accumulation (RuntimeError / double-fire):
           The render timer slot is connected ONCE at construction. A generation
           counter guards against stale ticks.
        2. Use-After-Free on Card Deletion (0xC0000005):
           `_BookmarkCard.disconnect_all()` severs outbound signals before
           `deleteLater()` is called, preventing pending OS events from triggering
           signals on destroyed C++ objects.
        3. Thread Race on `_all_bookmarks`:
           `_load_generation` is bumped BEFORE the old worker is abandoned.
           In-flight callbacks see a stale generation and return safely.
        4. Worker/Thread Ownership (0xC0000005):
           Workers subclass QThread directly (not QObject + moveToThread), keeping
           the C++ object in the main thread. Finished callbacks use identity
           checks to only clear references for their own worker.
        5. deleteLater() on a Running QThread (0xC0000409 STATUS_STACK_BUFFER_OVERRUN):
           Previously, `deleteLater()` was called unconditionally. Since `_LoadWorker`
           has no event loop, `quit()` is a no-op. The main thread would process the
           deferred-delete while the worker was still executing `run()`, destroying
           the C++ base object under the thread.
           Fix: Connect `finished -> deleteLater` so C++ is destroyed only after exit.
        6. Batch Card Deletion Layout Thrashing (O(n²) + reentrant events):
           Calling `removeWidget()` in a loop triggers full layout recalculations
           and repaints per removal.
           Fix: Wrap `_clear_cards()` with `setUpdatesEnabled(False/True)`.

    Performance Fixes Implemented:
        1. O(1) card lookup via `_card_index` dict (was O(n) linear scan).
        2. Count label computed from source-of-truth lists after mutation.
    """

    navigate_to_history = Signal(object, bool)
    bookmark_changed = Signal()

    def __init__(self, db: LocalDatabase, config=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config  # AppConfig; may be None in test contexts
        self._active_tag: str = ""
        self._show_annotated_only: bool = False
        self._search_text: str = ""
        self._hidden_mode: bool = False

        self._cards: list[_BookmarkCard] = []
        self._card_index: dict[str, _BookmarkCard] = {}  # url -> card (O(1) lookup)
        self._focused_card: _BookmarkCard | None = None  # card with keyboard focus

        self._pending_bms: list[tuple] = []
        self._render_queue: list[tuple] = []

        # Connected ONCE - never rewired
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(16)
        self._render_timer.timeout.connect(self._on_render_tick)

        self._load_generation: int = 0
        self._render_generation: int = 0

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._rebuild_cards_from_cache)

        self._worker: _LoadWorker | None = None
        self._tag_worker: _TagRefreshWorker | None = None

        self._all_bookmarks: list[BookmarkRecord] = []
        self._annotations: dict[str, AnnotationRecord] = {}
        self._all_tags: list[str] = []

        self._page_shortcuts: list[QShortcut] = []

        self._build_ui()
        self._setup_shortcuts()
        self._start_load()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def hideEvent(self, event):
        """Clear all card widgets when the page is hidden."""
        super().hideEvent(event)
        self._stop_render()
        self._clear_cards()
        self._pending_bms.clear()

    def showEvent(self, event):
        """Reload bookmarks from the database each time the page becomes visible."""
        super().showEvent(event)
        self._start_load()

    def _on_theme_changed(self, _theme: str) -> None:
        """Re-polish the tag list after a theme switch.

        Card widgets are destroyed while the page is hidden (see hideEvent),
        so app.setStyleSheet() no longer iterates over them.  The only extra
        work needed here is to nudge the QListWidget's style so its item
        colours pick up the new palette correctly.
        """
        style = self._tag_list.style()
        style.unpolish(self._tag_list)
        style.polish(self._tag_list)
        self._tag_list.viewport().update()

    # --- UI Setup ---

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # Sidebar
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

        splitter.addWidget(sidebar)

        # Main Area
        main_area = QWidget()
        ma_layout = QVBoxLayout(main_area)
        ma_layout.setContentsMargins(12, 12, 12, 12)
        ma_layout.setSpacing(8)

        # Toolbar
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

        # Hidden mode banner (shown only when in hidden mode)
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

        self._count_lbl = QLabel()
        self._count_lbl.setObjectName("muted")
        ma_layout.addWidget(self._count_lbl)

        # Scroll Area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)

        # Disable horizontal scrollbar: Long URLs inside cards would expand horizontally.
        # Setting to AlwaysOff forces content to wrap within the available width.
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        # addStretch keeps cards compactly stacked at the top, preventing them
        # from stretching to fill the window when there are few bookmarks.
        self._cards_layout.addStretch(1)

        self._scroll_area.setWidget(self._cards_container)
        ma_layout.addWidget(self._scroll_area, 1)

        self._load_more_btn = QPushButton()
        self._load_more_btn.setObjectName("filter_chip")
        self._load_more_btn.hide()
        self._load_more_btn.clicked.connect(self._load_next_page)
        ma_layout.addWidget(self._load_more_btn)

        splitter.addWidget(main_area)
        splitter.setSizes([180, 600])
        root.addWidget(splitter)

    # --- Background Load ---

    def _stop_render(self):
        """Stop the render timer and advance the generation counter."""
        self._render_timer.stop()
        self._render_queue.clear()
        self._render_generation += 1

    def _start_load(self):
        self._stop_render()

        # Bump generation BEFORE quit() so any in-flight result callback sees
        # a stale gen and exits without touching shared state.
        self._load_generation += 1
        gen = self._load_generation

        # Because _LoadWorker IS the QThread (lives in the main thread), calling
        # isRunning() is always safe — there's no risk of a deleted C++ object.
        if self._worker is not None:
            if self._worker.isRunning():
                # CRITICAL: quit() is a NO-OP here — _LoadWorker.run() never
                # calls exec(), so there is no Qt event loop inside the thread
                # to receive the quit signal. The thread will always run to completion.
                #
                # NEVER call deleteLater() on a QThread whose run() is still executing.
                # Safe pattern: let the thread finish naturally, then delete.
                self._worker.finished.connect(self._worker.deleteLater)
            else:
                # Thread already finished — safe to delete immediately.
                self._worker.deleteLater()
            self._worker = None

        self._count_lbl.setText(_("Loading…"))

        worker = _LoadWorker(
            self._db, "", hidden_mode=self._hidden_mode, parent=self
        )  # tag filtering is done client-side
        worker.result.connect(lambda bms, anns, tags: self._on_load_finished(bms, anns, tags, gen))
        worker.error.connect(lambda e: log.error("Bookmark load error: %s", e))

        # Only clear the ref when THIS specific worker finishes, not a future one.
        worker.finished.connect(lambda w=worker: self._clear_load_worker_ref(w))

        self._worker = worker
        worker.start()

    def _clear_load_worker_ref(self, w: _LoadWorker):
        if self._worker is w:
            self._worker = None

    def _on_load_finished(
        self,
        bookmarks: list[BookmarkRecord],
        annotations: list[AnnotationRecord],
        tags: list[str],
        gen: int,
    ):
        if gen != self._load_generation:
            return
        self._all_bookmarks = bookmarks
        self._annotations = {ann.url: ann for ann in annotations}
        self._all_tags = tags
        self._rebuild_tag_sidebar_from_cache()
        self._rebuild_cards_from_cache()

    # --- Tag Sidebar ---

    def _rebuild_tag_sidebar_from_cache(self):
        self._tag_list.blockSignals(True)
        self._tag_list.clear()

        all_item = QListWidgetItem(get_icon("bookmark"), _("All Bookmarks"))
        all_item.setData(Qt.UserRole, "")
        self._tag_list.addItem(all_item)

        for tag in self._all_tags:
            item = QListWidgetItem(get_icon("tag"), f"#{tag}")
            item.setData(Qt.UserRole, tag)
            self._tag_list.addItem(item)

        for i in range(self._tag_list.count()):
            if self._tag_list.item(i).data(Qt.UserRole) == self._active_tag:
                self._tag_list.setCurrentRow(i)
                break
        else:
            self._tag_list.setCurrentRow(0)

        self._tag_list.blockSignals(False)

    # --- Filtering ---

    def _filter_bookmarks(self) -> list:
        query = parse_query(self._search_text)
        effective_tag = query.bookmark_tag if query.bookmark_tag else self._active_tag

        annotated_urls: set[str] | None = None
        if self._show_annotated_only or query.has_annotation:
            annotated_urls = {url for url, ann in self._annotations.items() if ann.note}

        keyword = query.keyword.lower()
        filtered = []

        for bm in self._all_bookmarks:
            if effective_tag and effective_tag not in bm.tags:
                continue
            if annotated_urls is not None and bm.url not in annotated_urls:
                continue
            if query.domains:
                bm_domain = _extract_domain(bm.url)
                if not any(d.lower() in bm_domain for d in query.domains):
                    continue
            if query.after:
                after_ts = int(datetime(query.after.year, query.after.month, query.after.day).timestamp())
                if bm.bookmarked_at < after_ts:
                    continue
            if query.before:
                before_ts = int(
                    datetime(query.before.year, query.before.month, query.before.day, 23, 59, 59).timestamp()
                )
                if bm.bookmarked_at > before_ts:
                    continue
            if keyword:
                match_title = keyword in (bm.title or "").lower()
                match_url = keyword in bm.url.lower()
                match_tag = any(keyword in t.lower() for t in bm.tags)
                if query.title_only:
                    if not match_title:
                        continue
                elif query.url_only:
                    if not match_url:
                        continue
                elif not (match_title or match_url or match_tag):
                    continue
            if query.excludes:
                combined = ((bm.title or "") + " " + bm.url).lower()
                if any(ex.lower() in combined for ex in query.excludes):
                    continue

            filtered.append((bm, self._annotations.get(bm.url)))

        return filtered

    # --- Chunked Card Rendering ---

    def _delete_card(self, card: _BookmarkCard):
        """
        Disconnect all signals then schedule C++ deletion.

        This is the ONLY safe way to remove a card. Calling deleteLater()
        without disconnecting first leaves pending OS events that can be
        delivered to the dying C++ object, causing 0xC0000005 crashes.

        Note: card.hide() is intentionally omitted here. When called from
        _clear_cards(), the container already has updates disabled.
        """
        card.disconnect_all()
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _clear_cards(self):
        """
        Clear all cards safely.

        Disables repaints for the entire batch so Qt does not fire a layout
        recalculation (and potentially a reentrant paintEvent) for every
        individual removeWidget() call.
        """
        self._focused_card = None  # stale reference - card is being destroyed
        self._cards_container.setUpdatesEnabled(False)
        try:
            for card in self._cards:
                self._delete_card(card)
            self._cards.clear()
            self._card_index.clear()
        finally:
            self._cards_container.setUpdatesEnabled(True)

    def _rebuild_cards_from_cache(self):
        self._stop_render()
        self._clear_cards()
        self._pending_bms.clear()

        rgen = self._render_generation  # already bumped by _stop_render()

        filtered = self._filter_bookmarks()
        total = len(filtered)

        first_page = filtered[:_PAGE_SIZE]
        self._pending_bms = filtered[_PAGE_SIZE:]

        self._render_queue = list(first_page)
        self._count_lbl.setText(_("{n} bookmarks").format(n=total))
        self._update_load_more_btn(total)

        if self._render_queue:
            # singleShot(0) defers until the event loop has processed the
            # deleteLater() calls issued by _clear_cards() above.
            QTimer.singleShot(0, lambda: self._render_chunk(rgen))

    def _on_render_tick(self):
        """Timer slot — connected once at construction, never rewired."""
        self._render_chunk(self._render_generation)

    def _render_chunk(self, rgen: int):
        if rgen != self._render_generation:
            self._render_timer.stop()
            return
        if not self._render_queue:
            self._render_timer.stop()
            return

        batch = self._render_queue[:_CHUNK_SIZE]
        self._render_queue = self._render_queue[_CHUNK_SIZE:]

        for bm, ann in batch:
            card = self._make_card(bm, ann)
            # Insert before the stretch (which is always the last item)
            # to keep cards compactly stacked at the top.
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._cards.append(card)
            self._card_index[bm.url] = card

        if self._render_queue:
            if not self._render_timer.isActive():
                self._render_timer.start()
        else:
            self._render_timer.stop()

    # --- Pagination ---

    def _load_next_page(self):
        if not self._pending_bms:
            return
        page = self._pending_bms[:_PAGE_SIZE]
        self._pending_bms = self._pending_bms[_PAGE_SIZE:]
        self._render_queue.extend(page)

        if not self._render_timer.isActive():
            self._render_timer.start()

        total = len(self._cards) + len(self._render_queue) + len(self._pending_bms)
        self._update_load_more_btn(total)

    def _update_load_more_btn(self, total: int):
        remaining = len(self._pending_bms)
        if remaining > 0:
            shown = len(self._cards) + len(self._render_queue)
            self._load_more_btn.setText(
                _("Load {n} more…").format(n=min(_PAGE_SIZE, remaining)) + f"  ({shown}/{total})"
            )
            self._load_more_btn.show()
        else:
            self._load_more_btn.hide()

    # --- Card Factory ---

    def _make_card(self, bm: BookmarkRecord, ann: AnnotationRecord | None) -> _BookmarkCard:
        card = _BookmarkCard(bm, ann, parent=self._cards_container)
        card.open_requested.connect(self._open_url)
        card.copy_url_requested.connect(lambda u: QApplication.clipboard().setText(u))
        card.edit_tags_requested.connect(self._edit_tags)
        card.add_note_requested.connect(self._edit_note)
        card.remove_requested.connect(self._remove_bookmark)
        card.locate_in_list_requested.connect(self._locate_in_history)
        card.card_focused.connect(self._on_card_focused)
        card.navigate_requested.connect(self._on_card_navigate)
        return card

    def _on_card_focused(self, card: _BookmarkCard) -> None:
        """Track which card currently holds keyboard focus."""
        self._focused_card = card

    def _on_card_navigate(self, card: _BookmarkCard, direction: int) -> None:
        """Move keyboard focus to the adjacent card (direction: -1 up, +1 down)."""
        try:
            idx = self._cards.index(card)
        except ValueError:
            return
        new_idx = max(0, min(len(self._cards) - 1, idx + direction))
        if new_idx == idx:
            return
        target = self._cards[new_idx]
        target.setFocus()
        self._focused_card = target
        # Scroll the target into view
        self._scroll_area.ensureWidgetVisible(target)

    def _find_card(self, url: str) -> _BookmarkCard | None:
        return self._card_index.get(url)

    # --- Event Handlers ---

    def _on_tag_selected(self, row: int):
        if row < 0:
            return
        item = self._tag_list.item(row)
        new_tag = item.data(Qt.UserRole) if item else ""
        if new_tag == self._active_tag:
            return
        self._active_tag = new_tag
        # If we already have the full bookmark list cached, filter client-side
        # immediately without a DB round-trip. This eliminates the UI freeze
        # caused by issuing a new _LoadWorker every time the user clicks a tag.
        if self._all_bookmarks:
            self._rebuild_cards_from_cache()
        else:
            self._start_load()

    def _on_search_changed(self, text: str):
        self._search_text = text
        self._search_timer.start()

    def _set_annotated_filter(self, only_annotated: bool):
        self._show_annotated_only = only_annotated
        self._btn_all.setChecked(not only_annotated)
        self._btn_has_note.setChecked(only_annotated)
        self._rebuild_cards_from_cache()

    def _open_url(self, url: str):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _edit_tags(self, bm: BookmarkRecord):
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
        self._db.update_bookmark_tags(bm.url, tags)
        self.bookmark_changed.emit()

        old_tags = set(bm.tags)
        new_tags = set(tags)
        bm.tags = tags

        for cached_bm in self._all_bookmarks:
            if cached_bm.url == bm.url:
                cached_bm.tags = tags
                break

        card = self._find_card(bm.url)
        if card is not None:
            card._bm = bm
            card._rebuild_tags()

        if old_tags != new_tags:
            self._refresh_tags_only()

    def _edit_note(self, bm: BookmarkRecord):
        existing = self._db.get_annotation(bm.url)
        dlg = AnnotationDialog(bm.url, bm.title or bm.url, existing, parent=self)
        if not dlg.exec():
            return

        note = dlg.get_note()
        if note.strip():
            ann = self._db.upsert_annotation(bm.url, note)
        else:
            self._db.delete_annotation(bm.url)
            ann = None

        self.bookmark_changed.emit()

        if ann:
            self._annotations[bm.url] = ann
        else:
            self._annotations.pop(bm.url, None)

        card = self._find_card(bm.url)
        if card is not None:
            card.update_note(ann)
        elif self._show_annotated_only:
            self._rebuild_cards_from_cache()

    def _remove_bookmark(self, bm: BookmarkRecord):
        reply = QMessageBox.question(
            self,
            _("Remove Bookmark"),
            _("Remove bookmark for:\n{title}").format(title=bm.title or bm.url),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.remove_bookmark(bm.url)

        # Invalidate any _LoadWorker that is still running (e.g. one launched by
        # showEvent just before the user clicked Delete).  Without this bump the
        # worker's _on_load_finished callback would overwrite _all_bookmarks with
        # stale data that still contains the just-deleted bookmark, making it
        # reappear as soon as the thread finishes.
        self._load_generation += 1

        self.bookmark_changed.emit()

        self._all_bookmarks = [b for b in self._all_bookmarks if b.url != bm.url]
        self._annotations.pop(bm.url, None)
        self._pending_bms = [(b, a) for b, a in self._pending_bms if b.url != bm.url]
        self._render_queue = [(b, a) for b, a in self._render_queue if b.url != bm.url]

        card = self._find_card(bm.url)
        if card is not None:
            self._cards.remove(card)
            del self._card_index[bm.url]
            self._delete_card(card)  # disconnect then deleteLater

        total = len(self._cards) + len(self._render_queue) + len(self._pending_bms)
        self._count_lbl.setText(_("{n} bookmarks").format(n=total))
        self._update_load_more_btn(total)

        self._refresh_tags_only()

    def _locate_in_history(self, bm: BookmarkRecord):
        self.navigate_to_history.emit(bm, self._hidden_mode)

    # --- Tag Refresh ---

    def _refresh_tags_only(self):
        if self._tag_worker is not None and self._tag_worker.isRunning():
            return  # already in flight; its result will be applied shortly

        worker = _TagRefreshWorker(self._db, parent=self)
        worker.done.connect(self._apply_refreshed_tags)
        worker.finished.connect(lambda w=worker: self._clear_tag_worker_ref(w))

        # Schedule C++ deletion once the thread exits so we don't accumulate
        # finished-but-not-deleted QThread children on the page widget.
        worker.finished.connect(worker.deleteLater)

        self._tag_worker = worker
        worker.start()

    def _clear_tag_worker_ref(self, w: _TagRefreshWorker):
        if self._tag_worker is w:
            self._tag_worker = None

    def _apply_refreshed_tags(self, tags: list[str]):
        self._all_tags = tags
        self._rebuild_tag_sidebar_from_cache()

    # --- Keyboard shortcuts ---

    def _setup_shortcuts(self) -> None:
        """Register page-level keyboard shortcuts from config.

        All shortcuts use Qt.WidgetWithChildrenShortcut so they only fire when
        this page (or one of its children) has focus, preventing cross-page
        conflicts when multiple pages are instantiated.

        Note: card-level actions (Return, Del, Ctrl+C, Ctrl+N, Ctrl+L) are
        handled directly in _BookmarkCard.keyPressEvent when a card is focused.
        Ctrl+F is handled by MainWindow global focus_search to avoid duplicate
        registrations that can become ambiguous in Qt shortcut dispatch.
        """
        for sc in self._page_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._page_shortcuts.clear()

        kb = self._config.keybindings.app if self._config else {}

        def _bind(key: str, fallback: str, slot) -> None:
            seq = kb.get(key, fallback)
            if not seq:
                return
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._page_shortcuts.append(sc)

        # No page-level Ctrl+F binding: handled globally by MainWindow.

    def apply_keybindings(self) -> None:
        """Re-apply keyboard shortcuts after config change."""
        self._setup_shortcuts()

    def _focus_search(self) -> None:
        """Focus the bookmark search bar and select existing text."""
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # --- Public API ---

    def refresh(self):
        """Public method to trigger a full refresh of the bookmarks data."""
        self._start_load()

    def set_hidden_mode(self, enabled: bool) -> None:
        """Switch between normal and hidden-record bookmark views.

        In normal mode bookmarks pointing to hidden URLs/domains are invisible.
        In hidden mode *only* those bookmarks are shown, mirroring the history
        page behaviour.
        """
        if self._hidden_mode == enabled:
            return
        self._hidden_mode = enabled
        self._hidden_banner.setVisible(enabled)
        self._start_load()

    def leave_hidden_mode(self) -> None:
        """Return to normal mode (no-op if already in normal mode)."""
        self.set_hidden_mode(False)
