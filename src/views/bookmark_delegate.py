# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCharFormat, QTextCursor, QTextDocument
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
    card_rect: QRect
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
    actions_opacity: float = 0.0


# ── Delegate ─────────────────────────────────────────────────────────────────


class BookmarkDelegate(QStyledItemDelegate):
    """Paints BookmarkRecord rows entirely with QPainter — no child widgets."""

    # Layout constants — chosen to match the legacy QFrame card pixel-for-pixel.
    CARD_GUTTER_X = 10
    CARD_GUTTER_Y = 2
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
        self._last_layout_by_row: dict[int, tuple[QRect, _CardLayout]] = {}
        self._action_opacity_by_key: dict[str, float] = {}

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

    def layout_for_row(self, row: int) -> _CardLayout | None:
        cached = self._last_layout_by_row.get(row)
        if cached is None:
            return None
        return cached[1]

    def layout_rect_for_row(self, row: int) -> QRect | None:
        cached = self._last_layout_by_row.get(row)
        if cached is None:
            return None
        return QRect(cached[0])

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

    def action_key_for_row(self, row: int) -> str | None:
        parent = self.parent()
        if parent is None or not hasattr(parent, "model"):
            return None
        model = parent.model()
        if model is None:
            return None
        idx = model.index(row, 0)
        if not idx.isValid():
            return None
        bm = idx.data(BookmarkListModel.BookmarkRole)
        return bm.url if bm is not None else None

    def action_opacity_for_row(self, row: int) -> float:
        key = self.action_key_for_row(row)
        if key is None:
            return 0.0
        return self._action_opacity_by_key.get(key, 0.0)

    def set_action_opacity(self, row: int, opacity: float) -> None:
        key = self.action_key_for_row(row)
        if key is None:
            return
        opacity = max(0.0, min(1.0, float(opacity)))
        if self._action_opacity_by_key.get(key) == opacity:
            return
        self._action_opacity_by_key[key] = opacity
        self._update_row(row)

    def update_row(self, row: int) -> None:
        self._update_row(row)

    def _update_row(self, row: int) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "viewport"):
            try:
                row_rect = self.layout_rect_for_row(row)
                if row_rect is not None:
                    parent.viewport().update(row_rect)
                else:
                    parent.viewport().update()
            except Exception:
                pass

    def clear_action_opacity(self, row: int) -> None:
        key = self.action_key_for_row(row)
        if key is not None and key in self._action_opacity_by_key:
            self._action_opacity_by_key.pop(key, None)
            self._update_row(row)

    def clear_action_opacities_except(self, rows: set[int]) -> None:
        keep_keys = {key for row in rows if (key := self.action_key_for_row(row)) is not None}
        stale_keys = [key for key in self._action_opacity_by_key if key not in keep_keys]
        if not stale_keys:
            return
        for key in stale_keys:
            self._action_opacity_by_key.pop(key, None)
        parent = self.parent()
        if parent is not None and hasattr(parent, "viewport"):
            try:
                parent.viewport().update()
            except Exception:
                pass

    def clear_all_action_opacities(self) -> None:
        if not self._action_opacity_by_key:
            return
        self._action_opacity_by_key.clear()
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
        layout = self._compute_layout(option.rect, option, bm, ann, index.row())
        self._last_layout_by_row[index.row()] = (QRect(option.rect), layout)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # ── Card background + border ──────────────────────────
        self._paint_background(painter, option, layout.card_rect)

        # ── Top row: title + buttons ──────────────────────────
        # Title.
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(option.palette.text().color())
        painter.drawText(layout.title_rect, Qt.AlignLeft | Qt.AlignVCenter, layout.title_text)

        # Action buttons.
        if layout.actions_opacity > 0.0:
            painter.save()
            painter.setOpacity(layout.actions_opacity)
            for i, btn_rect in enumerate(layout.button_rects):
                self._paint_button(painter, option, btn_rect, i, index.row())
            painter.restore()

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
        if event.type() != QEvent.MouseButtonRelease:
            return False
        return False

    def _layout_for_event(
        self,
        row: int,
        option: QStyleOptionViewItem,
        bm: BookmarkRecord,
        ann: AnnotationRecord | None,
    ) -> tuple[QRect, _CardLayout]:
        cached = self._last_layout_by_row.get(row)
        if cached is not None:
            cached_rect, _cached_layout = cached
            if cached_rect == option.rect:
                return cached
        layout = self._compute_layout(option.rect, option, bm, ann, row)
        cached = (QRect(option.rect), layout)
        self._last_layout_by_row[row] = cached
        return cached

    @staticmethod
    def _event_point(event: QEvent):
        """Return event point in viewport coordinates for both Qt5/Qt6 style APIs."""
        if hasattr(event, "position"):
            return event.position().toPoint()
        if hasattr(event, "pos"):
            return event.pos()
        if hasattr(event, "x") and hasattr(event, "y"):
            from PySide6.QtCore import QPoint

            return QPoint(event.x(), event.y())
        raise AttributeError("Unsupported mouse event API")

    # ── Helpers ───────────────────────────────────────────────

    def _cache_key(self, bm: BookmarkRecord, ann: AnnotationRecord | None, width: int) -> tuple:
        ann_sig = (ann.url, ann.updated_at, ann.note) if (ann and ann.note) else None
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
        mixed = QColor(
            (c.red() + mid.red()) // 2,
            (c.green() + mid.green()) // 2,
            (c.blue() + mid.blue()) // 2,
            alpha,
        )
        if self._theme_token != "dark":
            mixed = mixed.darker(112)
            mixed.setAlpha(alpha)
        return mixed

    # ── Layout computation ────────────────────────────────────

    def _compute_layout(
        self,
        rect: QRect,
        option: QStyleOptionViewItem,
        bm: BookmarkRecord,
        ann: AnnotationRecord | None,
        row: int = -1,
    ) -> _CardLayout:
        card_rect = rect.adjusted(self.CARD_GUTTER_X, self.CARD_GUTTER_Y, -self.CARD_GUTTER_X, -self.CARD_GUTTER_Y)
        title_font = QFont(option.font)
        title_font.setBold(True)
        fm_title = self._font_metrics(title_font)
        fm_text = self._font_metrics(option.font)
        small_font = QFont(option.font)
        small_font.setPointSizeF(max(option.font.pointSizeF() - 1, 7.0))
        fm_small = self._font_metrics(small_font)

        inner_left = card_rect.left() + self.PAD_L
        inner_right = card_rect.right() - self.PAD_R
        inner_top = card_rect.top() + self.PAD_T
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
        button_rects: list[QRect] = []
        bx = inner_left + inner_width - self.BTN_SIZE
        for _i in range(self.BTN_COUNT):
            br = QRect(bx, cur_y + (top_h - self.BTN_SIZE) // 2, self.BTN_SIZE, self.BTN_SIZE)
            button_rects.append(br)
            bx -= self.BTN_SIZE + self.BTN_GAP
        button_rects.reverse()  # stored left-to-right matching _BUTTON_SPECS order
        actions_opacity = self._action_opacity_by_key.get(bm.url, 0.0) if row >= 0 else 0.0
        if self._hovered_row >= 0 and row != self._hovered_row:
            actions_opacity = 0.0
        for i, br in enumerate(button_rects):
            if actions_opacity > 0.0:
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
                tags_left = min(chip_rect.left() for chip_rect, _text in tag_chips)
                tags_right = max(chip_rect.right() for chip_rect, _text in tag_chips)
                tags_bottom = max(chip_rect.bottom() for chip_rect, _text in tag_chips)
                tag_area_rect = QRect(tags_left, chip_top, tags_right - tags_left + 1, tags_bottom - chip_top + 1)
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
            doc = self._build_note_doc(option, note_text, text_avail)
            line_h = fm_text.height()
            max_h = line_h * self.NOTE_MAX_LINES
            text_h = min(int(doc.size().height() + 0.9999), max_h)
            note_text_lines = max(1, min(self.NOTE_MAX_LINES, (text_h + line_h - 1) // line_h))
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

        total_height = (cur_y - card_rect.top()) + self.PAD_B + (2 * self.CARD_GUTTER_Y)

        return _CardLayout(
            total_height=total_height,
            card_rect=card_rect,
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
            actions_opacity=actions_opacity,
        )

    @staticmethod
    def _font_metrics(font: QFont):
        from PySide6.QtGui import QFontMetrics

        return QFontMetrics(font)

    # ── Painters ─────────────────────────────────────────────

    def _paint_background(self, painter: QPainter, option: QStyleOptionViewItem, rect: QRect) -> None:
        # Card body.
        if option.state & QStyle.State_Selected:
            base = option.palette.base().color()
            overlay = option.palette.highlight().color()
            base = QColor(
                (base.red() * 5 + overlay.red()) // 6,
                (base.green() * 5 + overlay.green()) // 6,
                (base.blue() * 5 + overlay.blue()) // 6,
            )
        elif option.state & QStyle.State_MouseOver:
            if self._theme_token == "dark":
                base = option.palette.alternateBase().color().lighter(107)
            else:
                base = option.palette.alternateBase().color().darker(106)
        else:
            base = option.palette.base().color()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(base)
        # Card border.
        border = option.palette.mid().color()
        if option.state & QStyle.State_Selected:
            border = QColor(
                (border.red() * 3 + option.palette.highlight().color().red()) // 4,
                (border.green() * 3 + option.palette.highlight().color().green()) // 4,
                (border.blue() * 3 + option.palette.highlight().color().blue()) // 4,
            )
            border.setAlpha(118)
        else:
            border.setAlpha(92)
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
            hover_bg.setAlpha(32)
            painter.setBrush(hover_bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
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
        bg.setAlpha(26)
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
        bg = bg.lighter(102) if self._theme_token == "dark" else bg.darker(103)
        bg.setAlpha(220)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(bg)
        border = option.palette.mid().color()
        border.setAlpha(72)
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
            doc = self._build_note_doc(option, layout.note_text, layout.note_text_rect.width())
            painter.setClipRect(layout.note_text_rect)
            painter.translate(layout.note_text_rect.topLeft())
            doc.drawContents(painter)
            painter.restore()

    def _build_note_doc(self, option: QStyleOptionViewItem, note_html: str, width: int) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        doc.setTextWidth(max(1, width))
        text_color = option.palette.text().color().name()
        link_color = option.palette.link().color().name()
        font_family = option.font.family().replace("'", "\\'")
        font_size = option.font.pointSize()
        doc.setDefaultStyleSheet(
            f"body, p, div, span {{ color: {text_color} !important; }} "
            f"a {{ color: {link_color} !important; }} "
            f"* {{ font-family: '{font_family}'; font-size: {font_size}pt; }}"
        )
        doc.setHtml(note_html)
        fmt = QTextCharFormat()
        fmt.setForeground(option.palette.text().color())
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        cursor.mergeCharFormat(fmt)
        return doc


__all__ = ["BookmarkDelegate"]
