# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
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
from src.views.annotation_dialog import AnnotationDialog

log = get_logger("view.bookmarks")


def _extract_domain(url: str) -> str:
    """Return the lowercased domain portion of a URL, or the raw URL on failure."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc.lower()
    except Exception:
        return url.lower()


class _TagChip(QPushButton):
    """A clickable pill button representing a single tag."""

    def __init__(self, tag: str, parent=None):
        super().__init__(f"# {tag}", parent)
        self.setCheckable(True)
        self.setObjectName("tag_chip")
        self.setCursor(Qt.PointingHandCursor)
        self._tag = tag

    @property
    def tag(self) -> str:
        return self._tag


class _BookmarkCard(QFrame):
    """A single bookmark card with title, URL, tags and optional note."""

    open_requested = Signal(str)
    edit_tags_requested = Signal(object)  # BookmarkRecord
    add_note_requested = Signal(object)  # BookmarkRecord
    remove_requested = Signal(object)  # BookmarkRecord
    copy_url_requested = Signal(str)
    locate_in_list_requested = Signal(object)  # BookmarkRecord

    def __init__(self, bm: BookmarkRecord, annotation: AnnotationRecord | None, parent=None):
        super().__init__(parent)
        self.setObjectName("bookmark_card")
        self.setFrameShape(QFrame.StyledPanel)
        self._bm = bm
        self._ann = annotation
        self._build()
        # Enable context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        open_act = QAction(get_icon("corner-up-right"), _("Open in Browser"), self)
        open_act.triggered.connect(lambda: self.open_requested.emit(self._bm.url))
        menu.addAction(open_act)

        copy_act = QAction(get_icon("copy"), _("Copy URL"), self)
        copy_act.triggered.connect(lambda: self.copy_url_requested.emit(self._bm.url))
        menu.addAction(copy_act)

        menu.addSeparator()

        edit_tags_act = QAction(get_icon("tag"), _("Edit Tags"), self)
        edit_tags_act.triggered.connect(lambda: self.edit_tags_requested.emit(self._bm))
        menu.addAction(edit_tags_act)

        edit_note_act = QAction(get_icon("edit-2"), _("Edit Note"), self)
        edit_note_act.triggered.connect(lambda: self.add_note_requested.emit(self._bm))
        menu.addAction(edit_note_act)

        menu.addSeparator()

        locate_act = QAction(get_icon("crosshair"), _("Locate in History"), self)
        locate_act.triggered.connect(lambda: self.locate_in_list_requested.emit(self._bm))
        menu.addAction(locate_act)

        menu.addSeparator()

        remove_act = QAction(get_icon("trash"), _("Remove Bookmark"), self)
        remove_act.triggered.connect(lambda: self.remove_requested.emit(self._bm))
        menu.addAction(remove_act)

        menu.exec(self.mapToGlobal(pos))

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # ── Top row: title + actions ──────────────────────────
        top = QHBoxLayout()
        top.setSpacing(6)

        title_text = self._bm.title or self._bm.url
        title_lbl = QLabel(f"<b>{title_text}</b>")
        title_lbl.setWordWrap(True)
        title_lbl.setCursor(Qt.PointingHandCursor)

        # Only open URL on left-click; let right-click propagate to the card's
        # context-menu handler instead of accidentally opening the browser.
        def _title_mouse_press(event, _lbl=title_lbl):
            if event.button() == Qt.LeftButton:
                self.open_requested.emit(self._bm.url)
            else:
                QLabel.mousePressEvent(_lbl, event)

        title_lbl.mousePressEvent = _title_mouse_press
        top.addWidget(title_lbl, 1)

        # Action buttons
        for icon_name, tooltip, cb in [
            ("corner-up-right", _("Open in browser"), lambda: self.open_requested.emit(self._bm.url)),
            ("tag", _("Edit tags"), lambda: self.edit_tags_requested.emit(self._bm)),
            ("edit-2", _("Edit note"), lambda: self.add_note_requested.emit(self._bm)),
            ("trash", _("Remove bookmark"), lambda: self.remove_requested.emit(self._bm)),
        ]:
            btn = QPushButton()
            btn.setIcon(get_icon(icon_name))
            btn.setToolTip(tooltip)
            btn.setFixedSize(26, 26)
            btn.setObjectName("icon_btn")
            btn.clicked.connect(cb)
            top.addWidget(btn)

        layout.addLayout(top)

        # ── URL ───────────────────────────────────────────────
        url_lbl = QLabel(self._bm.url)
        url_lbl.setObjectName("muted")
        url_lbl.setWordWrap(True)
        url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Suppress the label's built-in right-click menu (text-selection context
        # menu) so the event propagates up to the card's custom context menu.
        url_lbl.setContextMenuPolicy(Qt.NoContextMenu)
        layout.addWidget(url_lbl)

        # ── Tags ──────────────────────────────────────────────
        if self._bm.tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(4)
            tag_row.setContentsMargins(0, 2, 0, 0)
            for tag in self._bm.tags:
                chip = QLabel(f"#{tag}")
                chip.setObjectName("inline_tag")
                tag_row.addWidget(chip)
            tag_row.addStretch()
            layout.addLayout(tag_row)

        # ── Note ─────────────────────────────────────────────
        if self._ann and self._ann.note:
            note_frame = QFrame()
            note_frame.setObjectName("note_frame")
            nf_layout = QHBoxLayout(note_frame)
            nf_layout.setContentsMargins(8, 4, 8, 4)
            note_icon = QLabel()
            note_icon.setPixmap(get_icon("message-square").pixmap(14, 14))
            nf_layout.addWidget(note_icon)
            note_lbl = QLabel(self._ann.note)
            note_lbl.setWordWrap(True)
            note_lbl.setObjectName("note_text")
            nf_layout.addWidget(note_lbl, 1)
            layout.addWidget(note_frame)

        # ── Footer: date ──────────────────────────────────────
        dt = datetime.fromtimestamp(self._bm.bookmarked_at).strftime("%Y-%m-%d %H:%M")
        footer_lbl = QLabel(_("Bookmarked: {dt}").format(dt=dt))
        footer_lbl.setObjectName("muted_small")
        layout.addWidget(footer_lbl)


class BookmarksPage(QWidget):
    """
    Dedicated bookmarks management page.
    Features:
    - Tag sidebar for filtering
    - Search within bookmarks (supports advanced DSL: tag:, domain:, after:, before:, has:note, is:bookmarked)
    - Inline notes display
    - Full CRUD (remove, edit tags, edit note, open, copy URL)
    - Quick-filter chips: All, Has Note
    - Right-click context menu on cards
    - Locate bookmark in tag sidebar
    """

    navigate_to_history = Signal(str)  # url → open history page filtered to that URL
    bookmark_changed = Signal()  # emitted when bookmarks are added/removed/edited

    def __init__(self, db: LocalDatabase, parent=None):
        super().__init__(parent)
        self._db = db
        self._active_tag: str = ""
        self._show_annotated_only: bool = False
        self._search_text: str = ""
        self._cards: list[_BookmarkCard] = []
        self._build_ui()
        self._refresh()

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: tag sidebar ──────────────────────────────────
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

        # ── Right: main area ───────────────────────────────────
        main_area = QWidget()
        ma_layout = QVBoxLayout(main_area)
        ma_layout.setContentsMargins(12, 12, 12, 12)
        ma_layout.setSpacing(8)

        # Search + filter bar
        bar = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_("Search bookmarks… (tag:work, after:2024-01-01, has:note)"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        bar.addWidget(self._search_edit, 1)

        # Quick filter chips
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

        # Count label
        self._count_lbl = QLabel()
        self._count_lbl.setObjectName("muted")
        ma_layout.addWidget(self._count_lbl)

        # Scroll area with cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_container)
        ma_layout.addWidget(scroll, 1)

        splitter.addWidget(main_area)
        splitter.setSizes([180, 600])
        root.addWidget(splitter)

    # ── Data loading ───────────────────────────────────────────

    def _refresh(self):
        """Reload all bookmarks and annotations from DB, re-render cards."""
        self._rebuild_tag_sidebar()
        self._rebuild_cards()

    def _rebuild_tag_sidebar(self):
        self._tag_list.blockSignals(True)
        self._tag_list.clear()

        all_item = QListWidgetItem(get_icon("bookmark"), _("All Bookmarks"))
        all_item.setData(Qt.UserRole, "")
        self._tag_list.addItem(all_item)

        for tag in self._db.get_all_bookmark_tags():
            item = QListWidgetItem(get_icon("tag"), f"#{tag}")
            item.setData(Qt.UserRole, tag)
            self._tag_list.addItem(item)

        # Restore selection
        for i in range(self._tag_list.count()):
            if self._tag_list.item(i).data(Qt.UserRole) == self._active_tag:
                self._tag_list.setCurrentRow(i)
                break
        else:
            self._tag_list.setCurrentRow(0)

        self._tag_list.blockSignals(False)

    def _rebuild_cards(self):
        # Remove old cards
        for card in self._cards:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        # Parse the search query using the advanced DSL parser
        query = parse_query(self._search_text)

        # Determine effective tag: DSL tag: token overrides sidebar selection
        effective_tag = query.bookmark_tag if query.bookmark_tag else self._active_tag

        bookmarks = self._db.get_all_bookmarks(tag=effective_tag)
        annotated_urls = self._db.get_annotated_urls() if (self._show_annotated_only or query.has_annotation) else None
        annotations: dict[str, AnnotationRecord] = {}
        for ann in self._db.get_all_annotations():
            annotations[ann.url] = ann

        keyword = query.keyword.lower()
        visible = 0

        # Insert before the trailing stretch (last item)
        stretch_idx = self._cards_layout.count() - 1

        for bm in bookmarks:
            # Annotation filter (from quick-filter chip OR has:note DSL)
            if (self._show_annotated_only or query.has_annotation) and bm.url not in (annotated_urls or set()):
                continue

            # Domain filter from DSL
            if query.domains:
                bm_domain = _extract_domain(bm.url)
                if not any(d.lower() in bm_domain for d in query.domains):
                    continue

            # Date range filter from DSL
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

            # Keyword search (respects title_only / url_only)
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

            # Exclude terms
            if query.excludes:
                combined = ((bm.title or "") + " " + bm.url).lower()
                if any(ex.lower() in combined for ex in query.excludes):
                    continue

            ann = annotations.get(bm.url)
            card = _BookmarkCard(bm, ann, parent=self._cards_container)
            card.open_requested.connect(self._open_url)
            card.copy_url_requested.connect(lambda u: QApplication.clipboard().setText(u))
            card.edit_tags_requested.connect(self._edit_tags)
            card.add_note_requested.connect(self._edit_note)
            card.remove_requested.connect(self._remove_bookmark)
            card.locate_in_list_requested.connect(self._locate_in_history)

            self._cards_layout.insertWidget(stretch_idx, card)
            stretch_idx += 1
            self._cards.append(card)
            visible += 1

        total = len(bookmarks)
        if visible == total:
            self._count_lbl.setText(_("{n} bookmarks").format(n=total))
        else:
            self._count_lbl.setText(_("{visible} of {total} bookmarks").format(visible=visible, total=total))

    # ── Event handlers ─────────────────────────────────────────

    def _on_tag_selected(self, row: int):
        if row < 0:
            return
        item = self._tag_list.item(row)
        self._active_tag = item.data(Qt.UserRole) if item else ""
        self._rebuild_cards()

    def _on_search_changed(self, text: str):
        self._search_text = text
        self._rebuild_cards()

    def _set_annotated_filter(self, only_annotated: bool):
        self._show_annotated_only = only_annotated
        self._btn_all.setChecked(not only_annotated)
        self._btn_has_note.setChecked(only_annotated)
        self._rebuild_cards()

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
        if ok:
            tags = [t.strip() for t in text.split(",") if t.strip()]
            self._db.update_bookmark_tags(bm.url, tags)
            self.bookmark_changed.emit()
            self._refresh()

    def _edit_note(self, bm: BookmarkRecord):
        existing = self._db.get_annotation(bm.url)
        dlg = AnnotationDialog(bm.url, bm.title or bm.url, existing, parent=self)
        if dlg.exec():
            note = dlg.get_note()
            if note.strip():
                self._db.upsert_annotation(bm.url, note)
            else:
                self._db.delete_annotation(bm.url)
            self.bookmark_changed.emit()
            self._rebuild_cards()

    def _remove_bookmark(self, bm: BookmarkRecord):
        reply = QMessageBox.question(
            self,
            _("Remove Bookmark"),
            _("Remove bookmark for:\n{title}").format(title=bm.title or bm.url),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._db.remove_bookmark(bm.url)
            self.bookmark_changed.emit()
            self._refresh()

    def _locate_in_history(self, bm: BookmarkRecord):
        """Emit signal to navigate to the history page and locate this URL."""
        self.navigate_to_history.emit(bm.url)

    # ── Public API ─────────────────────────────────────────────

    def refresh(self):
        self._refresh()
