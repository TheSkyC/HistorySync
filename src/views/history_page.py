# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import time as _time
from urllib.parse import urlparse
import webbrowser

from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QEvent,
    QItemSelectionModel,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDrag,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateEdit,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionSlider,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.models.history_record import BookmarkRecord
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_browser_icon, get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.styled_combobox import StyledComboBox
from src.utils.styled_menu import StyledMenu
from src.utils.theme_manager import ThemeManager
from src.viewmodels.history_viewmodel import ANNOTATION_ROLE, BOOKMARK_ROLE, PAGE_SIZE, HistoryViewModel
from src.views.annotation_dialog import AnnotationDialog
from src.views.dialogs.hide_domain_dialog import HideDomainDialog
from src.views.history_page_layout import (
    _ROW_H,
    _separator_band_rect,
    _separator_content_rect,
)
from src.views.search_autocomplete import SmartSearchLineEdit


def _extract_main_domain(host: str) -> str:
    """Heuristically extract eTLD+1 from *host* without an external library.

    Handles common two-part ccTLD/SLD patterns (co.uk, com.au, org.uk …) by
    checking whether the second-to-last label is a well-known SLD and the TLD
    is a two-letter country code.  Falls back to the last two labels for all
    other cases.

    Examples::

        mail.google.com  →  google.com
        api.github.com   →  github.com
        bbc.co.uk        →  bbc.co.uk
        example.com      →  example.com  (already eTLD+1)
    """
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    _COMMON_SLD = {"co", "com", "org", "net", "gov", "edu", "ac", "ne", "or", "ltd", "plc"}
    if len(parts) >= 3 and parts[-2] in _COMMON_SLD and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


log = get_logger("view.history")


class _CustomScrollBar(QScrollBar):
    """QScrollBar with custom context menu for bubble display mode."""

    context_menu_requested = Signal(QPoint)  # global position

    def contextMenuEvent(self, event):
        """Override to disable default menu and emit custom signal."""
        self.context_menu_requested.emit(event.globalPos())
        event.accept()  # Prevent default menu


# Weekday abbreviations for scroll bubble — N_() marks for extraction, _() translates at display time
_WEEKDAY_ABBR = [
    N_("Mon"),
    N_("Tue"),
    N_("Wed"),
    N_("Thu"),
    N_("Fri"),
    N_("Sat"),
    N_("Sun"),
]

# Full weekday names for date-separator headers
_WEEKDAY_FULL = [
    N_("Monday"),
    N_("Tuesday"),
    N_("Wednesday"),
    N_("Thursday"),
    N_("Friday"),
    N_("Saturday"),
    N_("Sunday"),
]


def _format_separator_date(ts: int) -> str:
    """Return a human-readable date label for the separator strip.

    Graduated relative-time tiers, nearest first:

    · Today                  → "Today"
    · Yesterday              → "Yesterday"
    · 2-6 days ago           → weekday name only, e.g. "Monday"
    · 7-13 days ago          → "Last Monday"
    · Same calendar year     → e.g. "Oct 24  Wednesday"
    · Earlier year           → e.g. "2023  Oct 24  Wednesday"

    Format strings are translatable so each locale can rearrange tokens.
    """
    lt = _time.localtime(ts)
    record_ymd = (lt.tm_year, lt.tm_mon, lt.tm_mday)
    today_lt = _time.localtime()
    today_ymd = (today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday)

    if record_ymd == today_ymd:
        return _("Today")

    # Use Julian day number for fast day-difference calculation
    today_lt.tm_yday - lt.tm_yday + (today_lt.tm_year - lt.tm_year) * 365
    # Rough approximation is fine for <= 13 days; for larger spans we use month/year
    if today_lt.tm_year == lt.tm_year:
        exact_days = today_lt.tm_yday - lt.tm_yday
    else:
        # Cross-year boundary: compute from date objects only when needed
        exact_days = (
            date(today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday) - date(lt.tm_year, lt.tm_mon, lt.tm_mday)
        ).days

    weekday = _(_WEEKDAY_FULL[lt.tm_wday])

    if exact_days == 1:
        return _("Yesterday")
    if exact_days < 7:
        return _("{weekday}").format(weekday=weekday)
    if exact_days < 14:
        return _("Last {weekday}").format(weekday=weekday)
    if lt.tm_year == today_lt.tm_year:
        return _("{month}/{day}  {weekday}").format(month=lt.tm_mon, day=lt.tm_mday, weekday=weekday)
    return _("{year}/{month}/{day}  {weekday}").format(
        year=lt.tm_year, month=lt.tm_mon, day=lt.tm_mday, weekday=weekday
    )


# ── Fast local-day-number for separator detection ─────────────────────────────
# Pure integer arithmetic: (unix_ts + utc_offset) // 86400.  Avoids all Python
# date/datetime/struct_time object construction.
# The offset is refreshed lazily (every ~3600 calls) to catch DST transitions.
_day_offset: list[int] = [-(_time.altzone if _time.daylight and _time.localtime().tm_isdst else _time.timezone)]
_day_offset_counter: list[int] = [0]


def _local_day_number(ts: int) -> int:
    """Return a local calendar day number for *ts* (seconds since epoch)."""
    _day_offset_counter[0] += 1
    if _day_offset_counter[0] >= 3600:
        _day_offset_counter[0] = 0
        _day_offset[0] = -(_time.altzone if _time.daylight and _time.localtime().tm_isdst else _time.timezone)
    return (ts + _day_offset[0]) // 86400


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


class _DateSeparatorDelegate(QStyledItemDelegate):
    """Table-wide delegate that injects a Telegram-style date-separator strip
    at the top of every first-of-day row.

    Separator pills are a presentation-only overlay. Rows keep a fixed
    height and the delegate paints the date pill in the top area of column 0
    for first-of-day rows.

    ``separator_rows`` is a ``dict[int, int]`` mapping row_index → visit_time.
    The visit_time is stored at row-height assignment time so that paint() never
    needs to call model.data() to build the pill label — eliminating the most
    expensive call on the hot paint path.
    """

    def __init__(
        self,
        separator_rows: dict[int, int],
        sep_counts: dict[int, int],
        sub_delegate: QStyledItemDelegate | None = None,
        sub_col: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._sep_rows = separator_rows
        self._sep_counts = sep_counts  # row → visit count (populated lazily)
        self._sub = sub_delegate  # delegate used for sub_col (title column)
        self._sub_col = sub_col

        # ── Theme color cache ─────────────────────────────────────────────────
        # Avoids calling ThemeManager.instance().current on every paint() call.
        self._cached_theme: str = ""
        self._pill_bg = QColor(0, 0, 0, 14)
        self._pill_border = QColor(0, 0, 0, 28)
        self._pill_text_color = QColor(90, 100, 120)
        self._count_pill_bg = QColor(0, 0, 0, 9)
        self._count_pill_text_color = QColor(120, 130, 150)
        self._refresh_theme_cache()

        # ── Pill geometry cache ───────────────────────────────────────────────
        # Maps (prefix, label) → (pill_w, pill_h) so that horizontalAdvance()
        # and QFontMetrics construction are skipped on repeated paint calls for
        # the same date/count.  Cleared when the font or theme changes.
        self._geometry_cache: dict[tuple, tuple[int, int]] = {}
        self._pill_font: QFont | None = None
        self._pill_fm: QFontMetrics | None = None
        self._base_font_key: str = ""

        # ── Date-label cache ──────────────────────────────────────────────────
        # Maps visit_time (int, seconds) → formatted date string.
        # _format_separator_date() builds locale-aware strings; caching avoids
        # calling it on every paint() tick for the same separator row.
        # Keyed on (visit_time_day_bucket, today_date) so the cache auto-
        # invalidates at midnight without an explicit purge.
        self._date_label_cache: dict[tuple, str] = {}
        # Stored as an integer day-bucket (unix_seconds // 86400) instead of a
        # date object — avoids constructing a Python date on every paint call.
        self._date_label_cache_today: int = -1

        # ── QPainterPath cache ────────────────────────────────────────────────
        # Keyed on (width, height) → QPainterPath positioned at (0,0).
        # Avoids re-creating QPainterPath + addRoundedRect on every pill paint.
        self._path_cache: dict[tuple[int, int], QPainterPath] = {}

        # ── Cached QPen for pill border ───────────────────────────────────────
        # Creating QPen(QColor, float) on every _draw_pill_fast call showed up
        # in profiling.  Cache it once; rebuilt on theme change.
        self._border_pen = QPen(self._pill_border, 0.8)

        # ── Paint-loop counters & cached translations ─────────────────────────
        self._today_check_counter: int = 0
        self._count_fmt: str = _("{count} visits")

        # ── Connect theme signal so we never need to poll ThemeManager ────────
        try:
            ThemeManager.instance().theme_changed.connect(self._on_theme_switched)
        except Exception:
            pass  # during unit tests ThemeManager may not be fully initialized

    # ── QStyledItemDelegate interface ─────────────────────────────────────────

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = index.row()
        visit_time = self._sep_rows.get(row)  # None → not a separator row

        if visit_time is None:
            # Inline _paint_cell for the common non-separator path to avoid
            # function call overhead (called ~10k times during fast scroll).
            col = index.column()
            if col == self._sub_col and self._sub is not None:
                self._sub.paint(painter, option, index)
            else:
                super().paint(painter, option, index)
            return

        # Paint the full-row background first so the separator band keeps the
        # correct selection/hover styling even though the content is shifted.
        self._paint_cell_background(painter, option, index)

        # Paint the actual cell content in the lower inset rect.
        col = index.column()
        content_option = self._adjust_option_for_sep(option, index)
        if col == self._sub_col and self._sub is not None:
            self._sub.paint(painter, content_option, index)
        else:
            super().paint(painter, content_option, index)

        # Paint the date pill only once — in column 0 (leftmost visible cell).
        if col == 0:
            base_font = painter.font()
            self._paint_separator_pill(painter, _separator_band_rect(option.rect), visit_time, row)
            painter.setFont(base_font)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _refresh_theme_cache(self) -> None:
        """Rebuild cached QColor objects when the active theme changes.

        Now a no-op on the hot path — actual rebuild is driven by the
        theme_changed signal via _on_theme_switched().  The initial call
        from __init__ triggers the full rebuild because _cached_theme
        starts empty.
        """
        if self._cached_theme:
            return  # already initialized; signal-driven from here
        self._do_rebuild_theme()

    def _on_theme_switched(self, _theme_name: str = "") -> None:
        """Slot connected to ThemeManager.theme_changed."""
        self._cached_theme = ""  # force rebuild on next call
        self._do_rebuild_theme()

    def _do_rebuild_theme(self) -> None:
        """Actually rebuild all cached theme colors and pens."""
        theme = ThemeManager.instance().current
        if theme == self._cached_theme:
            return
        self._cached_theme = theme
        if theme == "dark":
            self._pill_bg = QColor(255, 255, 255, 22)
            self._pill_border = QColor(255, 255, 255, 38)
            self._pill_text_color = QColor(200, 208, 230)
            self._count_pill_bg = QColor(255, 255, 255, 14)
            self._count_pill_text_color = QColor(160, 170, 190)
        else:
            self._pill_bg = QColor(0, 0, 0, 14)
            self._pill_border = QColor(0, 0, 0, 28)
            self._pill_text_color = QColor(90, 100, 120)
            self._count_pill_bg = QColor(0, 0, 0, 9)
            self._count_pill_text_color = QColor(120, 130, 150)
        self._border_pen = QPen(self._pill_border, 0.8)

    def _get_pill_font_and_fm(self, painter_font: QFont) -> tuple[QFont, QFontMetrics]:
        """Return a cached (QFont, QFontMetrics) pair for the pill text.

        Keyed on the painter's base font family + point size so it survives
        DPI or preference changes, but is only rebuilt when the font actually
        changes (rare during a session).  Clears _geometry_cache on rebuild so
        old pill widths measured with the previous font are discarded.

        Note: id(painter_font) is NOT used as a fast-path because painter.font()
        returns a new Python wrapper object on every call, so the id() always
        differs.  The f-string key is cheap (~1µs) and only evaluated once per
        paint call.
        """
        font_key = f"{painter_font.family()}:{painter_font.pointSizeF():.2f}"
        if font_key != self._base_font_key or self._pill_font is None:
            self._base_font_key = font_key
            font = QFont(painter_font)
            font.setPointSizeF(max(painter_font.pointSizeF() * 0.82, 7.5))
            font.setWeight(QFont.Weight.Medium)
            self._pill_font = font
            self._pill_fm = QFontMetrics(font)
            self._geometry_cache.clear()
        return self._pill_font, self._pill_fm  # type: ignore[return-value]

    def _paint_cell(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Delegate actual cell painting to sub_delegate (title col) or Qt default."""
        if index.column() == self._sub_col and self._sub is not None:
            self._sub.paint(painter, option, index)
        else:
            super().paint(painter, option, index)

    def _paint_cell_background(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Paint only the base cell background for separator rows."""
        bg_option = QStyleOptionViewItem(option)
        self.initStyleOption(bg_option, index)
        bg_option.text = ""
        bg_option.icon = QIcon()
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, bg_option, painter, widget)

    def _adjust_option_for_sep(self, option, index):
        """Return a copy of *option* with content shifted below the separator."""
        if index.row() not in self._sep_rows:
            return option
        adj = QStyleOptionViewItem(option)
        adj.rect = _separator_content_rect(option.rect)
        return adj

    def editorEvent(self, event, model, option, index):
        if self._sub is not None and index.column() == self._sub_col:
            return self._sub.editorEvent(event, model, self._adjust_option_for_sep(option, index), index)
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):
        if self._sub is not None and index.column() == self._sub_col:
            return self._sub.helpEvent(event, view, self._adjust_option_for_sep(option, index), index)
        return super().helpEvent(event, view, option, index)

    def _measure_pill(self, fm: QFontMetrics, cache_key: tuple, text: str) -> tuple[int, int]:
        """Return (pill_w, pill_h) for *text*, using *cache_key* for geometry caching."""
        geom = self._geometry_cache.get(cache_key)
        if geom is None:
            pad_x, pad_y = 14, 2
            pill_w = fm.horizontalAdvance(text) + pad_x * 2
            pill_h = fm.height() + pad_y * 2
            geom = (pill_w, pill_h)
            if len(self._geometry_cache) > 400:
                self._geometry_cache.clear()
            self._geometry_cache[cache_key] = geom
        return geom

    def _get_pill_path(self, w: int, h: int) -> QPainterPath:
        """Return a cached QPainterPath for a pill of the given size.

        Pills with the same (w, h) reuse the same path object, avoiding
        QPainterPath allocation + addRoundedRect on every paint() call.
        The path is positioned at (0, 0); callers translate the painter.
        """
        path = self._path_cache.get((w, h))
        if path is None:
            path = QPainterPath()
            path.addRoundedRect(0, 0, w, h, h / 2, h / 2)
            if len(self._path_cache) > 200:
                self._path_cache.clear()
            self._path_cache[(w, h)] = path
        return path

    def _draw_pill_fast(self, painter: QPainter, x: int, y: int, w: int, h: int, text: str, *, primary: bool) -> None:
        """Draw a single rounded pill — no save/restore (caller manages state).

        Assumes painter already has: antialiasing enabled, pill font set.
        """
        bg = self._pill_bg if primary else self._count_pill_bg
        text_color = self._pill_text_color if primary else self._count_pill_text_color

        path = self._get_pill_path(w, h)
        painter.translate(x, y)
        painter.fillPath(path, bg)
        painter.setPen(self._border_pen)
        painter.drawPath(path)
        painter.setPen(text_color)
        painter.drawText(0, 0, w, h, Qt.AlignCenter, text)
        painter.translate(-x, -y)

    def _paint_separator_pill(self, painter: QPainter, band: QRect, visit_time: int, row: int) -> None:
        """Draw date pill (always) and count pill (once loaded) centered in *band*.

        ``visit_time`` is passed directly from the ``_sep_rows`` dict — no
        model.data() call is ever made on the hot paint path.

        ``row`` is used to look up the lazily-loaded visit count from
        ``_sep_counts``.  When the count has not yet been fetched only the date
        pill is shown; once the count arrives the viewport is repainted and the
        count pill appears to the right of the date pill.
        """
        self._refresh_theme_cache()

        # Check today_bucket lazily — the date only changes once per 86400 seconds,
        # so checking on every paint (~10k calls) is wasteful.
        # Use a simple counter: check time.time() every 500 paint calls (~3s at 60fps).
        self._today_check_counter += 1
        if self._today_check_counter >= 500:
            self._today_check_counter = 0
            today_bucket: int = int(_time.time()) // 86400
            if today_bucket != self._date_label_cache_today:
                self._date_label_cache.clear()
                self._date_label_cache_today = today_bucket

        day_bucket = visit_time // 86400
        cache_key_label = (day_bucket,)
        date_label = self._date_label_cache.get(cache_key_label)
        if date_label is None:
            date_label = _format_separator_date(visit_time)
            if len(self._date_label_cache) > 400:
                self._date_label_cache.clear()
            self._date_label_cache[cache_key_label] = date_label

        count = self._sep_counts.get(row)  # None → not yet loaded

        pill_font, fm2 = self._get_pill_font_and_fm(painter.font())

        date_w, pill_h = self._measure_pill(fm2, ("d", date_label), date_label)

        _GAP = 6
        if count is not None and count >= 2:
            count_label = self._count_fmt.format(count=count)
            count_w, __ = self._measure_pill(fm2, ("c", count), count_label)
            total_w = date_w + _GAP + count_w
        else:
            count_label = None
            total_w = date_w

        start_x = band.left() + (band.width() - total_w) // 2
        pill_y = band.top() + (band.height() - pill_h) // 2

        # Enable antialiasing for pill rendering.  We skip save/restore of
        # renderHints here because:
        # (a) The view already wraps each delegate.paint() call in save/restore,
        #     so renderHints state is reset between columns automatically.
        # (b) Antialiasing for the content cell (super().paint()) is harmless.
        # The caller (paint()) captures the original font BEFORE calling this
        # method and restores it AFTER, so we don't need to do that here either.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(pill_font)

        self._draw_pill_fast(painter, start_x, pill_y, date_w, pill_h, date_label, primary=True)

        if count_label is not None:
            self._draw_pill_fast(painter, start_x + date_w + _GAP, pill_y, count_w, pill_h, count_label, primary=False)


class BookmarkBadgeDelegate(QStyledItemDelegate):
    """Custom delegate that renders favicon + badge icons for bookmarks/annotations."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model
        self._badge_size = 14  # Increased from 12 to 14 for better visibility
        self._badge_spacing = 3
        # Cache colorized badge pixmaps — only 2 fixed combinations exist
        # (bookmark blue, annotation green), so this eliminates ~2800 QPixmap
        # allocations + QPainter compositing calls per profiling session.
        self._colorized_cache: dict[tuple[str, int], QPixmap] = {}

    def _get_colorized_badge(self, icon_name: str, color: str) -> QPixmap | None:
        """Return a cached colorized badge pixmap, creating it on first call."""
        key = (icon_name, self._badge_size)
        cached = self._colorized_cache.get(key)
        if cached is not None:
            return cached

        icon = get_icon(icon_name)
        if icon.isNull():
            return None

        pixmap = icon.pixmap(self._badge_size, self._badge_size)
        if pixmap.isNull():
            return None

        colored = QPixmap(pixmap.size())
        colored.fill(Qt.transparent)

        p = QPainter(colored)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawPixmap(0, 0, pixmap)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(colored.rect(), QColor(color))
        p.end()

        self._colorized_cache[key] = colored
        return colored

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Draw favicon and badge icons if present."""
        # Fetch the record once via UserRole — avoids 4 separate data() calls
        # (DisplayRole, DecorationRole, BOOKMARK_ROLE, ANNOTATION_ROLE) each of
        # which would trigger a full role-dispatch + _get_record_at() round-trip.
        record = index.data(Qt.UserRole)
        if record is None:
            super().paint(painter, option, index)
            return

        has_bookmark = record.url in self._model._bookmarked_urls
        has_annotation = record.url in self._model._annotated_urls
        display_text = record.title or record.url

        state = option.state
        needs_full_style = bool(state & (QStyle.State_Selected | QStyle.State_MouseOver | QStyle.State_HasFocus))

        if needs_full_style:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            opt.icon = QIcon()
            option.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)
        else:
            # Fast path: skip initStyleOption entirely — just fill background.
            palette = option.palette
            bg = palette.color(palette.ColorRole.Base)
            if state & QStyle.State_Enabled and (option.features & QStyleOptionViewItem.ViewItemFeature.Alternate):
                bg = palette.color(palette.ColorRole.AlternateBase)
            painter.fillRect(option.rect, bg)

        favicon = self._model.data(index, Qt.DecorationRole)

        # Save only the pen instead of full painter state — much cheaper
        old_pen = painter.pen()

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

        # Draw badge icons (pixmaps are cached after first colorization)
        if has_bookmark:
            bm_px = self._get_colorized_badge("bookmark", "#3B82F6")
            if bm_px is not None:
                badge_y = y + (16 - self._badge_size) // 2
                painter.drawPixmap(x, badge_y, bm_px)
            x += self._badge_size + self._badge_spacing

        if has_annotation:
            ann_px = self._get_colorized_badge("edit-2", "#10B981")
            if ann_px is not None:
                badge_y = y + (16 - self._badge_size) // 2
                painter.drawPixmap(x, badge_y, ann_px)
            x += self._badge_size + self._badge_spacing

        # Draw text
        text_rect = QRect(x + 4, rect.y(), rect.width() - (x - rect.x()) - 4, rect.height())
        text_palette = option.palette
        if needs_full_style and state & QStyle.State_Selected:
            painter.setPen(text_palette.color(text_palette.ColorRole.HighlightedText))
        else:
            painter.setPen(text_palette.color(text_palette.ColorRole.Text))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, display_text)

        painter.setPen(old_pen)

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
        page.bookmark_changed.emit()

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


class _DensityBar(QWidget):
    """Thin bar showing how active a day was relative to the daily average."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._density: float = 0.0
        self._day_progress: float = -1.0  # -1 = not set
        self._record_rank: float = -1.0  # -1 = not set
        self.setFixedHeight(6)

    def set_density(self, value: float) -> None:
        """value in [0.0, 1.0] where 1.0 = at/above average activity."""
        self._density = max(0.0, min(1.0, value))
        self.update()

    def set_day_progress(self, value: float) -> None:
        """value in [0.0, 1.0] representing position within the day (0=00:00, 1=23:59)."""
        self._day_progress = max(0.0, min(1.0, value))
        self.update()

    def set_record_rank(self, rank: int, total: int) -> None:
        """rank and total for the current record within the day (1-based)."""
        self._record_rank = rank / max(total, 1)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Background track
        bg = QColor(80, 90, 120, 60)
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, 2, 2)

        # Fill with gradient
        if self._density > 0:
            fill_w = max(int(w * self._density), h)
            grad = QLinearGradient(0, 0, fill_w, 0)
            grad.setColorAt(0.0, QColor(60, 120, 220, 200))  # cool blue
            grad.setColorAt(0.5, QColor(80, 180, 240, 210))  # sky blue
            grad.setColorAt(1.0, QColor(120, 230, 180, 220))  # teal-green at peak
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(0, 0, fill_w, h, 2, 2)

        # Day-position indicator: white dot drawn first so the orange line renders on top
        if self._day_progress >= 0:
            dot_r = 4
            cx = int(w * self._day_progress)
            cx = max(dot_r, min(w - dot_r, cx))
            cy = h // 2
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.setPen(QColor(0, 0, 0, 60))
            painter.drawEllipse(QPoint(cx, cy), dot_r, dot_r)

        # Record-rank indicator: orange vertical line drawn last so it appears above the dot
        if self._record_rank >= 0:
            rx = int(w * self._record_rank)
            rx = max(1, min(w - 2, rx))
            painter.setBrush(QColor(255, 160, 50, 220))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rx - 1, 0, 2, h, 1, 1)


class _DomainRow(QWidget):
    """A single domain row inside the scroll bubble: favicon + name + count bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self._favicon_lbl = QLabel()
        self._favicon_lbl.setFixedSize(14, 14)
        self._favicon_lbl.setScaledContents(True)

        self._name_lbl = QLabel()
        self._name_lbl.setMinimumWidth(80)
        self._name_lbl.setMaximumWidth(130)

        self._count_lbl = QLabel()
        self._count_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self._favicon_lbl)
        layout.addWidget(self._name_lbl, 1)
        layout.addWidget(self._count_lbl)

        # Track current style values to skip no-op setStyleSheet calls.
        # setStyleSheet is expensive (~0.3 ms each) because Qt re-parses the
        # CSS string and invalidates the widget's style cache even when the
        # value hasn't changed.
        self._current_domain_color: str = ""
        self._current_count_color: str = ""

    def set_data(self, domain: str, count: int, pixmap, domain_color: str, count_color: str):
        if pixmap and not pixmap.isNull():
            self._favicon_lbl.setPixmap(pixmap)
            self._favicon_lbl.setVisible(True)
        else:
            self._favicon_lbl.setVisible(False)

        # Truncate long domains
        display = domain if len(domain) <= 20 else domain[:18] + "…"
        self._name_lbl.setText(display)
        if domain_color != self._current_domain_color:
            self._name_lbl.setStyleSheet(f"color: {domain_color}; font-size: 11px;")
            self._current_domain_color = domain_color

        self._count_lbl.setText(str(count))
        if count_color != self._current_count_color:
            self._count_lbl.setStyleSheet(f"color: {count_color}; font-size: 10px; font-weight: 600;")
            self._current_count_color = count_color


class _ScrollTimeBubble(QWidget):
    """Floating context bubble shown while dragging the vertical scrollbar.

    Displays:
    - Date + time of the record at the current scroll position
    - Top 3 domains visited on that day (with favicons and visit counts)
    - A density bar showing how active that day was vs the overall average
    - Total record count for the day
    """

    def __init__(self, parent: QWidget) -> None:
        # Use a frameless Tool window instead of a plain child widget.
        # As a child widget with WA_TranslucentBackground, every move() call
        # schedules a repaint of the *parent* widget's dirty region (Qt must
        # restore the table content underneath the bubble). That chain triggers
        # O(visible_rows × columns) _DateSeparatorDelegate.paint() calls on
        # every 60 ms timer tick — the dominant scroll-lag cost.
        # As a Tool window, move() only talks to the OS window system; the
        # parent table is never invalidated. The bubble is still visually
        # parented (follows parent window z-order, hides with it, etc.)
        # because we pass *parent* to the constructor.
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint,
        )
        # Do not steal activation from the main window when shown.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # Pass all mouse events through to whatever is behind the bubble
        # (primarily the scrollbar the user is dragging).
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._bg_color = QColor(28, 31, 38, 237)
        self._border_color = QColor(70, 80, 100, 140)

        # ── Display mode ──
        self._display_mode: str = "show"  # "show" | "simplified" | "hidden"

        # ── DB / favicon references (set by HistoryPage) ──
        self._db = None
        self._favicon_manager = None

        # ── State cache: avoid redundant DB queries ──
        self._last_date_str: str = ""
        self._last_time_str: str = ""
        self._cached_stats: dict | None = None  # {"total": int, "domains": [...]}
        self._avg_daily: float = 0.0  # rolling avg for density bar
        # Cache the last get_day_rank result so repeated set_timestamp calls for
        # the same (day_start, ts) pair skip the DB round-trip entirely.
        self._last_rank_key: tuple[int, int] | None = None  # (day_start_ts, ts)
        self._last_rank_value: int = 1

        # ── Rank query debounce ───────────────────────────────────────────────
        # get_day_rank() fires a SQLite query on every distinct (day, ts) pair.
        # During a scrollbar drag the timestamp changes on every 50 ms tick, so
        # without debouncing we'd hit the DB ~20×/s just for rank.  Instead we
        # update rank only after the user pauses for 200 ms.
        self._rank_pending_ts: int | None = None
        self._rank_timer = QTimer(self)
        self._rank_timer.setSingleShot(True)
        self._rank_timer.setInterval(200)
        self._rank_timer.timeout.connect(self._flush_rank_query)

        # ── Layout ──
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(12, 9, 12, 9)
        self._outer_layout.setSpacing(0)
        outer = self._outer_layout

        # Date + time row
        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        self._date_lbl = QLabel()
        self._date_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._time_lbl = QLabel()
        self._time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_row.addWidget(self._date_lbl)
        time_row.addStretch()
        time_row.addWidget(self._time_lbl)
        outer.addLayout(time_row)

        # Divider with spacing (wrapped in container)
        self._divider_container = QWidget(self)
        self._divider_container.setAttribute(Qt.WA_NoSystemBackground)
        divider_layout = QVBoxLayout(self._divider_container)
        divider_layout.setContentsMargins(0, 5, 0, 5)
        divider_layout.setSpacing(0)

        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.HLine)
        self._divider.setFixedHeight(1)
        divider_layout.addWidget(self._divider)

        outer.addWidget(self._divider_container)

        # Domain rows (up to 3)
        self._domain_rows: list[_DomainRow] = []
        for __ in range(3):
            row = _DomainRow(self)
            row.hide()
            outer.addWidget(row)
            self._domain_rows.append(row)

        # Bottom: density bar + total count (wrapped in container with spacing)
        self._bottom_container = QWidget(self)
        self._bottom_container.setAttribute(Qt.WA_NoSystemBackground)
        bottom_container_layout = QVBoxLayout(self._bottom_container)
        bottom_container_layout.setContentsMargins(0, 6, 0, 0)
        bottom_container_layout.setSpacing(0)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)
        self._density_bar = _DensityBar(self)
        self._density_bar.setFixedHeight(6)
        bottom_row.addWidget(self._density_bar, 1)
        bottom_container_layout.addLayout(bottom_row)

        outer.addWidget(self._bottom_container)

        # ── Tutorial section ──────────────────────
        # Dismissed after TUTORIAL_DISMISS_DRAGS drags.
        # Hidden via _tutorial_widget.hide() + adjustSize() so the bubble
        # shrinks back to its normal height without any layout rebuild.
        self._tutorial_widget = QWidget(self)
        self._tutorial_widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._tutorial_widget.setAttribute(Qt.WA_NoSystemBackground)
        tut_layout = QVBoxLayout(self._tutorial_widget)
        tut_layout.setContentsMargins(0, 6, 0, 0)
        tut_layout.setSpacing(0)

        # Dashed divider above tutorial
        tut_divider = QFrame()
        tut_divider.setFrameShape(QFrame.HLine)
        tut_divider.setFixedHeight(1)
        tut_layout.addWidget(tut_divider)
        self._tut_divider = tut_divider

        tut_layout.addSpacing(6)

        # Header row: "Bar guide" label
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        self._tut_title_lbl = QLabel(_("Bar guide"))
        header_row.addWidget(self._tut_title_lbl)
        tut_layout.addLayout(header_row)

        tut_layout.addSpacing(5)

        # Three legend rows — each is a mini QHBoxLayout: icon-widget + label
        self._tut_rows: list[QHBoxLayout] = []
        for __ in range(4):  # Changed from 3 to 4 for new tutorial line
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(28, 10)
            text_lbl = QLabel()
            text_lbl.setWordWrap(True)
            row.addWidget(icon_lbl)
            row.addWidget(text_lbl, 1)
            tut_layout.addLayout(row)
            tut_layout.addSpacing(3)
            self._tut_rows.append((icon_lbl, text_lbl))

        # Auto-dismiss hint
        tut_layout.addSpacing(3)
        self._tut_hint_lbl = QLabel()
        self._tut_hint_lbl.setAlignment(Qt.AlignCenter)
        self._tut_hint_lbl.setWordWrap(True)
        tut_layout.addWidget(self._tut_hint_lbl)

        outer.addWidget(self._tutorial_widget)

        # ── Tutorial state ────────────────────────────────────────────────────
        # Number of sliderPressed events seen since the bubble was created.
        # After TUTORIAL_DISMISS_DRAGS the tutorial auto-dismisses.
        self._tutorial_drag_count: int = 0
        self._tutorial_dismissed: bool = False
        # Reference to AppConfig injected later via set_config(); used to
        # persist the dismissed state across restarts.
        self._config = None

        # ── Animation ──
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hiding = False
        self._anim.finished.connect(self._on_anim_done)

        # ── Inertial Y position smoothing ──
        # _target_y / _current_y are in parent-widget coordinates.
        # Each timer tick, _current_y is nudged toward _target_y with
        # exponential decay so the bubble glides rather than teleports.
        self._target_y: int = 0
        self._current_y: float = 0.0
        self._target_x: int = 0  # X never animates, stored for move()
        # Smoothing factor per 60 ms tick: 0 = no movement, 1 = instant.
        # 0.35 gives ~3-4 frames to settle — snappy but visibly smooth.
        self._SMOOTH_FACTOR: float = 0.35

        self.setFixedWidth(220)
        self.hide()
        self.apply_theme(ThemeManager.instance().current)

    def set_data_sources(self, db, favicon_manager) -> None:
        """Called by HistoryPage after construction to inject data sources."""
        self._db = db
        self._favicon_manager = favicon_manager
        # Precompute the average daily record count for the density bar
        self._refresh_avg_daily()

    # Number of drag operations before the tutorial auto-dismisses.
    _TUTORIAL_DISMISS_DRAGS: int = 5

    def set_config(self, config) -> None:
        """Inject AppConfig so the tutorial dismissed-state can be persisted.

        Must be called once after construction, before the first drag.
        If config already has the tutorial dismissed, hide the tutorial widget
        immediately (before the bubble is ever shown) so adjustSize() never
        includes the tutorial section in the bubble height.
        """
        self._config = config
        already_dismissed = getattr(getattr(config, "ui", None), "scroll_bubble_tutorial_dismissed", False)
        if already_dismissed:
            self._tutorial_dismissed = True
            self._tutorial_widget.hide()

    def _dismiss_tutorial(self, *, save: bool) -> None:
        """Hide the tutorial section and optionally persist the dismissed state."""
        if self._tutorial_dismissed:
            return
        self._tutorial_dismissed = True
        self._tutorial_widget.hide()
        self.adjustSize()
        if save and self._config is not None:
            try:
                self._config.ui.scroll_bubble_tutorial_dismissed = True
                self._config.save()
            except Exception as e:
                log.warning("Failed to save tutorial dismissed state: %s", e)

    def on_drag_started(self) -> None:
        """Called by HistoryPage each time the scrollbar slider is pressed.

        Increments the drag counter and auto-dismisses the tutorial once the
        threshold is reached.  This method is a no-op once dismissed.
        """
        if self._tutorial_dismissed:
            return
        self._tutorial_drag_count += 1
        self._update_tut_hint()
        if self._tutorial_drag_count >= self._TUTORIAL_DISMISS_DRAGS:
            self._dismiss_tutorial(save=True)

    def _update_tut_hint(self) -> None:
        """Refresh the auto-dismiss hint label with the remaining drag count."""
        if self._tutorial_dismissed:
            return
        remaining = max(self._TUTORIAL_DISMISS_DRAGS - self._tutorial_drag_count, 0)
        self._tut_hint_lbl.setText(_("{n} more drag(s) to close").format(n=remaining) if remaining > 0 else "")

    def _refresh_avg_daily(self) -> None:
        if self._db is None:
            return
        try:
            stats = self._db.get_db_stats()
            total = getattr(stats, "record_count", 0)

            if total <= 0:
                self._avg_daily = 100.0
                return

            time_range = self._db.get_visit_time_range()
            span_days = max((time_range[1] - time_range[0]) / 86400, 1) if time_range else 365

            real_avg = total / span_days
            self._avg_daily = max(real_avg, 50.0)

            log.debug("Scroll bubble: total=%d, days=%.1f, avg=%.1f", total, span_days, self._avg_daily)
        except Exception as e:
            log.warning("Failed to refresh avg daily stats: %s", e)
            self._avg_daily = 100.0

    def apply_theme(self, theme: str) -> None:
        is_dark = theme == "dark"
        if is_dark:
            self._bg_color = QColor(22, 25, 34, 245)
            self._border_color = QColor(70, 80, 100, 130)
            self._date_color = "#e2e5f0"
            self._time_color = "#5a6580"
            self._domain_color = "#b0b8d0"
            self._count_color = "#5a9cf8"
            self._total_color = "#4a5570"
            self._divider.setStyleSheet("background: #2e3347;")
        else:
            self._bg_color = QColor(250, 251, 255, 245)
            self._border_color = QColor(200, 208, 228, 180)
            self._date_color = "#1a1e2e"
            self._time_color = "#8896b0"
            self._domain_color = "#3a4260"
            self._count_color = "#2563eb"
            self._total_color = "#9aa0b4"
            self._divider.setStyleSheet("background: #dde2f0;")

        self._date_lbl.setStyleSheet(
            f"color: {self._date_color}; font-size: 13px; font-weight: 700; background: transparent;"
        )
        self._time_lbl.setStyleSheet(f"color: {self._time_color}; font-size: 11px; background: transparent;")
        # Force domain rows to repaint with new colors if data is already loaded
        if self._cached_stats:
            self._render_domain_rows(self._cached_stats)
        self.update()
        # ── Tutorial section theming ──────────────────────────────────────────
        self._apply_tutorial_theme(is_dark)

    def _apply_tutorial_theme(self, is_dark: bool) -> None:
        """Style all tutorial sub-widgets for the current theme.

        Also redraws the three icon QLabels (blue bar, white dot, orange line)
        using QPainter so they always match the real _DensityBar appearance.
        Called from apply_theme(); safe to call before the tutorial widget is
        shown for the first time.
        """
        tut_title_color = "#c0c8e0" if is_dark else "#3a4260"
        tut_text_color = "#8090b0" if is_dark else "#6070a0"
        tut_hint_color = "#4a5570" if is_dark else "#aab0c8"
        tut_divider_css = "background: #2e3347;" if is_dark else "background: #dde2f0;"

        self._tut_divider.setStyleSheet(tut_divider_css)
        self._tut_title_lbl.setStyleSheet(
            f"color: {tut_title_color}; font-size: 10px; font-weight: 600; background: transparent;"
        )
        self._tut_hint_lbl.setStyleSheet(f"color: {tut_hint_color}; font-size: 9px; background: transparent;")

        # Legend definitions — each draw_fn renders the icon into a QPainter.
        bar_color = QColor(74, 156, 239, 160)  # matches _DensityBar blue fill
        dot_color = QColor(255, 255, 255, 230)  # white dot
        dot_border = QColor(0, 0, 0, 60)
        line_color = QColor(255, 160, 50, 220)  # orange rank line

        def _draw_bar(painter: QPainter, rect) -> None:
            painter.setBrush(QColor(80, 90, 120, 60))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.x(), rect.y() + 3, rect.width(), 4, 2, 2)
            fill_w = int(rect.width() * 0.6)
            painter.setBrush(bar_color)
            painter.drawRoundedRect(rect.x(), rect.y() + 3, fill_w, 4, 2, 2)

        def _draw_dot(painter: QPainter, rect) -> None:
            painter.setBrush(QColor(80, 90, 120, 60))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.x(), rect.y() + 3, rect.width(), 4, 2, 2)
            cx = rect.x() + int(rect.width() * 0.45)
            cy = rect.y() + 5
            painter.setBrush(dot_color)
            painter.setPen(dot_border)
            painter.drawEllipse(QPoint(cx, cy), 4, 4)

        def _draw_line(painter: QPainter, rect) -> None:
            painter.setBrush(QColor(80, 90, 120, 60))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.x(), rect.y() + 3, rect.width(), 4, 2, 2)
            rx = rect.x() + int(rect.width() * 0.70)
            painter.setBrush(line_color)
            painter.drawRoundedRect(rx - 1, rect.y() + 1, 2, 8, 1, 1)

        legend_defs = [
            (_draw_bar, N_("Daily visit volume")),
            (_draw_dot, N_("Time position within the day")),
            (_draw_line, N_("Record rank within the day")),
            (None, N_("Right-click scrollbar to change settings")),  # Text-only, no icon
        ]

        for (draw_fn, desc_key), (icon_lbl, text_lbl) in zip(legend_defs, self._tut_rows, strict=False):
            if draw_fn is not None:
                pm = QPixmap(icon_lbl.size())
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                draw_fn(p, pm.rect())
                p.end()
                icon_lbl.setPixmap(pm)
                icon_lbl.show()
            else:
                icon_lbl.hide()  # No icon for text-only rows
            text_lbl.setText(_(desc_key))
            text_lbl.setStyleSheet(f"color: {tut_text_color}; font-size: 10px; background: transparent;")

        self._update_tut_hint()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 12, 12)
        painter.fillPath(path, self._bg_color)
        painter.setPen(self._border_color)
        painter.drawPath(path)

    def set_timestamp(self, ts: int) -> None:
        lt = _time.localtime(ts)

        # Cache the current year to avoid a syscall on every timer tick.
        now_year = getattr(self, "_cached_year", 0)
        if now_year == 0:
            now_year = _time.localtime().tm_year
            self._cached_year = now_year

        weekday = _(_WEEKDAY_ABBR[lt.tm_wday])  # 0=Mon ... 6=Sun
        if lt.tm_year == now_year:
            new_date = f"{lt.tm_mon:02d}-{lt.tm_mday:02d} {weekday}"
        else:
            new_date = f"{lt.tm_year}-{lt.tm_mon:02d}-{lt.tm_mday:02d} {weekday}"
        new_time = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"

        # Always update time label
        if new_time != self._last_time_str:
            self._time_lbl.setText(new_time)
            self._last_time_str = new_time

        # Update day-position indicator on every timestamp change
        day_progress = (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) / 86400
        self._density_bar.set_day_progress(day_progress)

        # Update record-rank indicator — debounced to avoid a SQLite round-trip
        # on every 50 ms scroll tick.  We schedule the actual DB query 200 ms
        # after the last timestamp change; the bar keeps showing the previous
        # rank value while the user is actively dragging.
        if self._db is not None:
            self._rank_pending_ts = int(ts)
            if not self._rank_timer.isActive():
                self._rank_timer.start()  # start 200 ms countdown; don't restart if already running

        # Only query DB and resize when the date actually changes (expensive part).
        # adjustSize() triggers a full Qt layout pass, so it must not be called
        # on every 50 ms scroll tick — only when domain rows are added/removed.
        if new_date != self._last_date_str:
            self._last_date_str = new_date
            self._date_lbl.setText(new_date)
            self._load_day_stats(lt)
            self.adjustSize()

    def _flush_rank_query(self) -> None:
        """Execute the deferred get_day_rank DB query after the debounce idle period."""
        ts = self._rank_pending_ts
        if ts is None or self._db is None:
            return
        self._rank_pending_ts = None
        try:
            lt = _time.localtime(ts)
            day_start = int(
                _time.mktime(_time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, lt.tm_isdst)))
            )
            rank_key = (day_start, ts)
            if rank_key != self._last_rank_key:
                self._last_rank_value = self._db.get_day_rank(day_start, ts)
                self._last_rank_key = rank_key
            total = self._cached_stats.get("total", 1) if self._cached_stats else 1
            self._density_bar.set_record_rank(self._last_rank_value, total)
        except Exception:
            pass

    def _load_day_stats(self, lt) -> None:
        """Query DB for top domains + total count for the given day.

        *lt* is a time.struct_time from localtime().
        """
        if self._db is None:
            return
        try:
            day_start = int(
                _time.mktime(_time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, lt.tm_isdst)))
            )
            day_end = day_start + 86399
            stats = self._db.get_day_stats(day_start, day_end, top_n=3)
            self._cached_stats = stats
            self._render_domain_rows(stats)
            # Update density bar
            total = stats.get("total", 0)
            density = min(total / max(self._avg_daily, 1.0), 1.0)
            self._density_bar.set_density(density)
        except Exception:
            self._cached_stats = None

    def _render_domain_rows(self, stats: dict) -> None:
        """Populate domain row widgets from cached stats."""
        if self._display_mode in ("compact", "minimal"):
            # Keep domains hidden in compact/minimal mode
            for row in self._domain_rows:
                row.hide()
            return
        domains = stats.get("domains", [])
        for i, row_widget in enumerate(self._domain_rows):
            if i < len(domains):
                host, count = domains[i]
                pixmap = None
                if self._favicon_manager:
                    try:
                        pixmap = self._favicon_manager.get_pixmap(f"https://{host}", size=14)
                    except Exception:
                        pass
                row_widget.set_data(host, count, pixmap, self._domain_color, self._count_color)
                row_widget.show()
            else:
                row_widget.hide()

    def set_display_mode(self, mode: str) -> None:
        """Change bubble display mode and update visibility immediately.

        Modes:
        - "full": Full display (date, time, domains, density bar, tutorial)
        - "compact": Date, time, and density bar only (hide domains + tutorial)
        - "minimal": Date and time only (hide domains, density bar, tutorial)
        - "hidden": Never show bubble (handled by caller, not here)
        """
        self._display_mode = mode

        if mode == "minimal":
            # Hide everything except date and time
            for row in self._domain_rows:
                row.hide()
            self._tutorial_widget.hide()
            self._divider_container.hide()
            self._bottom_container.hide()
            # Reduce bottom padding in minimal mode to match top
            self._outer_layout.setContentsMargins(12, 9, 12, 9)
            self.adjustSize()
        elif mode == "compact":
            # Hide domain rows and tutorial
            for row in self._domain_rows:
                row.hide()
            self._tutorial_widget.hide()
            self._divider_container.hide()
            self._bottom_container.show()
            # Restore default margins
            self._outer_layout.setContentsMargins(12, 9, 12, 9)
            self.adjustSize()
        elif mode == "full":
            # Show divider; domains are shown/hidden dynamically in _render_domain_rows
            self._divider_container.show()
            self._bottom_container.show()
            # Restore default margins
            self._outer_layout.setContentsMargins(12, 9, 12, 9)
            # Tutorial visibility depends on dismissed state
            if not self._tutorial_dismissed:
                self._tutorial_widget.show()
            self.adjustSize()

    def show_animated(self) -> None:
        if self._display_mode == "hidden":
            return  # Don't show at all
        self._hiding = False
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self.show()
        self.raise_()
        self._anim.start()

    def hide_animated(self) -> None:
        self._hiding = True
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if self._hiding:
            self.hide()
            self._hiding = False
            # Reset caches so the next open always reloads fresh data
            self._last_date_str = ""
            self._last_time_str = ""
            self._last_rank_key = None
            self._rank_pending_ts = None
            self._rank_timer.stop()
            # Expire year cache on hide so the next drag gets a fresh value
            self._cached_year = 0
            # Reset inertial state so next show starts from the correct position
            self._last_pos_set = False

    def reposition(self, sb: QScrollBar, page: QWidget) -> None:
        # Cache the last scrollbar value so we only recompute thumb geometry
        # when the slider actually moved.  subControlRect() + mapToGlobal()
        # account for a significant share of reposition() cost on busy timer ticks.
        sb_value = sb.value()
        if sb_value == getattr(self, "_last_sb_value", None) and getattr(self, "_last_pos_set", False):
            return
        self._last_sb_value = sb_value
        self._last_pos_set = True

        opt = QStyleOptionSlider()
        sb.initStyleOption(opt)
        thumb_rect = sb.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            opt,
            QStyle.SubControl.SC_ScrollBarSlider,
            sb,
        )
        # The bubble is now a top-level Tool window, so all coordinates must
        # be in global screen space — mapToGlobal() instead of mapTo(page).
        thumb_global_y = sb.mapToGlobal(QPoint(0, thumb_rect.center().y())).y()
        sb_global_x = sb.mapToGlobal(QPoint(0, 0)).x()
        page_global = page.mapToGlobal(QPoint(0, 0))

        self._target_x = sb_global_x - self.width() - 8
        raw_y = thumb_global_y - self.height() // 2
        # Clamp to the page widget's global rect so the bubble never floats
        # outside the visible history panel.
        self._target_y = max(
            page_global.y(),
            min(raw_y, page_global.y() + page.height() - self.height()),
        )

    def tick_position(self) -> bool:
        """Advance the inertial Y position one step toward _target_y.

        Called every 60 ms by the HistoryPage timer.  Uses exponential
        smoothing so the bubble glides to its target rather than teleporting.
        X is never animated — it only changes when the scrollbar moves to the
        other side of the viewport, which is rare.

        Returns True when the bubble has fully settled at _target_y (no more
        movement needed) so the caller can skip subsequent work.
        """
        delta = self._target_y - self._current_y
        # Skip sub-pixel moves to avoid perpetual repaints when settled.
        if abs(delta) < 0.5:
            if int(self._current_y) != self._target_y:
                self._current_y = float(self._target_y)
                self.move(self._target_x, self._target_y)
            return True  # fully settled — caller may skip next tick if nothing else changed
        self._current_y += delta * self._SMOOTH_FACTOR
        new_y = int(self._current_y)
        # Only call move() when the integer pixel position actually changes.
        # QWidget.move() is expensive (~2.6ms/call) even for Tool windows because
        # it triggers OS-level window repositioning.  During inertial smoothing
        # the sub-pixel delta can be non-zero while the integer position is unchanged.
        new_pos = (self._target_x, new_y)
        if new_pos != (self.x(), self.y()):
            self.move(*new_pos)
        return False  # still animating toward target

    def snap_position(self) -> None:
        """Instantly place the bubble at _target_y with no animation.

        Called on the first tick of a new drag so the bubble appears at the
        correct position rather than sliding in from wherever it last was.
        Coordinates are global (screen-space) because the bubble is a Tool window.
        """
        self._current_y = float(self._target_y)
        self.move(self._target_x, self._target_y)


class _DraggableHistoryTable(QTableView):
    """QTableView subclass with Alt+drag URL export support.

    • Normal drag (no Alt) → rubber-band selection (unchanged)
    • Alt + drag from any row → drag URL(s) as text/uri-list and text/plain
    • Tooltip shown when hovering over rows with Alt held
    """

    # Maximum number of URLs to drag at once (circuit breaker)
    MAX_DRAG_URLS = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_start_pos: QPoint | None = None
        self._drag_start_row: int = -1
        self._alt_pressed: bool = False
        self._favicon_drag: bool = False  # True if drag started from favicon area

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                # Check if click is on favicon area (title column)
                if self._is_favicon_area(index, event.pos()):
                    self._drag_start_pos = QPoint(event.pos())
                    self._drag_start_row = index.row()
                    self._favicon_drag = True
                    # Don't call super() - prevent selection change on favicon click
                    event.accept()
                    return

                # Check if Alt is pressed
                mods = QApplication.keyboardModifiers()
                if mods & Qt.AltModifier:
                    self._drag_start_pos = QPoint(event.pos())
                    self._drag_start_row = index.row()
                    self._alt_pressed = True
                    # Do NOT call super() — prevents selection change on Alt+press
                    event.accept()
                    return

        self._drag_start_pos = None
        self._drag_start_row = -1
        self._alt_pressed = False
        self._favicon_drag = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Check whether to start a drag first (before cursor update)
        if (
            (self._alt_pressed or self._favicon_drag)
            and self._drag_start_pos is not None
            and event.buttons() & Qt.LeftButton
            and (event.pos() - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._start_url_drag()
            self._drag_start_pos = None
            self._drag_start_row = -1
            self._alt_pressed = False
            self._favicon_drag = False
            event.accept()
            return

        # Don't call super() when Alt is pressed or favicon dragging to prevent selection changes
        if (self._alt_pressed or self._favicon_drag) and event.buttons() & Qt.LeftButton:
            event.accept()
            return

        # Update cursor when hovering over favicon area
        if not (event.buttons() & Qt.LeftButton):
            index = self.indexAt(event.pos())
            if index.isValid() and self._is_favicon_area(index, event.pos()):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        self._drag_start_row = -1
        self._alt_pressed = False
        self._favicon_drag = False

        # Update cursor after release
        index = self.indexAt(event.pos())
        if index.isValid() and self._is_favicon_area(index, event.pos()):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()

        super().mouseReleaseEvent(event)

    def _is_favicon_area(self, index, pos: QPoint) -> bool:
        """Check if the click position is within the favicon area of the title column."""
        model = self.model()
        if not model or not hasattr(model, "_key_to_col"):
            return False

        title_col = model._key_to_col.get("title", -1)
        if title_col < 0 or index.column() != title_col:
            return False

        # Get visual rect for this cell
        vr = self.visualRect(index)
        if vr.isNull():
            return False
        page = self.parent()
        if page and hasattr(page, "_separator_rows") and index.row() in page._separator_rows:
            vr = _separator_content_rect(vr)

        # Favicon is at x=rect.x()+4, y=centered, w=16, h=16
        # Add some padding for easier clicking (24x24 hit area)
        fav_x = vr.x() + 4 - 4  # Add 4px padding on left
        fav_y = vr.y() + (vr.height() - 24) // 2
        fav_rect = QRect(fav_x, fav_y, 24, 24)

        return fav_rect.contains(pos)

    # ------------------------------------------------------------------
    # Drag logic
    # ------------------------------------------------------------------

    def _start_url_drag(self):
        """Collect URLs, build MIME data, show preview, execute drag."""
        if self._drag_start_row < 0:
            return

        # Decide which rows to drag:
        # - If drag starts from a selected row → drag all selected rows
        # - If drag starts from an unselected row → drag only that row (don't change selection)
        sel_rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        rows = sel_rows if self._drag_start_row in sel_rows and len(sel_rows) >= 1 else [self._drag_start_row]

        # Circuit breaker: silently abort if too many URLs selected
        if len(rows) > self.MAX_DRAG_URLS:
            return

        model = self.model()
        records = [model.get_record_at(r) for r in rows]
        records = [r for r in records if r and getattr(r, "url", None)]
        if not records:
            return

        urls = [r.url for r in records]
        titles = [r.title or urlparse(r.url).netloc or "Link" for r in records]

        mime = QMimeData()
        mime.setText("\n".join(urls))
        mime.setUrls([QUrl(u) for u in urls])

        # Add Windows file drag support for creating .url files on desktop
        import sys

        if sys.platform == "win32":
            try:
                self._add_windows_file_drag(mime, urls, titles)
            except Exception as e:
                log.warning("Failed to add Windows file drag support: %s", e)

        drag = QDrag(self)
        drag.setMimeData(mime)

        preview = self._create_drag_preview(rows, records)
        if not preview.isNull():
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))

        drag.exec(Qt.CopyAction)

    def _add_windows_file_drag(self, mime: QMimeData, urls: list[str], titles: list[str]):
        """Add Windows-specific MIME data to support dragging .url files to desktop."""
        import struct

        # FileGroupDescriptorW structure for Windows shell
        file_count = len(urls)

        # Build FileGroupDescriptorW
        # UINT cItems (4 bytes) + array of FILEDESCRIPTORW structures
        fgd = struct.pack("<I", file_count)  # cItems

        file_contents = []

        for _i, (url, title) in enumerate(zip(urls, titles, strict=False)):
            # Sanitize filename
            safe_title = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in title)
            safe_title = safe_title.strip()[:50]  # Limit length
            if not safe_title:
                safe_title = "Link"
            filename = f"{safe_title}.url"

            # .url file format (INI-style)
            content = f"[InternetShortcut]\r\nURL={url}\r\n"
            content_bytes = content.encode("utf-8")
            file_contents.append(content_bytes)

            # FILEDESCRIPTORW structure (592 bytes)
            flags = 0x00000001 | 0x00000040  # FD_ATTRIBUTES | FD_FILESIZE
            filename_wide = filename.encode("utf-16-le")[:520]  # Max 260 wide chars
            filename_wide = filename_wide.ljust(520, b"\x00")

            descriptor = struct.pack("<I", flags)  # dwFlags
            descriptor += b"\x00" * 16  # clsid
            descriptor += b"\x00" * 8  # sizel
            descriptor += b"\x00" * 8  # pointl
            descriptor += struct.pack("<I", 0x80)  # dwFileAttributes (FILE_ATTRIBUTE_NORMAL)
            descriptor += b"\x00" * 8  # ftCreationTime
            descriptor += b"\x00" * 8  # ftLastAccessTime
            descriptor += b"\x00" * 8  # ftLastWriteTime
            descriptor += struct.pack("<I", 0)  # nFileSizeHigh
            descriptor += struct.pack("<I", len(content_bytes))  # nFileSizeLow
            descriptor += filename_wide  # cFileName

            fgd += descriptor

        # Set MIME data with proper Qt Windows format
        mime.setData('application/x-qt-windows-mime;value="FileGroupDescriptorW"', fgd)

        # Set FileContents for each file
        for i, content_bytes in enumerate(file_contents):
            mime.setData(f'application/x-qt-windows-mime;value="FileContents";index={i}', content_bytes)

    # ------------------------------------------------------------------
    # Drag preview pixmap
    # ------------------------------------------------------------------

    def _create_drag_preview(self, rows: list[int], records: list) -> QPixmap:
        """Return a rich semi-transparent card pixmap for the drag ghost.

        Args:
            rows: List of row indices being dragged
            records: List of HistoryRecord objects corresponding to rows
        """
        count = len(records)
        if count == 0:
            return QPixmap()

        # Detect current theme
        theme = ThemeManager.instance().current
        is_dark = theme == "dark"

        # Theme-aware colors
        if is_dark:
            card_bg = QColor(50, 55, 65, 240)  # Dark card background (lighter)
            card_border = QColor(90, 100, 115, 200)  # Dark border (lighter)
            shadow_color = QColor(0, 0, 0, 80)  # Darker shadow
            text_primary = QColor(230, 235, 245)  # Light text
            text_secondary = QColor(170, 180, 195)  # Muted light text
            avatar_bg = QColor(100, 120, 180)  # Blue avatar
            avatar_bg_2 = QColor(120, 100, 180)  # Purple avatar (second)
            badge_bg = QColor(59, 130, 246)  # Blue badge
        else:
            card_bg = QColor(255, 255, 255, 220)  # Light card background
            card_border = QColor(200, 200, 200, 180)  # Light border
            shadow_color = QColor(0, 0, 0, 40)  # Light shadow
            text_primary = QColor(40, 40, 40)  # Dark text
            text_secondary = QColor(100, 100, 100)  # Muted dark text
            avatar_bg = QColor(100, 120, 180)  # Blue avatar
            avatar_bg_2 = QColor(120, 100, 180)  # Purple avatar (second)
            badge_bg = QColor(59, 130, 246)  # Blue badge

        card_w, card_h = 240, 56
        layer_offset = 4

        total_w = card_w if count == 1 else card_w + layer_offset
        total_h = card_h if count == 1 else card_h + layer_offset

        pixmap = QPixmap(total_w, total_h)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        num_layers = min(count, 2)
        model = self.model()
        title_col = -1
        if model and hasattr(model, "_key_to_col"):
            title_col = model._key_to_col.get("title", -1)

        # Draw layered cards back → front
        for i in range(num_layers - 1, -1, -1):
            ox = (num_layers - 1 - i) * layer_offset
            oy = (num_layers - 1 - i) * layer_offset

            # Shadow
            painter.setBrush(shadow_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRect(ox + 2, oy + 2, card_w, card_h), 6, 6)

            # Card face
            painter.setBrush(card_bg)
            painter.setPen(QPen(card_border, 1))
            painter.drawRoundedRect(QRect(ox, oy, card_w, card_h), 6, 6)

            # Draw favicon on back card (second URL) if we have 2+ items
            if i == 0 and count >= 2 and title_col >= 0 and len(rows) >= 2:
                idx = model.index(rows[1], title_col)
                deco = model.data(idx, Qt.DecorationRole)
                back_favicon: QPixmap | None = None
                if isinstance(deco, QPixmap):
                    back_favicon = deco
                elif isinstance(deco, QIcon) and not deco.isNull():
                    back_favicon = deco.pixmap(16, 16)

                back_fav_x = ox + 12
                back_fav_y = oy + (card_h - 16) // 2

                if back_favicon and not back_favicon.isNull():
                    painter.drawPixmap(back_fav_x, back_fav_y, 16, 16, back_favicon)
                else:
                    # Letter avatar for second URL
                    try:
                        domain = urlparse(records[1].url).netloc or "?"
                        letter = domain[0].upper() if domain else "?"
                    except Exception:
                        letter = "?"
                    painter.setBrush(avatar_bg_2)
                    painter.setPen(Qt.NoPen)
                    painter.drawRoundedRect(back_fav_x, back_fav_y, 16, 16, 3, 3)
                    painter.setPen(QColor(255, 255, 255))
                    painter.setFont(QFont("Arial", 9, QFont.Bold))
                    painter.drawText(QRect(back_fav_x, back_fav_y, 16, 16), Qt.AlignCenter, letter)

        # Front card offset
        fx = layer_offset if count > 1 else 0
        fy = layer_offset if count > 1 else 0

        # ── Retrieve favicon for first URL ────────────────────
        favicon: QPixmap | None = None
        if title_col >= 0 and len(rows) > 0:
            idx = model.index(rows[0], title_col)
            deco = model.data(idx, Qt.DecorationRole)
            if isinstance(deco, QPixmap):
                favicon = deco
            elif isinstance(deco, QIcon) and not deco.isNull():
                favicon = deco.pixmap(16, 16)

        # ── Draw favicon (or letter avatar) on front card ─────
        fav_x = fx + 12
        fav_y = fy + (card_h - 16) // 2

        if favicon and not favicon.isNull():
            painter.drawPixmap(fav_x, fav_y, 16, 16, favicon)
        else:
            try:
                domain = urlparse(records[0].url).netloc or "?"
                letter = domain[0].upper() if domain else "?"
            except Exception:
                letter = "?"
            painter.setBrush(avatar_bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(fav_x, fav_y, 16, 16, 3, 3)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.drawText(QRect(fav_x, fav_y, 16, 16), Qt.AlignCenter, letter)

        # ── Draw text ─────────────────────────────────────────
        text_x = fav_x + 16 + 8
        text_y = fy + 8
        text_w = card_w - (text_x - fx) - 8

        painter.setPen(text_primary)

        if count == 1:
            try:
                domain = urlparse(records[0].url).netloc or records[0].url
            except Exception:
                domain = records[0].url

            # Domain bold
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            d_text = domain if len(domain) <= 30 else domain[:28] + "…"
            painter.drawText(QRect(text_x, text_y, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter, d_text)

            # Title small
            painter.setFont(QFont("Arial", 9))
            painter.setPen(text_secondary)
            title = getattr(records[0], "title", "") or ""
            t_text = title if len(title) <= 35 else title[:33] + "…"
            painter.drawText(QRect(text_x, text_y + 20, text_w, 18), Qt.AlignLeft | Qt.AlignVCenter, t_text)
        else:
            # Multiple: "N links" label
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.setPen(text_primary)
            painter.drawText(
                QRect(text_x, text_y + 8, text_w - 30, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{count} links",
            )

            # Count badge
            bx = fx + card_w - 32
            by = fy + 8
            painter.setBrush(badge_bg)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(bx, by, 20, 20)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(QRect(bx, by, 20, 20), Qt.AlignCenter, str(count))

        painter.end()
        return pixmap


# Columns whose content is naturally long text; these share remaining viewport
# width equally when the window is resized, replacing the old "stretch last
# column" behaviour with a more balanced layout.
_LONG_TEXT_COLS: frozenset[str] = frozenset({"title", "url", "domain", "metadata"})

# Hard floor for any single long-text column so text remains readable even on
# very narrow windows.
_MIN_LONG_TEXT_W = 80


class HistoryPage(QWidget):
    # Signals to parent for blacklist / hide changes
    blacklist_domain_requested = Signal(str)
    hide_records_requested = Signal(list)  # list of record IDs
    hide_domain_requested = Signal(str, bool, bool)  # domain, subdomain_only, auto_hide
    delete_records_requested = Signal(list)  # list of record IDs
    unhide_records_requested = Signal(list)  # list of record IDs to unhide
    bookmark_changed = Signal()  # emitted after any add/remove bookmark action

    _BUBBLE_SETTLE_TICKS = 3

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

        # Deferred long-text column redistribution.  Using a single-shot timer
        # lets multiple rapid resize events collapse into one redistribution and,
        # more importantly, ensures the timer fires AFTER updateGeometries() has
        # run so the viewport already reflects the correct vertical-scrollbar
        # visibility (and thus the correct available width).
        self._redist_timer = QTimer(self)
        self._redist_timer.setSingleShot(True)
        self._redist_timer.timeout.connect(self._redistribute_long_text_cols)
        # Guard flag: True while _redistribute_long_text_cols is executing.
        # Prevents the viewport Resize event emitted by updateGeometries() inside
        # redistribution from scheduling a new redistribution pass (infinite loop).
        self._in_redistribution = False
        self._scroll_bubble_timer = QTimer(self)
        self._scroll_bubble_timer.setInterval(60)
        self._scroll_bubble_timer.timeout.connect(self._update_scroll_bubble)

        # Scroll position to restore after an in-place mutation (delete/hide/unhide).
        # None means "scroll to top as usual"; set before emitting mutation signals.
        self._pending_scroll_restore: int | None = None
        # Generation counter to invalidate stale filter_by_url scroll handlers
        # when filter_by_url is called again before the previous one completes.
        self._filter_url_gen: int = 0
        # Active locate generation. While set, table repaints are temporarily
        # frozen so a model reset does not visibly jump to the top.
        self._active_locate_gen: int | None = None

        self._separator_rows: dict[int, int] = {}
        # Lazily-populated visit counts for date-separator pills.
        # Keyed by row index — populated by _load_visible_sep_counts() after
        # the user scrolls to (and pauses on) a region of the table.
        self._sep_counts: dict[int, int] = {}

        # Debounce timer: fires 300 ms after the last scroll event to trigger
        # a batch DB query for visible separator rows that lack counts.
        self._sep_count_timer = QTimer(self)
        self._sep_count_timer.setSingleShot(True)
        self._sep_count_timer.setInterval(300)

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

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title_lbl = QLabel(_("History"))
        self._title_lbl.setObjectName("page_title")
        title_row.addWidget(self._title_lbl)

        self._hidden_mode_btn = QPushButton()
        self._hidden_mode_btn.setIcon(get_icon("eye-off"))
        self._hidden_mode_btn.setToolTip(_("View hidden records"))
        self._hidden_mode_btn.setFlat(True)
        self._hidden_mode_btn.setFixedSize(28, 28)
        self._hidden_mode_btn.setIconSize(QSize(16, 16))
        self._hidden_mode_btn.setCursor(Qt.PointingHandCursor)
        self._hidden_mode_btn.clicked.connect(self._toggle_hidden_mode)
        title_row.addWidget(self._hidden_mode_btn)
        title_row.addStretch()

        title_col.addLayout(title_row)
        self._subtitle_lbl = QLabel(_("Double-click any row to open the link in browser"))
        self._subtitle_lbl.setObjectName("page_subtitle")
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
        persist_recent = not bool(self._config and getattr(self._config, "_fresh", False))
        self._search = SmartSearchLineEdit(persist_recent=persist_recent)
        self._search.setObjectName("search_box")
        self._search.textChanged.connect(lambda _: self._debounce.start(_DEBOUNCE_MS))
        self._search.regex_toggled.connect(self._do_search)
        self._search.search_submitted.connect(self._do_search)
        row1.addWidget(self._search)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self._browser_combo = StyledComboBox()
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
        self._customize_calendar(self._date_from)

        dash = QLabel("→")
        dash.setObjectName("muted")

        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._do_search)
        self._customize_calendar(self._date_to)

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
        self._table = _DraggableHistoryTable(self)
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

        # Defer column width application until the widget has been added to the
        # layout and the viewport has its real size.  Calling _apply_column_widths()
        # synchronously here means the viewport width is still 0 (the widget hasn't
        # been inserted into the QStackedWidget yet), so setStretchLastSection has
        # nothing to stretch against and the explicit section widths exceed the
        # viewport once the page becomes visible — causing a spurious horizontal scrollbar.
        QTimer.singleShot(0, self._apply_column_widths)

        # Watch viewport resize events to redistribute long-text columns whenever
        # available width changes (window resize OR vertical-scrollbar
        # appearing/disappearing).  We use a deferred single-shot timer so
        # rapid resize events collapse into one redistribution and so it always
        # runs after Qt has finished updating viewport geometry.
        self._table.viewport().installEventFilter(self)

        vh = self._table.verticalHeader()
        vh.setDefaultSectionSize(_ROW_H)
        # Fixed: users cannot drag row heights.
        vh.setSectionResizeMode(QHeaderView.Fixed)
        self._table.doubleClicked.connect(self._on_double_click)

        # Set badge delegate for title column
        self._setup_badge_delegate()

        # Replace standard scrollbar with custom one for context menu support
        custom_sb = _CustomScrollBar(Qt.Vertical, self._table)
        self._table.setVerticalScrollBar(custom_sb)

        # Floating time bubble shown while dragging the scrollbar
        self._scroll_bubble = _ScrollTimeBubble(self)
        # Data sources are injected in _connect_vm after vm is ready

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
        """Install the date-separator-aware delegate (table-wide).

        Architecture
        ────────────
        _DateSeparatorDelegate acts as the single table-wide delegate.  It owns
        a BookmarkBadgeDelegate instance and calls it for the title column so
        that favicon + bookmark/annotation badge rendering is preserved.  All
        other columns fall through to QStyledItemDelegate's default painting,
        but still get the separator-strip treatment when their row starts a new
        day.
        """
        # Remove any per-column overrides left from a previous call
        for col_idx in range(self._table.model().columnCount()):
            self._table.setItemDelegateForColumn(col_idx, None)

        title_col_idx = self._vm.table_model._key_to_col.get("title")

        # Build the inner badge delegate (handles favicon + badge icons in the
        # title column); None is safe - _DateSeparatorDelegate falls back to Qt
        # default painting when sub_delegate is None.
        badge_delegate = BookmarkBadgeDelegate(self._vm.table_model, self) if title_col_idx is not None else None

        sep_delegate = _DateSeparatorDelegate(
            separator_rows=self._separator_rows,
            sep_counts=self._sep_counts,
            sub_delegate=badge_delegate,
            sub_col=title_col_idx if title_col_idx is not None else 0,
            parent=self,
        )
        # Install as the table-wide delegate (covers every column/row)
        self._table.setItemDelegate(sep_delegate)

    # ── Date-separator marker management ──────────────────────────────────────

    def _on_records_loaded(self, base_row: int, records: list) -> None:
        """Called whenever a page of records is fetched into the model cache.

        Scans the batch and marks rows that start a new calendar day.

        Performance notes
        -----------------
        * Only newly loaded rows are examined - O(batch_size), not O(total).
        * For rows within the batch, the previous record is read directly from
          the *records* list - zero DB access.
        * At the page boundary (local_idx == 0), peek_record_at is used to
          check the cache without triggering a fetch, preventing recursive
          page-load cascades.
        * visit_time is stored in _separator_rows[row] so paint() never needs
          to call model.data() to build the pill label.
        """
        if not records or self._vm.table_model.is_filtered:
            return

        model = self._vm.table_model

        for local_idx, record in enumerate(records):
            row = base_row + local_idx
            if row == 0:
                # First record ever → always a separator
                self._separator_rows[row] = record.visit_time
                continue

            # Get previous record: batch-local when possible, cache-peek otherwise.
            # Never call _get_record_at here — it can trigger _fetch_page which
            # emits records_loaded again, causing an unbounded recursive cascade.
            if local_idx > 0:
                prev = records[local_idx - 1]
            else:
                prev = model.peek_record_at(row - 1)
                if prev is None:
                    # Previous page not in cache — conservatively mark as separator.
                    self._separator_rows[row] = record.visit_time
                    continue

            # Compare calendar days using local-day-number — pure integer
            # arithmetic (one division per timestamp, no Python object allocation).
            # _local_day_number returns (ts + utc_offset) // 86400.
            curr_day = _local_day_number(record.visit_time)
            prev_day = _local_day_number(prev.visit_time)

            if curr_day != prev_day:
                self._separator_rows[row] = record.visit_time
            elif row in self._separator_rows:
                # Row was previously marked as a separator (e.g. after a
                # model reset with different data) - un-mark it.
                del self._separator_rows[row]

        # Schedule a lazy count fetch for any newly visible separator rows.
        # Use the existing debounce timer instead of singleShot(0, ...) to avoid
        # creating a new QTimer object on every page load (~200+ per scroll session).
        # The 300 ms delay is acceptable for cosmetic sep counts.
        if not self._sep_count_timer.isActive():
            self._sep_count_timer.start()

        # Restore scroll position after an in-place mutation (delete/hide/unhide).
        if base_row == 0 and self._pending_scroll_restore is not None:
            saved = self._pending_scroll_restore
            self._pending_scroll_restore = None
            QTimer.singleShot(0, lambda: self._table.verticalScrollBar().setValue(saved))

    def _on_model_reset(self) -> None:
        """Clear separator state when the model is rebuilt (new search / filter).

        Qt's QHeaderView.initializeSections() IS called on endResetModel and
        resets every horizontal section to defaultSectionSize, discarding the
        widths set by _apply_column_widths().  Re-apply them here so the header
        always reflects the user's saved (or default) column widths after any
        model reset, including the initial load triggered by initialize().
        """
        self._separator_rows.clear()
        self._sep_counts.clear()
        self._sep_count_timer.stop()
        if self._pending_scroll_restore is not None:
            # Defer restore until page 0 data arrives.
            pass
        else:
            # Qt's QAbstractItemView also resets the scrollbar in response to
            # modelReset, so we must defer our restore to run after that.
            self._table.verticalScrollBar().setValue(0)
        self._apply_column_widths()

    def _customize_calendar(self, date_edit: QDateEdit):
        """Customize calendar widget appearance for better dark mode support."""
        calendar = date_edit.calendarWidget()
        if calendar is None:
            return

        # Get the appropriate text color based on current theme
        theme = ThemeManager.instance().current
        text_color = QColor("#c0c8d8") if theme == "dark" else QColor("#1e2128")

        # Remove red color from Sunday (use normal text color instead)
        text_format = calendar.weekdayTextFormat(Qt.Sunday)
        text_format.setForeground(QBrush(text_color))
        calendar.setWeekdayTextFormat(Qt.Sunday, text_format)

        # Also customize Saturday to match
        text_format_sat = calendar.weekdayTextFormat(Qt.Saturday)
        text_format_sat.setForeground(QBrush(text_color))
        calendar.setWeekdayTextFormat(Qt.Saturday, text_format_sat)

    def _setup_shortcuts(self):
        """Register keyboard shortcuts from config."""
        self._page_shortcuts: list[QShortcut] = []
        kb = self._config.keybindings.app if self._config else {}

        # Helper: bind a sequence to a slot, optionally scoped to a specific widget.
        def _bind(key: str, fallback: str, slot, widget=None):
            seq = kb.get(key, fallback)
            if not seq:
                return
            parent = widget if widget is not None else self
            sc = QShortcut(QKeySequence(seq), parent)
            if widget is None:
                # Page-level shortcuts: only fire when this page or its children
                # have focus, preventing cross-page conflicts.
                sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._page_shortcuts.append(sc)

        # -- Existing shortcuts (keep original context for compatibility) --
        seq = kb.get("focus_search", "Ctrl+F")
        if seq:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self._focus_search)
            self._page_shortcuts.append(sc)

        seq = kb.get("trigger_sync", "Ctrl+R")
        if seq:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self._trigger_sync)
            self._page_shortcuts.append(sc)

        # Del is scoped to the table so it doesn't intercept from search bar
        seq = kb.get("delete_selected", "Del")
        if seq:
            sc = QShortcut(QKeySequence(seq), self._table)
            sc.activated.connect(self._delete_selected)
            self._page_shortcuts.append(sc)

        # -- New table-scoped shortcuts (only fire when the table has focus) --
        _bind("history_open_selected", "Return", self._open_selected_in_browser, self._table)
        _bind("history_copy_url", "Ctrl+C", self._copy_url_of_selected, self._table)
        _bind("history_copy_title_url", "Ctrl+Shift+C", self._copy_title_url_of_selected, self._table)
        _bind("history_toggle_bookmark", "Ctrl+B", self._toggle_bookmark_shortcut, self._table)
        _bind("history_add_note", "Ctrl+N", self._add_note_shortcut, self._table)
        _bind("history_hide_selected", "", self._hide_selected_shortcut, self._table)

        # Export is page-scoped (useful even when search bar has focus)
        _bind("history_open_export", "Ctrl+E", self._open_export_dialog)

    def apply_keybindings(self) -> None:
        """Re-apply shortcuts after config change."""
        for sc in self._page_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._page_shortcuts.clear()
        self._setup_shortcuts()

    # ── Shortcut action helpers ───────────────────────────────

    def _open_selected_in_browser(self):
        """Open all selected rows in the default browser."""
        records = self._get_selected_records()
        for r in records:
            if r.url:
                try:
                    webbrowser.open(r.url)
                except Exception:
                    pass

    def _copy_url_of_selected(self):
        """Copy URL(s) of selected row(s) to clipboard."""
        records = self._get_selected_records()
        if not records:
            return
        if len(records) == 1:
            QApplication.clipboard().setText(records[0].url)
        else:
            QApplication.clipboard().setText("\n".join(r.url for r in records))

    def _copy_title_url_of_selected(self):
        """Copy 'title\\nurl' of the primary selected row to clipboard."""
        records = self._get_selected_records()
        if not records:
            return
        primary = records[0]
        QApplication.clipboard().setText(f"{primary.title or primary.url}\n{primary.url}")

    def _toggle_bookmark_shortcut(self):
        """Toggle bookmark state for all currently selected rows."""
        records = self._get_selected_records()
        if not records:
            return
        multi = len(records) > 1
        primary = records[0]
        self._toggle_bookmark(records, primary, multi)

    def _add_note_shortcut(self):
        """Open the annotation dialog for the primary selected row."""
        records = self._get_selected_records()
        if not records:
            return
        self._edit_annotation(records[0])

    def _hide_selected_shortcut(self):
        """Hide all currently selected rows."""
        records = self._get_selected_records()
        if not records:
            return
        ids = [r.id for r in records if r.id is not None]
        if ids:
            self._hide_records(ids)

    def _focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def _clear_navigation_filters(self) -> None:
        """Reset navigation controls to the unfiltered history dataset."""
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

    def _begin_locate_navigation(self, generation: int) -> None:
        """Freeze table repaints until the target row can be shown directly."""
        self._active_locate_gen = generation
        self._table.setUpdatesEnabled(False)

    def _finish_locate_navigation(self, generation: int) -> None:
        """Re-enable table repaints for the active locate generation."""
        if self._active_locate_gen != generation:
            return
        self._active_locate_gen = None
        if not self._table.updatesEnabled():
            self._table.setUpdatesEnabled(True)
            self._table.viewport().update()

    def _schedule_locate_row(self, row: int) -> None:
        """Reload the target dataset and reveal *row* once its page is ready."""
        model = self._vm.table_model
        self._filter_url_gen += 1
        _gen = self._filter_url_gen
        target_page_start = (row // PAGE_SIZE) * PAGE_SIZE

        self._pending_scroll_restore = self._table.verticalScrollBar().value()
        self._begin_locate_navigation(_gen)

        def _show_target_row() -> None:
            idx = model.index(row, 0)
            if not idx.isValid():
                self._finish_locate_navigation(_gen)
                return
            self._table.selectionModel().clearSelection()
            self._table.selectionModel().select(
                idx,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            self._table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            self._finish_locate_navigation(_gen)

        def _on_page_loaded(base_row: int, records: list) -> None:
            if self._filter_url_gen != _gen:
                try:
                    model.records_loaded.disconnect(_on_page_loaded)
                except RuntimeError:
                    pass
                return
            if base_row == target_page_start:
                try:
                    model.records_loaded.disconnect(_on_page_loaded)
                except RuntimeError:
                    pass
                QTimer.singleShot(0, _show_target_row)
            elif base_row == 0 and target_page_start > 0:
                target_page_idx = target_page_start // PAGE_SIZE
                QTimer.singleShot(0, lambda: model._fetch_page(target_page_idx))

        model.records_loaded.connect(_on_page_loaded)
        self._do_search(skip_badges=True)

    def filter_by_url(self, url: str):
        """When navigating from 'Locate in History' in the bookmarks page, clear filters and scroll to the row containing the URL."""
        row = self._vm._db.get_row_offset_for_url(
            url,
            excluded_ids=self._vm.table_model._hidden_ids,
            hidden_only=self._vm.hidden_mode,
        )

        # Step 2: clear all filters so the full list is shown
        self._clear_navigation_filters()

        if row < 0:
            # URL not found - fall back to a url: search so the user sees something
            self._search.blockSignals(False)
            self._search.setText(f"url:{url}")
            self._focus_search()
            self._do_search()
            return

        # Step 3: trigger the async reload, then scroll AFTER the page containing
        # the target row has loaded so index->viewport mapping is stable.
        self._schedule_locate_row(row)

    def locate_bookmark(self, bookmark: BookmarkRecord, hidden_mode: bool = False) -> None:
        """Locate a bookmark in history, preferring its bound history_id.

        When history_id is missing or stale, falls back to the most recent
        visible row for the bookmark URL in the target dataset.
        """
        if hidden_mode != self._vm.hidden_mode:
            self.set_hidden_mode(hidden_mode, reload=False)
            if self._vm.hidden_mode != hidden_mode:
                return

        row = -1
        hidden_ids = self._vm.table_model._hidden_ids
        if bookmark.history_id is not None:
            row = self._vm._db.get_row_offset_for_history_id(
                bookmark.history_id,
                excluded_ids=hidden_ids,
                hidden_only=hidden_mode,
            )
        if row < 0:
            row = self._vm._db.get_row_offset_for_url(
                bookmark.url,
                excluded_ids=hidden_ids,
                hidden_only=hidden_mode,
            )

        # Step 2: clear all filters so the target dataset is shown as-is.
        self._clear_navigation_filters()

        if row < 0:
            self._search.setText(f"url:{bookmark.url}")
            self._focus_search()
            self._do_search()
            return

        self._schedule_locate_row(row)

    def filter_by_date(self, date_str: str):
        """Switch to history page and show only records for *date_str* (YYYY-MM-DD)."""
        from PySide6.QtCore import QDate

        try:
            d = QDate.fromString(date_str, "yyyy-MM-dd")
        except Exception:
            return
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._browser_combo.blockSignals(True)
        self._browser_combo.setCurrentIndex(0)
        self._browser_combo.blockSignals(False)
        self._date_from.blockSignals(True)
        self._date_from.setDate(d)
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(True)
        self._date_to.setDate(d)
        self._date_to.blockSignals(False)
        self._do_search()
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
        self._vm.device_list_changed.connect(self._search.set_available_devices)
        self._vm.tag_list_changed.connect(self._search.set_available_tags)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # Trigger regex incremental loading when scrolling to the bottom
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_check_load_more)
        # Floating time bubble on scrollbar drag
        sb = self._table.verticalScrollBar()
        sb.sliderPressed.connect(self._on_sb_pressed)
        sb.sliderReleased.connect(self._on_sb_released)
        self._scroll_bubble_timer.timeout.connect(self._update_scroll_bubble)
        # Hide bubble when app loses focus (e.g. Win key, right-click outside)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        # Inject DB + favicon data sources into the bubble
        self._scroll_bubble.set_data_sources(self._vm._db, self._vm._favicon_manager)
        # Inject config so the bubble can persist the tutorial dismissed state
        self._scroll_bubble.set_config(self._config)
        # Apply saved display mode
        saved_mode = getattr(self._config.ui, "scroll_bubble_mode", "full")
        self._scroll_bubble.set_display_mode(saved_mode)
        # Connect custom scrollbar context menu if using custom scrollbar
        if isinstance(sb, _CustomScrollBar):
            sb.context_menu_requested.connect(self._show_scrollbar_context_menu)
        # Date-separator: track which rows start a new calendar day
        self._vm.table_model.records_loaded.connect(self._on_records_loaded)
        self._vm.table_model.modelReset.connect(self._on_model_reset)
        # Lazy visit-count loading for separator pills.
        # Debounced off the same valueChanged signal already wired above;
        # also connected to the sep_count_timer timeout.
        self._sep_count_timer.timeout.connect(self._load_visible_sep_counts)
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_sep_counts)

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

    def _on_scroll_sep_counts(self, _value: int) -> None:
        """Start the debounce timer on the first scroll event in a burst.

        Previously this called start() on every valueChanged event which
        restarts the QTimer on every pixel of drag (~4000+ calls/session).
        Now we only start it when it is not already running.  The timer fires
        300 ms after it was *first* started, which is acceptable — sep counts
        are cosmetic and a slightly earlier fire is fine.  The timer restarts
        naturally after it fires if scrolling continues.
        """
        if not self._sep_count_timer.isActive():
            self._sep_count_timer.start()

    def _load_visible_sep_counts(self) -> None:
        """Batch-fetch visit counts for every separator row currently visible.

        Called 300 ms after scroll activity ceases (debounced) and also
        immediately (via QTimer.singleShot(0)) after a page of records is
        loaded into the model.

        Algorithm
        ---------
        1. Determine the visible row range from the viewport geometry.
        2. Collect separator rows in that range whose counts are not yet cached.
        3. Compute each row's local-midnight day_start timestamp from the
           already-stored visit_time (no extra DB access needed).
        4. De-duplicate day_starts (multiple rows on the same date share one
           DB count) and issue a single ``get_day_counts_batch`` query.
        5. Populate _sep_counts and trigger a viewport repaint only if new
           data arrived.
        """
        if not self._separator_rows or self._vm._db is None:
            return

        vp = self._table.viewport()
        top_row = self._table.rowAt(0)
        bottom_row = self._table.rowAt(vp.height() - 1)
        if top_row < 0:
            return
        if bottom_row < 0:
            # rowAt returns -1 when the coordinate is below the last row
            bottom_row = self._vm.table_model.rowCount() - 1

        # Collect separator rows in the visible band that lack counts
        missing_rows: dict[int, int] = {}  # row → day_start_ts
        for row, visit_time in self._separator_rows.items():
            if top_row <= row <= bottom_row and row not in self._sep_counts:
                lt = _time.localtime(visit_time)
                day_start = int(
                    _time.mktime(_time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, lt.tm_isdst)))
                )
                missing_rows[row] = day_start

        if not missing_rows:
            return

        # De-duplicate: many rows on the same calendar day share one count
        unique_day_starts = list(set(missing_rows.values()))
        model = self._vm.table_model
        try:
            counts_by_day = self._vm._db.get_day_counts_batch(
                unique_day_starts,
                hidden_only=self._vm.hidden_mode,
                keyword=model._keyword,
                browser_type=model._browser_type,
                excluded_ids=model._hidden_ids if model._hidden_ids else None,
                domain_ids=model._domain_ids,
                excludes=model._excludes,
                title_only=model._title_only,
                url_only=model._url_only,
                bookmarked_only=model._bookmarked_only,
                has_annotation=model._has_annotation,
                bookmark_tag=model._bookmark_tag,
                device_ids=model._device_ids,
            )
        except Exception:
            return

        updated = False
        for row, day_start in missing_rows.items():
            cnt = counts_by_day.get(day_start, 0)
            self._sep_counts[row] = cnt
            updated = True

        if updated:
            # Repaint the entire viewport; Qt coalesces this into a single
            # paint pass — no per-row invalidation needed.
            vp.update()

    def _on_theme_changed(self, theme: str) -> None:
        """Repaint the visible viewport on theme change.

        ThemeManager.apply() temporarily calls setModel(None) then setModel(model)
        to force Qt to re-apply the new stylesheet.

        Column-width note: setModel(None) hides the vertical scrollbar (no content),
        temporarily widening the viewport by the scrollbar width (~6 px).  When
        setModel(model) restores the model the stretch recalculation runs against this
        inflated viewport.  If the page is hidden at the time, Qt never issues a
        follow-up resize event to the header once the scrollbar reappears, so the
        last column stays ~6 px too wide and a spurious horizontal scrollbar appears
        the next time the page is shown.  Deferring _apply_column_widths (same
        pattern as __init__) ensures the call runs after updateGeometries() has
        settled scrollbar visibility and the viewport width is correct.
        """
        self._table.viewport().update()
        self._scroll_bubble.apply_theme(theme)
        # Re-apply calendar customization after theme change
        self._customize_calendar(self._date_from)
        self._customize_calendar(self._date_to)
        # Re-fetch counts lost when modelReset cleared _sep_counts during theme swap.
        if not self._sep_count_timer.isActive():
            self._sep_count_timer.start()
        # Re-apply column widths after the event loop has processed updateGeometries()
        # so that setStretchLastSection uses the correct (scrollbar-adjusted) viewport width.
        # This covers the case where the page is *visible* during the theme change.
        # The hidden-page case is handled by showEvent().
        QTimer.singleShot(0, self._apply_column_widths)

    def showEvent(self, event) -> None:
        """Re-apply column widths each time the page becomes visible.

        When a theme change occurs while this page is hidden the vertical
        scrollbar momentarily disappears (setModel(None) clears all content),
        widening the viewport by the scrollbar width (~6 px).  setStretchLastSection
        recalculates the last column against this inflated viewport.  Because the
        page is hidden, Qt never sends a follow-up resize event to the header once
        the scrollbar reappears, so the stretch stays ~6 px too wide.  The deferred
        timer in _on_theme_changed corrects this when the page is visible during the
        swap, but cannot help for the hidden case.

        Reapplying column widths here — deferred by one event-loop turn so the
        viewport geometry is fully settled — guarantees a correct stretch regardless
        of how many theme changes occurred while the page was hidden.
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_column_widths)

    def _on_sb_pressed(self) -> None:
        mode = self._config.ui.scroll_bubble_mode
        if mode == "hidden":
            return  # Don't show bubble at all
        self._scroll_bubble.on_drag_started()
        self._last_bubble_row: int = -1  # reset row cache on each new drag
        self._last_bubble_sb_val: int = -1  # force first tick to run all work
        self._bubble_settle_count: int = 0  # reset settle counter
        self._scroll_bubble._last_pos_set = False  # force reposition on first tick
        self._update_scroll_bubble()
        self._scroll_bubble.snap_position()  # instant placement on first show
        self._scroll_bubble.show_animated()
        self._scroll_bubble_timer.start()

    def _on_sb_released(self) -> None:
        self._scroll_bubble_timer.stop()
        self._scroll_bubble.hide_animated()

    def _on_focus_changed(self, __old, new) -> None:
        """Hide bubble when focus leaves the application."""
        if new is None:
            self._scroll_bubble.hide_animated()

    def _update_scroll_bubble(self) -> None:
        if self._vm.table_model.rowCount() == 0:
            return

        sb = self._table.verticalScrollBar()
        sb_val = sb.value()

        # Fast-path: if the scrollbar hasn't moved *and* the bubble animation
        # has fully converged for at least _BUBBLE_SETTLE_TICKS consecutive ticks
        # (~180 ms), skip all work until something actually changes.  This
        # eliminates rowAt(), get_visit_time_at_row(), and reposition() overhead
        # during the common case where the user pauses mid-drag to read the date.
        if sb_val == self._last_bubble_sb_val and self._bubble_settle_count >= self._BUBBLE_SETTLE_TICKS:
            return
        self._last_bubble_sb_val = sb_val

        # Use the row at the vertical center of the viewport.
        # This is simpler and more accurate than manual height calculation.
        center_y = self._table.viewport().height() // 2
        row = self._table.rowAt(center_y)

        if row < 0:
            # If center is empty space (e.g., scrolled past the end),
            # try to get the last valid row.
            row = self._vm.table_model.rowCount() - 1

        if row < 0:
            return

        # Skip the expensive set_timestamp + reposition work when the center
        # row hasn't changed since the last timer tick.  reposition() calls
        # QStyle.subControlRect() on every call which is measurably expensive
        last_row = self._last_bubble_row
        ts = self._vm.table_model.get_visit_time_at_row(row)
        if ts is None:
            return

        self._scroll_bubble.set_timestamp(ts)
        if row != last_row:
            self._last_bubble_row = row
            self._scroll_bubble.reposition(self._table.verticalScrollBar(), self)
            # raise_() is only needed when the row (and therefore bubble position)
            # changes.  Calling it on every tick was triggering unnecessary repaints
            # even when the bubble was stationary.  As a Tool window this is now
            # cheaper, but avoiding pointless calls is still good practice.
            self._scroll_bubble.raise_()

        # Advance inertial Y every tick regardless of whether the row changed,
        # so the bubble glides smoothly even during fast continuous scrolling.
        # tick_position() returns True when fully settled.
        settled = self._scroll_bubble.tick_position()
        if settled:
            self._bubble_settle_count += 1
        else:
            self._bubble_settle_count = 0

    def _on_columns_changed(self):
        QTimer.singleShot(0, self._apply_column_widths)
        QTimer.singleShot(0, self._setup_badge_delegate)  # Rebind delegate after column order changes
        QTimer.singleShot(0, self._rebuild_separators_from_cache)

    def _rebuild_separators_from_cache(self):
        """Replay cached pages through _on_records_loaded to restore date separators.

        Called after a column-only model reset (toggle/reorder), which clears
        _separator_rows via _on_model_reset but does not re-emit records_loaded.
        """
        model = self._vm.table_model
        for page_index in sorted(model._page_cache.keys()):
            records = model._page_cache[page_index]
            if records:
                self._on_records_loaded(page_index * PAGE_SIZE, records)

    def _on_section_resized(self, logical_index, old_size, new_size):
        col_key = self._vm.table_model._col_to_key.get(logical_index)
        if col_key and col_key != "browser":
            self._current_widths[col_key] = new_size
            self._col_resize_timer.start(500)

    def _redistribute_long_text_cols(self, hh=None, visible_cols=None, _notify_geometry=True):
        """Distribute available viewport width among visible long-text columns.

        Each long-text column has a preferred width drawn from _current_widths
        (user's last manual resize) or the built-in defaults.  Available space
        is the viewport width minus the sum of all non-long-text column widths.

        - If available >= sum(preferred): distribute the extra space
          proportionally so each column grows in proportion to its preference.
        - If available < sum(preferred): scale down proportionally, respecting
          _MIN_LONG_TEXT_W as a hard floor per column.  If the floors push the
          total beyond available, the table's own horizontal scrollbar handles
          the overflow - we never force columns below their floor.

        _notify_geometry: when False, skip the updateGeometries() call at the
          end.  Pass False when calling from inside _batch_header_update, which
          already calls updateGeometries() in its __exit__.
        """
        if self._in_redistribution:
            return

        if hh is None:
            hh = self._table.horizontalHeader()
        if visible_cols is None:
            visible_cols = self._vm.table_model.get_visible_columns()

        viewport_w = self._table.viewport().width()
        if viewport_w <= 0:
            return

        _defaults = {"title": 340, "url": 420, "domain": 140, "metadata": 240}

        long_indices: list[int] = []
        long_preferred: list[int] = []
        fixed_total = 0
        for idx, col_key in enumerate(visible_cols):
            if col_key in _LONG_TEXT_COLS:
                long_indices.append(idx)
                pref = self._current_widths.get(col_key, _defaults.get(col_key, 120))
                long_preferred.append(max(pref, _MIN_LONG_TEXT_W))
            else:
                fixed_total += hh.sectionSize(idx)

        if not long_indices:
            return

        available = viewport_w - fixed_total
        if available <= 0:
            return

        total_pref = sum(long_preferred)
        if available >= total_pref:
            # Extra space: grow each column proportionally to its preferred width.
            extra = available - total_pref
            new_widths = [p + int(extra * p / total_pref) for p in long_preferred]
            # Assign any leftover pixel from integer rounding to the first column.
            remainder = available - sum(new_widths)
            if remainder > 0:
                new_widths[0] += remainder
        else:
            # Insufficient space: scale down proportionally, floor at _MIN_LONG_TEXT_W.
            # If floors push the total past available, the scrollbar handles overflow.
            new_widths = [max(int(p * available / total_pref), _MIN_LONG_TEXT_W) for p in long_preferred]

        # Early exit: widths unchanged - no resize or geometry update needed.
        # This is the normal outcome of the "correction pass" when the viewport
        # width did not change after updateGeometries(), and it breaks the
        # otherwise-infinite schedule loop (redistribute → updateGeometries →
        # viewport Resize → schedule → redistribute → ...).
        if all(hh.sectionSize(idx) == w for idx, w in zip(long_indices, new_widths, strict=False)):
            return

        self._in_redistribution = True
        try:
            was_blocked = hh.signalsBlocked()
            if not was_blocked:
                hh.blockSignals(True)
            try:
                for idx, w in zip(long_indices, new_widths, strict=False):
                    hh.resizeSection(idx, w)
            finally:
                if not was_blocked:
                    hh.blockSignals(False)
            if _notify_geometry:
                self._table.updateGeometries()
        finally:
            self._in_redistribution = False

    def eventFilter(self, obj, event):
        """Schedule a deferred redistribution whenever the viewport is resized.

        Listening on the viewport means we react to both window resizes AND
        vertical-scrollbar visibility changes (which shrink the viewport by
        ~17px).  Two guards keep the feedback loop clean:

        - _in_redistribution: set True while _redistribute_long_text_cols runs.
          updateGeometries() inside it emits another Resize event; without this
          guard that would schedule another redistribution indefinitely.
        - _col_resize_timer.isActive(): True for 500ms after the user drags a
          column resizer.  Column resizes can also change scrollbar visibility,
          so they also emit a viewport Resize event.  Suppressing redistribution
          during this window preserves the user's manual column width intent.
        """
        if obj is self._table.viewport() and event.type() == QEvent.Resize:
            if not self._in_redistribution and not self._col_resize_timer.isActive():
                self._redist_timer.start(0)
        return super().eventFilter(obj, event)

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
            "title": 340,
            "url": 420,
            "domain": 140,
            "metadata": 240,
            "visit_time": 165,
            "first_visit_time": 165,
        }
        _min_widths = {"visit_time": 140, "first_visit_time": 140}
        for col_key, min_w in _min_widths.items():
            if self._current_widths.get(col_key, min_w) < min_w:
                self._current_widths.pop(col_key, None)

        with self._batch_header_update() as hh:
            hh.setStretchLastSection(False)
            for idx, col_key in enumerate(visible_cols):
                if col_key == "browser":
                    hh.setSectionResizeMode(idx, QHeaderView.Fixed)
                    hh.resizeSection(idx, 48)
                else:
                    hh.setSectionResizeMode(idx, QHeaderView.Interactive)
                    w = self._current_widths.get(col_key, default_widths.get(col_key, 120))
                    hh.resizeSection(idx, w)
            # Redistribute synchronously inside the batch update so that
            # _batch_header_update's updateGeometries() call sees the final
            # column layout.  This eliminates the one-frame flicker that
            # previously occurred between setting raw widths and the deferred
            # _redist_timer firing.
            self._redistribute_long_text_cols(hh, visible_cols, _notify_geometry=False)
        # A deferred correction pass: if updateGeometries() above changed
        # scrollbar visibility (narrowing the viewport by ~17px), the
        # viewport Resize event from eventFilter will schedule _redist_timer.
        # The early-exit in _redistribute_long_text_cols ensures it is a no-op
        # when the viewport width is already stable.

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
                w = fm.horizontalAdvance(str(text)) + 40  # 20px per side for cell padding + safety
                max_w = max(max_w, w)

        max_w = min(max_w, 600)

        # Enforce per-column minimum widths so auto-fit never produces a value
        # that _apply_column_widths would immediately discard on the next call.
        _col_min = {"visit_time": 140, "first_visit_time": 140}
        if col_key in _col_min:
            max_w = max(max_w, _col_min[col_key])

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

        menu = StyledMenu(self)

        all_cols = self._vm.table_model.get_all_columns()
        visible_cols = self._vm.table_model.get_visible_columns()

        # ── 1. Column visibility toggles (inside a submenu) ──
        col_submenu = StyledMenu(_("Columns"), menu)
        col_submenu.setIcon(get_icon("list"))
        for col_key, col_def in all_cols.items():
            label = _(col_def.get("label_key", col_key.title()))
            action = col_submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col_key in visible_cols)
            action.setData(col_key)

            # Keep at least one column visible
            if len(visible_cols) == 1 and col_key in visible_cols:
                action.setEnabled(False)

        menu.addMenu(col_submenu)
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

    def _do_search(self, skip_badges: bool = False):
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
            skip_badges=skip_badges,
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

    def _show_scrollbar_context_menu(self, global_pos: QPoint) -> None:
        """Show custom context menu for scrollbar to change bubble display mode."""
        menu = StyledMenu(self)

        current_mode = self._config.ui.scroll_bubble_mode

        # Four radio-style checkable options
        full_act = menu.addAction(_("Full bubble"))
        full_act.setCheckable(True)
        full_act.setChecked(current_mode == "full")
        full_act.setData("full")

        compact_act = menu.addAction(_("Compact bubble"))
        compact_act.setCheckable(True)
        compact_act.setChecked(current_mode == "compact")
        compact_act.setData("compact")

        minimal_act = menu.addAction(_("Minimal bubble"))
        minimal_act.setCheckable(True)
        minimal_act.setChecked(current_mode == "minimal")
        minimal_act.setData("minimal")

        hidden_act = menu.addAction(_("Hide bubble"))
        hidden_act.setCheckable(True)
        hidden_act.setChecked(current_mode == "hidden")
        hidden_act.setData("hidden")

        action = menu.exec(global_pos)
        if action:
            new_mode = action.data()
            self._config.ui.scroll_bubble_mode = new_mode
            self._config.save()
            self._scroll_bubble.set_display_mode(new_mode)

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

        menu = StyledMenu(self)

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
        copy_menu = StyledMenu(_("Copy"), menu)
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
        actions_menu = StyledMenu(_("Actions"), menu)
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

        # ── Hide / Unhide submenu ─────────────────────────────
        in_hidden_mode = self._vm.hidden_mode
        unhide_rec_act = None
        hide_rec_act = None
        hide_sub_act = None
        hide_main_act = None

        if in_hidden_mode:
            # In hidden-records mode: offer Unhide instead
            if multi:
                unhide_rec_act = actions_menu.addAction(
                    get_icon("eye"), _("Unhide Selected ({n} records)").format(n=len(selected_records))
                )
            else:
                unhide_rec_act = actions_menu.addAction(get_icon("eye"), _("Unhide This Record"))
        else:
            # Normal mode: offer Hide
            hide_menu = StyledMenu(_("Hide…"), actions_menu)
            hide_menu.setIcon(get_icon("eye-off"))

            # Hide this record / selected records
            if multi:
                hide_rec_act = hide_menu.addAction(
                    get_icon("eye-off"), _("Hide Selected ({n} records)").format(n=len(selected_records))
                )
            else:
                hide_rec_act = hide_menu.addAction(get_icon("eye-off"), _("Hide This Record"))

            # Domain-level hide options (single-select only for clarity)
            if primary_domain and not multi:
                hide_menu.addSeparator()
                main_domain = _extract_main_domain(primary_domain)
                if main_domain != primary_domain:
                    # primary_domain is a subdomain - offer both options
                    hide_sub_act = hide_menu.addAction(
                        get_icon("eye-off"),
                        _("Hide Subdomain: {domain}").format(domain=primary_domain),
                    )
                    hide_sub_act.setToolTip(_("Hide only records from {domain}").format(domain=primary_domain))
                    hide_main_act = hide_menu.addAction(
                        get_icon("eye-off"),
                        _("Hide Domain: {domain}").format(domain=main_domain),
                    )
                    hide_main_act.setToolTip(
                        _("Hide records from {domain} and all its subdomains").format(domain=main_domain)
                    )
                else:
                    # primary_domain is already eTLD+1
                    hide_main_act = hide_menu.addAction(
                        get_icon("eye-off"),
                        _("Hide Domain: {domain}").format(domain=primary_domain),
                    )
                    hide_main_act.setToolTip(
                        _("Hide records from {domain} and all its subdomains").format(domain=primary_domain)
                    )
            elif primary_domain and multi:
                # Multi-select: only offer main-domain hide for the primary record's domain
                hide_menu.addSeparator()
                main_domain = _extract_main_domain(primary_domain)
                hide_main_act = hide_menu.addAction(
                    get_icon("eye-off"),
                    _("Hide Domain: {domain}").format(domain=main_domain),
                )
                hide_main_act.setToolTip(
                    _("Hide records from {domain} and all its subdomains").format(domain=main_domain)
                )

            actions_menu.addMenu(hide_menu)

        # Blacklist domain (destructive — kept outside Hide submenu intentionally)
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

        elif unhide_rec_act and action == unhide_rec_act:
            self._unhide_records(ids)

        elif hide_rec_act and action == hide_rec_act:
            self._hide_records(ids)

        elif hide_sub_act and action == hide_sub_act:
            self._hide_domain(primary_domain, subdomain_only=True)

        elif hide_main_act and action == hide_main_act:
            resolved_main = _extract_main_domain(primary_domain) if primary_domain else ""
            target = primary_domain if (primary_domain == resolved_main) else resolved_main
            self._hide_domain(target, subdomain_only=False)

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
            self._pending_scroll_restore = self._table.verticalScrollBar().value()
            self.delete_records_requested.emit(ids)

    def _hide_records(self, ids: list[int]):
        self._pending_scroll_restore = self._table.verticalScrollBar().value()
        self.hide_records_requested.emit(ids)
        self._status_label.setText(_("Hidden {n} record(s). Manage in Settings → Privacy.").format(n=len(ids)))

    def _unhide_records(self, ids: list[int]):
        """Unhide records by emitting the signal, then refresh the view."""
        self._pending_scroll_restore = self._table.verticalScrollBar().value()
        self.unhide_records_requested.emit(ids)
        self._status_label.setText(_("Restored {n} record(s).").format(n=len(ids)))

    def _hide_domain(self, domain: str, subdomain_only: bool) -> None:
        """Show the HideDomainDialog then emit hide_domain_requested if confirmed."""
        if not domain:
            return
        count = self._vm._db.count_records_for_domain(domain, subdomain_only)
        dlg = HideDomainDialog(domain, subdomain_only, count, parent=self)
        if dlg.exec() != HideDomainDialog.Accepted:
            return
        self._pending_scroll_restore = self._table.verticalScrollBar().value()
        self.hide_domain_requested.emit(domain, subdomain_only, dlg.auto_hide)

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
            self._pending_scroll_restore = self._table.verticalScrollBar().value()
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
        self.bookmark_changed.emit()

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

    # ── Hidden-mode toggle ────────────────────────────────────

    def _toggle_hidden_mode(self) -> None:
        """Toggle between normal and hidden-records-only viewing mode."""
        self.set_hidden_mode(not self._vm.hidden_mode)

    def leave_hidden_mode(self) -> None:
        """Exit hidden-mode if active.  Called on window close."""
        self.set_hidden_mode(False)

    @property
    def hidden_mode(self) -> bool:
        """Return whether the page is currently showing hidden records."""
        return self._vm.hidden_mode

    def set_hidden_mode(self, enabled: bool, reload: bool = True) -> None:
        """Programmatically enter or leave hidden mode.  Auth-guarded when entering."""
        if self._vm.hidden_mode == enabled:
            return
        if enabled and self._config and self._config.master_password_hash:
            from src.views.master_password_dialog import require_master_password

            if not require_master_password(self._config.master_password_hash, self):
                return
        self._vm.set_hidden_mode(enabled, reload=reload)
        self._update_hidden_mode_ui()

    def _update_hidden_mode_ui(self) -> None:
        """Sync title, subtitle, icon, and button styling to hidden-mode state."""
        active = self._vm.hidden_mode
        if active:
            self._title_lbl.setText(_("Hidden Records"))
            self._subtitle_lbl.setText(_("Showing only hidden records."))
            self._hidden_mode_btn.setIcon(get_icon("eye"))
            self._hidden_mode_btn.setToolTip(_("Return to normal view"))
            self._hidden_mode_btn.setStyleSheet(
                "QPushButton { border: 1px solid #e05252; border-radius: 6px; background: rgba(224,82,82,0.12); }"
            )
        else:
            self._title_lbl.setText(_("History"))
            self._subtitle_lbl.setText(_("Double-click any row to open the link in browser"))
            self._hidden_mode_btn.setIcon(get_icon("eye-off"))
            self._hidden_mode_btn.setToolTip(_("View hidden records"))
            self._hidden_mode_btn.setStyleSheet("")

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
            hidden_only=vm._hidden_mode,
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
