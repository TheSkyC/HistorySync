# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
import webbrowser

from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QItemSelectionModel,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
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

from src.utils.i18n import N_, _
from src.utils.icon_helper import get_browser_icon, get_icon
from src.utils.logger import get_logger
from src.utils.search_parser import parse_query
from src.utils.theme_manager import ThemeManager
from src.viewmodels.history_viewmodel import ANNOTATION_ROLE, BOOKMARK_ROLE, HistoryViewModel
from src.views.annotation_dialog import AnnotationDialog
from src.views.search_autocomplete import SmartSearchLineEdit

log = get_logger("view.history")

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

    · Today              → translated "Today"
    · Yesterday          → translated "Yesterday"
    · Same calendar year → e.g. "Oct 24  Wednesday"  /  "10月24日 星期三"
    · Earlier year       → e.g. "2023 Dec 1  Wednesday" / "2023年12月1日 星期三"

    Format strings are translatable so each locale can rearrange tokens.
    """

    dt = datetime.fromtimestamp(ts)
    today = date.today()
    record_date = dt.date()
    weekday = _(_WEEKDAY_FULL[dt.weekday()])

    if record_date == today:
        return _("Today")
    if record_date == today - timedelta(days=1):
        return _("Yesterday")
    if dt.year == today.year:
        # Translators: date separator - same year.  tokens: {month} {day} {weekday}
        return _("{month}/{day}  {weekday}").format(month=dt.month, day=dt.day, weekday=weekday)
    # Translators: date separator - different year.  tokens: {year} {month} {day} {weekday}
    return _("{year}/{month}/{day}  {weekday}").format(year=dt.year, month=dt.month, day=dt.day, weekday=weekday)


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


# ── Date-separator constants ──────────────────────────────────────────────────
_SEP_H = 26  # height of the date-separator band in pixels
_ROW_H = 38  # normal cell-content height in pixels
_SEP_TOTAL = _SEP_H + _ROW_H  # total row height when a separator is shown


class _DateSeparatorDelegate(QStyledItemDelegate):
    """Table-wide delegate that injects a Telegram-style date-separator strip
    at the top of every first-of-day row.

    For rows that start a new calendar day the cell's total height is
    ``_SEP_TOTAL`` (_SEP_H + _ROW_H).  The top _SEP_H pixels render the
    separator pill (date label, centered pill background); the bottom _ROW_H
    pixels render the regular cell content, delegated to *sub_delegate* for
    the title column or to the default Qt painting for every other column.

    ``separator_rows`` is a ``dict[int, int]`` mapping row_index → visit_time.
    The visit_time is stored at row-height assignment time so that paint() never
    needs to call model.data() to build the pill label — eliminating the most
    expensive call on the hot paint path.
    """

    def __init__(
        self,
        separator_rows: dict[int, int],
        sub_delegate: QStyledItemDelegate | None = None,
        sub_col: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._sep_rows = separator_rows
        self._sub = sub_delegate  # delegate used for sub_col (title column)
        self._sub_col = sub_col

        # ── Theme color cache ─────────────────────────────────────────────────
        # Avoids calling ThemeManager.instance().current on every paint() call.
        self._cached_theme: str = ""
        self._pill_bg = QColor(0, 0, 0, 14)
        self._pill_border = QColor(0, 0, 0, 28)
        self._pill_text_color = QColor(90, 100, 120)
        self._refresh_theme_cache()

        # ── Pill geometry cache ───────────────────────────────────────────────
        # Maps date-label string → (pill_w, pill_h) so that horizontalAdvance()
        # and QFontMetrics construction are skipped on repeated paint calls for
        # the same date.  Cleared when the font or theme changes.
        self._geometry_cache: dict[str, tuple[int, int]] = {}
        self._pill_font: QFont | None = None
        self._pill_fm: QFontMetrics | None = None
        self._base_font_key: str = ""

    # ── QStyledItemDelegate interface ─────────────────────────────────────────

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        if index.row() in self._sep_rows:
            return QSize(option.rect.width(), _SEP_TOTAL)
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = index.row()
        visit_time = self._sep_rows.get(row)  # None → not a separator row

        if visit_time is None:
            self._paint_cell(painter, option, index)
            return

        # ── Separator row: split the rect into top band + content band ────────
        top_rect = QRect(option.rect.left(), option.rect.top(), option.rect.width(), _SEP_H)
        content_rect = QRect(option.rect.left(), option.rect.top() + _SEP_H, option.rect.width(), _ROW_H)

        # Fill separator band background (matches the view's window color so it
        # blends naturally regardless of alternating-row-colors settings).
        painter.save()
        win_color = option.palette.color(option.palette.ColorRole.Window)
        painter.fillRect(top_rect, win_color)
        painter.restore()

        # Paint the date pill only once — in column 0 (leftmost visible cell).
        # Pass the cached visit_time directly — no model.data() call needed.
        if index.column() == 0:
            self._paint_separator_pill(painter, top_rect, visit_time)

        # Paint the regular cell content in the lower portion
        adj = QStyleOptionViewItem(option)
        adj.rect = content_rect
        self._paint_cell(painter, adj, index)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _refresh_theme_cache(self) -> None:
        """Rebuild cached QColor objects when the active theme changes.

        This is a cheap string comparison on every paint call; the actual
        QColor construction only happens on a real theme switch (~2×/session).
        """
        theme = ThemeManager.instance().current
        if theme == self._cached_theme:
            return
        self._cached_theme = theme
        if theme == "dark":
            self._pill_bg = QColor(255, 255, 255, 22)
            self._pill_border = QColor(255, 255, 255, 38)
            self._pill_text_color = QColor(200, 208, 230)
        else:
            self._pill_bg = QColor(0, 0, 0, 14)
            self._pill_border = QColor(0, 0, 0, 28)
            self._pill_text_color = QColor(90, 100, 120)

    def _get_pill_font_and_fm(self, painter_font: QFont) -> tuple[QFont, QFontMetrics]:
        """Return a cached (QFont, QFontMetrics) pair for the pill text.

        Keyed on the painter's base font family + point size so it survives
        DPI or preference changes, but is only rebuilt when the font actually
        changes (rare during a session).  Clears _geometry_cache on rebuild so
        old pill widths measured with the previous font are discarded.
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

    def _adjust_option_for_sep(self, option, index):
        """Return a copy of option with rect shifted down past the separator band for sep rows."""
        row = index.row()
        if row not in self._sep_rows:
            return option
        adj = QStyleOptionViewItem(option)
        adj.rect = QRect(
            option.rect.left(),
            option.rect.top() + _SEP_H,
            option.rect.width(),
            _ROW_H,
        )
        return adj

    def editorEvent(self, event, model, option, index):
        if self._sub is not None and index.column() == self._sub_col:
            return self._sub.editorEvent(event, model, self._adjust_option_for_sep(option, index), index)
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index):
        if self._sub is not None and index.column() == self._sub_col:
            return self._sub.helpEvent(event, view, self._adjust_option_for_sep(option, index), index)
        return super().helpEvent(event, view, option, index)

    def _paint_separator_pill(self, painter: QPainter, band: QRect, visit_time: int) -> None:
        """Draw a centered pill label with the day string inside *band*.

        ``visit_time`` is passed directly from the ``_sep_rows`` dict — no
        model.data() call is ever made on the hot paint path.
        """
        self._refresh_theme_cache()

        label = _format_separator_date(visit_time)

        # ── Font + metrics (cached) ───────────────────────────────────────────
        pill_font, fm2 = self._get_pill_font_and_fm(painter.font())

        # ── Pill geometry (cached per label string) ───────────────────────────
        geom = self._geometry_cache.get(label)
        if geom is None:
            pad_x, pad_y = 14, 3
            pill_w = fm2.horizontalAdvance(label) + pad_x * 2
            pill_h = fm2.height() + pad_y * 2
            geom = (pill_w, pill_h)
            # Bounded: at most ~365 unique dates + some headroom
            if len(self._geometry_cache) > 400:
                self._geometry_cache.clear()
            self._geometry_cache[label] = geom
        pill_w, pill_h = geom

        pill_x = band.left() + (band.width() - pill_w) // 2
        pill_y = band.top() + (band.height() - pill_h) // 2
        pill_rect = QRect(pill_x, pill_y, pill_w, pill_h)

        # ── Draw pill ─────────────────────────────────────────────────────────
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        radius = pill_h / 2
        path.addRoundedRect(pill_rect.x(), pill_rect.y(), pill_rect.width(), pill_rect.height(), radius, radius)

        painter.fillPath(path, self._pill_bg)
        painter.setPen(QPen(self._pill_border, 0.8))
        painter.drawPath(path)

        painter.setFont(pill_font)
        painter.setPen(self._pill_text_color)
        painter.drawText(pill_rect, Qt.AlignCenter, label)
        painter.restore()


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
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._bg_color = QColor(28, 31, 38, 237)
        self._border_color = QColor(70, 80, 100, 140)

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 9)
        outer.setSpacing(0)

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

        # Divider
        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.HLine)
        self._divider.setFixedHeight(1)
        outer.addSpacing(5)
        outer.addWidget(self._divider)
        outer.addSpacing(5)

        # Domain rows (up to 3)
        self._domain_rows: list[_DomainRow] = []
        for _ in range(3):
            row = _DomainRow(self)
            row.hide()
            outer.addWidget(row)
            self._domain_rows.append(row)

        # Bottom: density bar + total count
        outer.addSpacing(6)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        self._density_bar = _DensityBar(self)
        self._density_bar.setFixedHeight(6)
        self._total_lbl = QLabel()
        self._total_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._total_lbl.setFixedWidth(62)  # Wide enough for "999 records", prevents bar jitter
        bottom_row.addWidget(self._density_bar, 1)
        bottom_row.addWidget(self._total_lbl)
        outer.addLayout(bottom_row)

        # ── Animation ──
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hiding = False
        self._anim.finished.connect(self._on_anim_done)

        self.setFixedWidth(220)
        self.hide()
        self.apply_theme(ThemeManager.instance().current)

    def set_data_sources(self, db, favicon_manager) -> None:
        """Called by HistoryPage after construction to inject data sources."""
        self._db = db
        self._favicon_manager = favicon_manager
        # Precompute the average daily record count for the density bar
        self._refresh_avg_daily()

    def _refresh_avg_daily(self) -> None:
        if self._db is None:
            return
        try:
            stats = self._db.get_db_stats()
            total = getattr(stats, "record_count", 0)

            if total <= 0:
                self._avg_daily = 100.0
                return

            with self._db._conn(write=False) as conn:
                row = conn.execute("SELECT MIN(visit_time), MAX(visit_time) FROM history").fetchone()
                span_days = max((row[1] - row[0]) / 86400, 1) if row and row[0] and row[1] else 365

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
        self._total_lbl.setStyleSheet(f"color: {self._total_color}; font-size: 10px; background: transparent;")
        # Force domain rows to repaint with new colors if data is already loaded
        if self._cached_stats:
            self._render_domain_rows(self._cached_stats)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 12, 12)
        painter.fillPath(path, self._bg_color)
        painter.setPen(self._border_color)
        painter.drawPath(path)

    def set_timestamp(self, ts: int) -> None:
        now = datetime.now()
        dt = datetime.fromtimestamp(ts)

        weekday = _(_WEEKDAY_ABBR[dt.weekday()])  # 0=Mon ... 6=Sun
        new_date = (
            (dt.strftime("%m-%d") + f" {weekday}") if dt.year == now.year else (dt.strftime("%Y-%m-%d") + f" {weekday}")
        )
        new_time = dt.strftime("%H:%M")

        # Always update time label
        if new_time != self._last_time_str:
            self._time_lbl.setText(new_time)
            self._last_time_str = new_time

        # Update day-position indicator on every timestamp change
        day_progress = (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400
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
            self._load_day_stats(dt)
            self.adjustSize()

    def _flush_rank_query(self) -> None:
        """Execute the deferred get_day_rank DB query after the debounce idle period."""
        ts = self._rank_pending_ts
        if ts is None or self._db is None:
            return
        self._rank_pending_ts = None
        try:
            dt = datetime.fromtimestamp(ts)
            day_start = int(datetime(dt.year, dt.month, dt.day, 0, 0, 0).timestamp())
            rank_key = (day_start, ts)
            if rank_key != self._last_rank_key:
                self._last_rank_value = self._db.get_day_rank(day_start, ts)
                self._last_rank_key = rank_key
            total = self._cached_stats.get("total", 1) if self._cached_stats else 1
            self._density_bar.set_record_rank(self._last_rank_value, total)
        except Exception:
            pass

    def _load_day_stats(self, dt: datetime) -> None:
        """Query DB for top domains + total count for the given day."""
        if self._db is None:
            return
        try:
            day_start = int(datetime(dt.year, dt.month, dt.day, 0, 0, 0).timestamp())
            day_end = day_start + 86399
            stats = self._db.get_day_stats(day_start, day_end, top_n=3)
            self._cached_stats = stats
            self._render_domain_rows(stats)
            # Update density bar
            total = stats.get("total", 0)
            density = min(total / max(self._avg_daily, 1.0), 1.0)
            self._density_bar.set_density(density)
            self._total_lbl.setText(_("{n} records").format(n=total))
        except Exception:
            self._cached_stats = None

    def _render_domain_rows(self, stats: dict) -> None:
        """Populate domain row widgets from cached stats."""
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

    def show_animated(self) -> None:
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

    def reposition(self, sb: QScrollBar, page: QWidget) -> None:
        opt = QStyleOptionSlider()
        sb.initStyleOption(opt)
        thumb_rect = sb.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            opt,
            QStyle.SubControl.SC_ScrollBarSlider,
            sb,
        )
        thumb_center_y = sb.mapTo(page, QPoint(0, thumb_rect.center().y())).y()
        sb_left_x = sb.mapTo(page, QPoint(0, 0)).x()
        x = sb_left_x - self.width() - 8
        y = max(0, min(thumb_center_y - self.height() // 2, page.height() - self.height()))
        self.move(x, y)


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
        self._scroll_bubble_timer = QTimer(self)
        self._scroll_bubble_timer.setInterval(60)
        self._scroll_bubble_timer.timeout.connect(self._update_scroll_bubble)

        self._separator_rows: dict[int, int] = {}

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

        vh = self._table.verticalHeader()
        vh.setDefaultSectionSize(_ROW_H)
        # Fixed: users cannot drag row heights, but resizeSection() still works
        # programmatically — used by _on_records_loaded to enlarge separator rows.
        vh.setSectionResizeMode(QHeaderView.Fixed)
        self._table.doubleClicked.connect(self._on_double_click)

        # Set badge delegate for title column
        self._setup_badge_delegate()

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
            sub_delegate=badge_delegate,
            sub_col=title_col_idx if title_col_idx is not None else 0,
            parent=self,
        )
        # Install as the table-wide delegate (covers every column/row)
        self._table.setItemDelegate(sep_delegate)

    # ── Date-separator row-height management ──────────────────────────────────

    def _on_records_loaded(self, base_row: int, records: list) -> None:
        """Called whenever a page of records is fetched into the model cache.

        Scans the batch, decides which rows start a new calendar day compared
        to the row immediately before them, and resizes those rows to
        _SEP_TOTAL so the separator strip has space to render.

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
        if not records:
            return

        model = self._vm.table_model
        vh = self._table.verticalHeader()

        for local_idx, record in enumerate(records):
            row = base_row + local_idx
            if row == 0:
                # First record ever → always a separator
                self._separator_rows[row] = record.visit_time
                vh.resizeSection(row, _SEP_TOTAL)
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
                    vh.resizeSection(row, _SEP_TOTAL)
                    continue

            curr_day = date.fromtimestamp(record.visit_time)
            prev_day = date.fromtimestamp(prev.visit_time)

            if curr_day != prev_day:
                if row not in self._separator_rows:
                    self._separator_rows[row] = record.visit_time
                    vh.resizeSection(row, _SEP_TOTAL)
            elif row in self._separator_rows:
                # Row was previously marked as a separator (e.g. after a
                # model reset with different data) - un-mark it.
                del self._separator_rows[row]
                vh.resizeSection(row, _ROW_H)

    def _on_model_reset(self) -> None:
        """Clear separator state when the model is rebuilt (new search / filter).

        Qt does NOT automatically reset per-section sizes on beginResetModel /
        endResetModel, so we must restore every enlarged row back to _ROW_H
        before dropping the separator_rows dict.
        """
        vh = self._table.verticalHeader()
        for row in self._separator_rows:
            vh.resizeSection(row, _ROW_H)
        self._separator_rows.clear()

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
        self._vm.device_list_changed.connect(self._search.set_available_devices)
        self._vm.tag_list_changed.connect(self._search.set_available_tags)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # Trigger regex incremental loading when scrolling to the bottom
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_check_load_more)
        # Floating time bubble on scrollbar drag
        sb = self._table.verticalScrollBar()
        sb.sliderPressed.connect(self._on_sb_pressed)
        sb.sliderReleased.connect(self._on_sb_released)
        # Hide bubble when app loses focus (e.g. Win key, right-click outside)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        # Inject DB + favicon data sources into the bubble
        self._scroll_bubble.set_data_sources(self._vm._db, self._vm._favicon_manager)
        # Date-separator: track which rows start a new calendar day
        self._vm.table_model.records_loaded.connect(self._on_records_loaded)
        self._vm.table_model.modelReset.connect(self._on_model_reset)

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

    def _on_theme_changed(self, theme: str) -> None:
        """Repaint the visible viewport on theme change.

        ThemeManager.apply() temporarily calls setModel(None) then setModel(model)
        to force Qt to re-apply the new stylesheet.  Qt's QHeaderView.initializeSections()
        resets every section to defaultSectionSize during that swap, discarding the
        per-row resizeSection() calls that gave separator rows their extra height
        (_SEP_TOTAL instead of _ROW_H).  Re-apply those sizes here so the total
        content height is restored before the next paint, preventing the brief
        upward jump caused by vbar.setValue() operating on a shrunken content area.
        """
        vh = self._table.verticalHeader()
        for row in self._separator_rows:
            vh.resizeSection(row, _SEP_TOTAL)
        self._table.viewport().update()
        self._scroll_bubble.apply_theme(theme)

    def _on_sb_pressed(self) -> None:
        self._update_scroll_bubble()
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
        sb = self._table.verticalScrollBar()
        pos = sb.sliderPosition()
        vh = self._table.verticalHeader()
        row = vh.logicalIndexAt(pos)
        if row < 0:
            row_h = max(vh.defaultSectionSize(), 1)
            row = max(pos // row_h, 0)

        ts = self._vm.table_model.get_visit_time_at_row(row)
        if ts is None:
            return
        self._scroll_bubble.set_timestamp(ts)
        self._scroll_bubble.reposition(self._table.verticalScrollBar(), self)
        self._scroll_bubble.raise_()

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
