# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
QStyledItemDelegate that paints a single bookmark row entirely with QPainter.

The delegate is the entire "view of one bookmark"; combined with QListView's
viewport-only painting, the application memory cost of the bookmark page is
O(visible rows) regardless of how many bookmarks the user has stored.

Visual layout (matches the legacy QFrame card):

    +------------------------------------------------------------+
    | <bold title>                              [O][T][N][L][R]  |  ^ top row
    | <muted url, single-line, ellipsised>                       |  | url
    | #tag1  #tag2  #tag3                                        |  | tags (wrap)
    | [ ][note text wrapped to two lines max]                    |  | note (opt.)
    | Bookmarked: 2026-05-25 14:30                               |  v footer
    +------------------------------------------------------------+

Action regions
--------------

The layout pass also builds a list of *clickable hit boxes*; on a mouse
release event the delegate looks up which box was hit and emits
``action_requested(name, BookmarkRecord)``.  Names map 1:1 to the slots the
page wires up:

    open / edit_tags / edit_note / locate / remove / title / tag_area / note

Size caching
------------

`sizeHint` is called by QListView whenever the layout needs to know a row's
height (scrollbar adjustment, paint, scroll-by-pixel computation).  The
result is cached by ``(url, width, ann_signature, tags_tuple, theme)`` so
repeated calls during scrolling are O(1).  The cache is cleared whenever
the theme changes or the delegate is asked to invalidate.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from src.models.history_record import AnnotationRecord, BookmarkRecord
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.theme_manager import ThemeManager
from src.views.bookmark_list_model import BookmarkListModel

# ── Layout types ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _HitBox:
    """A clickable rectangle inside a card."""

    name: str
    rect: QRect


@dataclass(slots=True)
class _CardLayout:
    """All geometry needed to both paint and hit-test a card."""

    total_height: int
    title_rect: QRect
    title_text: str  # already elided
    url_rect: QRect
    url_text: str  # already elided
    button_rects: list[QRect] = field(default_factory=list)
    tag_chips: list[tuple[QRect, str]] = field(default_factory=list)  # (chip_rect, "#tag")
    tag_area_rect: QRect | None = None
    note_rect: QRect | None = None
    note_icon_rect: QRect | None = None
    note_text_rect: QRect | None = None
    note_text: str = ""
    note_text_lines: int = 1
    footer_rect: QRect = field(default_factory=QRect)
    footer_text: str = ""
    hit_boxes: list[_HitBox] = field(default_factory=list)


# ── Delegate ─────────────────────────────────────────────────────────────────


class BookmarkDelegate(QStyledItemDelegate):
    """Paints BookmarkRecord rows entirely with QPainter — no child widgets."""

    # Layout constants — chosen to match the legacy QFrame card pixel-for-pixel.
    PAD_L = 12
    PAD_T = 10
    PAD_R = 12
    PAD_B = 10
    SPACING = 4
    BTN_SIZE = 26
    BTN_GAP = 4
    BTN_COUNT = 5
    BTN_TITLE_GAP = 8
    BTN_ICON_PX = 16
    CHIP_PAD_H = 8
    CHIP_PAD_V = 2
    CHIP_GAP = 4
    CHIP_RADIUS = 8
    NOTE_PAD_H = 8
    NOTE_PAD_V = 6
    NOTE_ICON_W = 14
    NOTE_ICON_GAP = 6
    NOTE_MAX_LINES = 3
    NOTE_RADIUS = 4
    CARD_RADIUS = 6
    CARD_BORDER_W = 1

    # Action ordering & icons match the original BookmarkCard top-row buttons.
    # button_id is what goes into action_requested.emit(button_id, bm).
    _BUTTON_SPECS: tuple[tuple[str, str, str], ...] = (
        ("open", "corner-up-right", "Open in browser"),
        ("edit_tags", "tag", "Edit tags"),
        ("edit_note", "edit-2", "Edit note"),
        ("locate", "crosshair", "Locate in History"),
        ("remove", "trash", "Remove bookmark"),
    )

    # Cache size before LRU eviction kicks in.  ~2000 entries × ~160 B ≈ 320 KB.
    _SIZE_CACHE_MAX = 2000

    # Names of clickable hit-boxes (besides buttons) — used by the page to
    # map to slots cleanly.  The button names above are also valid actions.
    ACTION_TITLE = "title"
    ACTION_TAG_AREA = "tag_area"
    ACTION_NOTE = "note"
    ACTION_OPEN = "open"
    ACTION_EDIT_TAGS = "edit_tags"
    ACTION_EDIT_NOTE = "edit_note"
    ACTION_LOCATE = "locate"
    ACTION_REMOVE = "remove"

    # Emitted when the user clicks a sub-region of a card.
    action_requested = Signal(str, object)  # (action, BookmarkRecord)
    # Emitted when the user activates a card via Enter/double-click anywhere.
    activated = Signal(object)  # BookmarkRecord

    def __init__(self, parent=None):
        super().__init__(parent)
        # Layout/geometry cache: key -> (height, _CardLayout-bytes-equivalent isn't cached;
        # only sizeHint heights are cached because layout for paint is cheap to recompute).
        self._height_cache: OrderedDict[tuple, int] = OrderedDict()
        self._theme_token: str = ""
        self._refresh_theme_resources()
        try:
            ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        except Exception:
            # ThemeManager may not be initialised in headless tests; ignore.
            pass
        # Hovered (row, button_index) pair, used for per-button highlight.
        self._hovered_row: int = -1
        self._hovered_button: int = -1

    # ── Theme handling ────────────────────────────────────────

    def _on_theme_changed(self, resolved: str) -> None:
        self._theme_token = resolved
        self._refresh_theme_resources()
        self._height_cache.clear()
        # Trigger a repaint of the whole view if we have a viewport reference.
        parent = self.parent()
        if parent is not None and hasattr(parent, "viewport"):
            try:
                parent.viewport().update()
            except Exception:
                pass

    def _refresh_theme_resources(self) -> None:
        """Pre-build per-theme resources (icons, colours) for cheap paint."""
        try:
            tm = ThemeManager.instance()
            self._theme_token = tm.current
            default_color = tm.icon_default_color()
            active_color = tm.icon_active_color()
        except Exception:
            self._theme_token = "dark"
            default_color = "#a0a8b8"
            active_color = "#5b9cf6"
        self._default_icon_color = default_color
        self._active_icon_color = active_color
        self._button_icons: list[tuple[str, str, str, object, object]] = []
        for button_id, icon_name, tooltip in self._BUTTON_SPECS:
            icon = get_icon(icon_name, self.BTN_ICON_PX, default_color)
            icon_active = get_icon(icon_name, self.BTN_ICON_PX, active_color)
            self._button_icons.append((button_id, icon_name, tooltip, icon, icon_active))
        self._note_marker_icon = get_icon("message-square", self.NOTE_ICON_W, default_color)

    def invalidate_cache(self) -> None:
        """Clear the size cache (e.g. after font change)."""
        self._height_cache.clear()

    # ── Hover tracking ────────────────────────────────────────

    def set_hover(self, row: int, button_index: int) -> None:
        """Update which (row, button) is currently under the cursor."""
        if (row, button_index) == (self._hovered_row, self._hovered_button):
            return
        self._hovered_row = row
        self._hovered_button = button_index
        parent = self.parent()
        if parent is not None and hasattr(parent, "viewport"):
            try:
                parent.viewport().update()
            except Exception:
                pass

    # ── QStyledItemDelegate API ───────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        bm: BookmarkRecord | None = index.data(BookmarkListModel.BookmarkRole)
        if bm is None:
            return
        ann: AnnotationRecord | None = index.data(BookmarkListModel.AnnotationRole)
        rect = option.rect
        layout = self._compute_layout(rect, option, bm, ann)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # ── Card background + border ──────────────────────────
        self._paint_background(painter, option, rect)

        # ── Top row: title + buttons ──────────────────────────
        # Title.
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(option.palette.text().color())
        painter.drawText(layout.title_rect, Qt.AlignLeft | Qt.AlignVCenter, layout.title_text)

        # Action buttons.
        for i, btn_rect in enumerate(layout.button_rects):
            self._paint_button(painter, option, btn_rect, i, index.row())

        # ── URL line ──────────────────────────────────────────
        painter.setFont(option.font)
        muted = self._muted_color(option)
        painter.setPen(muted)
        painter.drawText(layout.url_rect, Qt.AlignLeft | Qt.AlignVCenter, layout.url_text)

        # ── Tag chips ────────────────────────────────────────
        if layout.tag_chips:
            self._paint_tag_chips(painter, option, layout.tag_chips)

        # ── Note frame ───────────────────────────────────────
        if layout.note_rect is not None and layout.note_text_rect is not None:
            self._paint_note(painter, option, layout)

        # ── Footer date ──────────────────────────────────────
        small_font = QFont(option.font)
        small_font.setPointSizeF(max(option.font.pointSizeF() - 1, 7.0))
        painter.setFont(small_font)
        painter.setPen(self._muted_color(option, alpha=180))
        painter.drawText(layout.footer_rect, Qt.AlignLeft | Qt.AlignVCenter, layout.footer_text)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        bm: BookmarkRecord | None = index.data(BookmarkListModel.BookmarkRole)
        if bm is None:
            return QSize(0, 0)
        ann: AnnotationRecord | None = index.data(BookmarkListModel.AnnotationRole)
        width = option.rect.width()
        if width <= 0 and option.widget is not None:
            try:
                width = option.widget.viewport().width()  # type: ignore[attr-defined]
            except Exception:
                width = 0
        if width <= 0:
            width = 480  # safe fallback so Qt's first sizing pass doesn't return 0

        cache_key = self._cache_key(bm, ann, width)
        cached = self._height_cache.get(cache_key)
        if cached is not None:
            self._height_cache.move_to_end(cache_key)
            return QSize(width, cached)

        layout = self._compute_layout(QRect(0, 0, width, 1), option, bm, ann)
        height = layout.total_height
        self._height_cache[cache_key] = height
        if len(self._height_cache) > self._SIZE_CACHE_MAX:
            self._height_cache.popitem(last=False)
        return QSize(width, height)

    def editorEvent(self, event: QEvent, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        """Handle clicks on sub-regions and emit ``action_requested``.

        Returning True consumes the event so the view does not also process it
        (which would otherwise toggle the row's selected state on every click
        of a button — visually noisy).
        """
        if event.type() not in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        bm: BookmarkRecord | None = index.data(BookmarkListModel.BookmarkRole)
        if bm is None:
            return False
        if event.button() != Qt.LeftButton:
            return False

        ann: AnnotationRecord | None = index.data(BookmarkListModel.AnnotationRole)
        layout = self._compute_layout(option.rect, option, bm, ann)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()

        if event.type() == QEvent.MouseButtonDblClick:
            # Double-click anywhere activates the bookmark (open in browser).
            self.activated.emit(bm)
            return True

        for hit in layout.hit_boxes:
            if hit.rect.contains(pos):
                self.action_requested.emit(hit.name, bm)
                return True
        return False

    # ── Helpers ───────────────────────────────────────────────

    def _cache_key(self, bm: BookmarkRecord, ann: AnnotationRecord | None, width: int) -> tuple:
        ann_sig = (ann.url, ann.updated_at, len(ann.note)) if (ann and ann.note) else None
        return (
            bm.url,
            width,
            bm.title,
            tuple(bm.tags),
            ann_sig,
            self._theme_token,
        )

    def _muted_color(self, option: QStyleOptionViewItem, alpha: int = 220) -> QColor:
        """Return a muted text colour suitable for URL/footer text."""
        c = QColor(option.palette.text().color())
        c.setAlpha(alpha)
        # Mix toward palette mid for a softer look.
        mid = option.palette.mid().color()
        return QColor(
            (c.red() + mid.red()) // 2,
            (c.green() + mid.green()) // 2,
            (c.blue() + mid.blue()) // 2,
            alpha,
        )

    # ── Layout computation ────────────────────────────────────

    def _compute_layout(
        self,
        rect: QRect,
        option: QStyleOptionViewItem,
        bm: BookmarkRecord,
        ann: AnnotationRecord | None,
    ) -> _CardLayout:
        title_font = QFont(option.font)
        title_font.setBold(True)
        fm_title = self._font_metrics(title_font)
        fm_text = self._font_metrics(option.font)
        small_font = QFont(option.font)
        small_font.setPointSizeF(max(option.font.pointSizeF() - 1, 7.0))
        fm_small = self._font_metrics(small_font)

        inner_left = rect.left() + self.PAD_L
        inner_right = rect.right() - self.PAD_R
        inner_top = rect.top() + self.PAD_T
        inner_width = max(0, inner_right - inner_left)

        cur_y = inner_top
        hit_boxes: list[_HitBox] = []

        # ── Top row: title (left) + 5 buttons (right) ──
        btn_strip_w = self.BTN_COUNT * self.BTN_SIZE + (self.BTN_COUNT - 1) * self.BTN_GAP
        title_avail = max(0, inner_width - btn_strip_w - self.BTN_TITLE_GAP)
        title_h = fm_title.height()
        top_h = max(title_h, self.BTN_SIZE)
        title_text = bm.title.strip() if bm.title and bm.title.strip() else bm.url
        title_elided = fm_title.elidedText(title_text, Qt.ElideRight, title_avail)
        title_rect = QRect(
            inner_left,
            cur_y + (top_h - title_h) // 2,
            title_avail,
            title_h,
        )
        hit_boxes.append(_HitBox(self.ACTION_OPEN, title_rect))

        button_rects: list[QRect] = []
        bx = inner_left + inner_width - self.BTN_SIZE
        for _i in range(self.BTN_COUNT):
            br = QRect(bx, cur_y + (top_h - self.BTN_SIZE) // 2, self.BTN_SIZE, self.BTN_SIZE)
            button_rects.append(br)
            bx -= self.BTN_SIZE + self.BTN_GAP
        button_rects.reverse()  # stored left-to-right matching _BUTTON_SPECS order
        for i, br in enumerate(button_rects):
            hit_boxes.append(_HitBox(self._BUTTON_SPECS[i][0], br))

        cur_y += top_h + self.SPACING

        # ── URL line ──
        url_h = fm_text.height()
        url_text = fm_text.elidedText(bm.url, Qt.ElideRight, inner_width)
        url_rect = QRect(inner_left, cur_y, inner_width, url_h)
        cur_y += url_h + self.SPACING

        # ── Tag chips (wrap into multiple rows if needed) ──
        tag_chips: list[tuple[QRect, str]] = []
        tag_area_rect: QRect | None = None
        if bm.tags:
            chip_h = fm_small.height() + 2 * self.CHIP_PAD_V
            cx = inner_left
            cy = cur_y
            chip_top = cy
            for tag in bm.tags:
                if not tag:
                    continue
                text = f"#{tag}"
                chip_w = fm_small.horizontalAdvance(text) + 2 * self.CHIP_PAD_H
                if cx > inner_left and cx + chip_w > inner_right:
                    cx = inner_left
                    cy += chip_h + 2  # vertical gap between chip rows
                tag_chips.append((QRect(cx, cy, chip_w, chip_h), text))
                cx += chip_w + self.CHIP_GAP
            if tag_chips:
                tags_bottom = tag_chips[-1][0].bottom()
                tag_area_rect = QRect(inner_left, chip_top, inner_width, tags_bottom - chip_top + 1)
                hit_boxes.append(_HitBox(self.ACTION_TAG_AREA, tag_area_rect))
                cur_y = tags_bottom + 1 + self.SPACING

        # ── Note frame ──
        note_rect: QRect | None = None
        note_icon_rect: QRect | None = None
        note_text_rect: QRect | None = None
        note_text = ""
        note_text_lines = 1
        if ann is not None and ann.note and ann.note.strip():
            note_text = ann.note.strip()
            text_avail = max(40, inner_width - 2 * self.NOTE_PAD_H - self.NOTE_ICON_W - self.NOTE_ICON_GAP)
            # Multi-line bounding box with word wrap.
            bb = fm_text.boundingRect(
                QRect(0, 0, text_avail, 100000),
                Qt.TextWordWrap,
                note_text,
            )
            line_h = fm_text.height()
            max_h = line_h * self.NOTE_MAX_LINES
            note_text_lines = max(1, min(self.NOTE_MAX_LINES, (bb.height() + line_h - 1) // line_h))
            text_h = min(bb.height(), max_h)
            frame_h = text_h + 2 * self.NOTE_PAD_V
            note_rect = QRect(inner_left, cur_y, inner_width, frame_h)
            note_icon_rect = QRect(
                inner_left + self.NOTE_PAD_H,
                cur_y + (frame_h - self.NOTE_ICON_W) // 2,
                self.NOTE_ICON_W,
                self.NOTE_ICON_W,
            )
            note_text_rect = QRect(
                inner_left + self.NOTE_PAD_H + self.NOTE_ICON_W + self.NOTE_ICON_GAP,
                cur_y + self.NOTE_PAD_V,
                text_avail,
                text_h,
            )
            hit_boxes.append(_HitBox(self.ACTION_NOTE, note_rect))
            cur_y += frame_h + self.SPACING

        # ── Footer ──
        footer_h = fm_small.height()
        footer_text = ""
        try:
            dt = datetime.fromtimestamp(int(bm.bookmarked_at)).strftime("%Y-%m-%d %H:%M")
            footer_text = _("Bookmarked: {dt}").format(dt=dt)
        except (ValueError, OSError, OverflowError):
            footer_text = ""
        footer_rect = QRect(inner_left, cur_y, inner_width, footer_h)
        cur_y += footer_h

        total_height = cur_y - rect.top() + self.PAD_B

        return _CardLayout(
            total_height=total_height,
            title_rect=title_rect,
            title_text=title_elided,
            url_rect=url_rect,
            url_text=url_text,
            button_rects=button_rects,
            tag_chips=tag_chips,
            tag_area_rect=tag_area_rect,
            note_rect=note_rect,
            note_icon_rect=note_icon_rect,
            note_text_rect=note_text_rect,
            note_text=note_text,
            note_text_lines=note_text_lines,
            footer_rect=footer_rect,
            footer_text=footer_text,
            hit_boxes=hit_boxes,
        )

    @staticmethod
    def _font_metrics(font: QFont):
        from PySide6.QtGui import QFontMetrics

        return QFontMetrics(font)

    # ── Painters ─────────────────────────────────────────────

    def _paint_background(self, painter: QPainter, option: QStyleOptionViewItem, rect: QRect) -> None:
        # Card body.
        if option.state & QStyle.State_Selected:
            base = option.palette.highlight().color()
            base.setAlpha(60)
        elif option.state & QStyle.State_MouseOver:
            base = option.palette.alternateBase().color()
        else:
            base = option.palette.base().color()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(base)
        # Card border.
        border = option.palette.mid().color()
        border.setAlpha(110 if (option.state & QStyle.State_Selected) else 70)
        pen = QPen(border, self.CARD_BORDER_W)
        painter.setPen(pen)
        body = rect.adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(body, self.CARD_RADIUS, self.CARD_RADIUS)
        painter.restore()

    def _paint_button(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        rect: QRect,
        button_index: int,
        row: int,
    ) -> None:
        is_hovered = self._hovered_row == row and self._hovered_button == button_index
        if is_hovered:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            hover_bg = option.palette.highlight().color()
            hover_bg.setAlpha(45)
            painter.setBrush(hover_bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 4, 4)
            painter.restore()
        _, _icon_name, _tooltip, icon, icon_active = self._button_icons[button_index]
        icon_to_use = icon_active if is_hovered else icon
        icon_size = self.BTN_ICON_PX
        ix = rect.left() + (rect.width() - icon_size) // 2
        iy = rect.top() + (rect.height() - icon_size) // 2
        target = QRect(ix, iy, icon_size, icon_size)
        icon_to_use.paint(painter, target, Qt.AlignCenter)

    def _paint_tag_chips(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        chips: list[tuple[QRect, str]],
    ) -> None:
        small_font = QFont(option.font)
        small_font.setPointSizeF(max(option.font.pointSizeF() - 1, 7.0))
        painter.setFont(small_font)
        # Chip colours: tinted accent.
        accent = QColor(self._active_icon_color)
        bg = QColor(accent)
        bg.setAlpha(38)
        text_color = QColor(accent)
        text_color.setAlpha(255)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for chip_rect, text in chips:
            painter.setBrush(bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(chip_rect, self.CHIP_RADIUS, self.CHIP_RADIUS)
            painter.setPen(text_color)
            painter.drawText(chip_rect, Qt.AlignCenter, text)
        painter.restore()

    def _paint_note(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        layout: _CardLayout,
    ) -> None:
        # Note frame background.
        bg = option.palette.alternateBase().color()
        # Slightly more opaque than alternateBase for visibility.
        bg.setAlpha(180)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(bg)
        border = option.palette.mid().color()
        border.setAlpha(60)
        painter.setPen(QPen(border, 1))
        if layout.note_rect is not None:
            painter.drawRoundedRect(layout.note_rect, self.NOTE_RADIUS, self.NOTE_RADIUS)
        painter.restore()

        # Note icon.
        if layout.note_icon_rect is not None:
            self._note_marker_icon.paint(painter, layout.note_icon_rect, Qt.AlignCenter)

        # Note text — multi-line wrapped with elision on the last line if it overflows.
        if layout.note_text_rect is not None:
            painter.save()
            painter.setPen(option.palette.text().color())
            painter.setFont(option.font)
            text = layout.note_text
            if layout.note_text_lines >= self.NOTE_MAX_LINES:
                # Add ellipsis if the rendered height would exceed.
                fm = self._font_metrics(option.font)
                avail_w = layout.note_text_rect.width()
                # Greedy line-wrap up to NOTE_MAX_LINES; elide final line if needed.
                lines = self._wrap_lines(text, fm, avail_w, self.NOTE_MAX_LINES)
                for i, line in enumerate(lines):
                    line_rect = QRect(
                        layout.note_text_rect.left(),
                        layout.note_text_rect.top() + i * fm.height(),
                        avail_w,
                        fm.height(),
                    )
                    painter.drawText(line_rect, Qt.AlignLeft | Qt.AlignVCenter, line)
            else:
                painter.drawText(layout.note_text_rect, Qt.TextWordWrap | Qt.AlignLeft, text)
            painter.restore()

    @staticmethod
    def _wrap_lines(text: str, fm, avail: int, max_lines: int) -> list[str]:
        """Greedy word-wrap that elides the last line when *text* overflows."""
        if avail <= 0 or max_lines <= 0:
            return []
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        cur = ""
        for w in words:
            candidate = w if not cur else cur + " " + w
            if fm.horizontalAdvance(candidate) <= avail:
                cur = candidate
            else:
                if cur:
                    lines.append(cur)
                if len(lines) == max_lines - 1:
                    # Build the last line greedily out of the remaining words.
                    remainder = " ".join([w, *words[words.index(w) + 1 :]])
                    lines.append(fm.elidedText(remainder, Qt.ElideRight, avail))
                    return lines
                if fm.horizontalAdvance(w) <= avail:
                    cur = w
                else:
                    lines.append(fm.elidedText(w, Qt.ElideRight, avail))
                    cur = ""
                    if len(lines) >= max_lines:
                        return lines[:max_lines]
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = [
                *lines[: max_lines - 1],
                fm.elidedText(lines[max_lines - 1], Qt.ElideRight, avail),
            ]
        return lines


__all__ = ["BookmarkDelegate"]
