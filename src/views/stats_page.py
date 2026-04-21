# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import calendar
import collections
from dataclasses import dataclass
import datetime
import math
from pathlib import Path
import random
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import N_, _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.styled_menu import StyledMenu
from src.utils.theme_manager import ThemeManager

if TYPE_CHECKING:
    from src.services.local_db import LocalDatabase

log = get_logger("view.stats")

# ── Month name table ─────────────────────────────────────────────────────────
# Full month names marked for translation.  Use _MONTH_NAMES[month - 1] to get
# the N_()-marked string, then wrap with _() at the point of display so the
# active locale is applied at runtime, not at import time.
_MONTH_NAMES = [
    N_("January"),
    N_("February"),
    N_("March"),
    N_("April"),
    N_("May"),
    N_("June"),
    N_("July"),
    N_("August"),
    N_("September"),
    N_("October"),
    N_("November"),
    N_("December"),
]

# ── Colour palettes ─────────────────────────────────────────────────────────

# Per-theme heatmap colour ramps  (background → max-activity)
_DARK_HEATMAP = [
    QColor("#1a1d23"),  # level 0 - empty cell (bg)
    QColor("#0e3d1e"),  # level 1
    QColor("#1a6b34"),  # level 2
    QColor("#26a64f"),  # level 3
    QColor("#39d96b"),  # level 4 - highest
]
_LIGHT_HEATMAP = [
    QColor("#ebedf0"),  # level 0 - empty cell
    QColor("#9be9a8"),  # level 1
    QColor("#40c463"),  # level 2
    QColor("#30a14e"),  # level 3
    QColor("#216e39"),  # level 4 - highest
]

# Browser colour wheel (distinct, accessible)
_BROWSER_COLORS = [
    QColor("#5b9cf6"),  # blue
    QColor("#f59e0b"),  # amber
    QColor("#4ade80"),  # green
    QColor("#f472b6"),  # pink
    QColor("#a78bfa"),  # violet
    QColor("#fb923c"),  # orange
    QColor("#34d399"),  # teal
    QColor("#60a5fa"),  # sky-blue
    QColor("#e879f9"),  # fuchsia
    QColor("#94a3b8"),  # slate (fallback)
]


def _is_dark() -> bool:
    tm = ThemeManager.instance()
    return tm.current == "dark"


def _heatmap_palette() -> list[QColor]:
    return _DARK_HEATMAP if _is_dark() else _LIGHT_HEATMAP


@dataclass(frozen=True)
class _Palette:
    """Centralised colour definitions for one theme variant.

    Add a new theme by creating another ``_Palette`` instance and returning it
    from ``_palette()``.  All widgets call the six helper functions below, so
    no widget code needs to change when themes are added or modified.
    """

    card_bg: QColor
    card_border: QColor
    text_primary: QColor
    text_muted: QColor
    accent: QColor
    bg_page: QColor


_DARK_PALETTE = _Palette(
    card_bg=QColor("#20232c"),
    card_border=QColor("#252830"),
    text_primary=QColor("#e8eaf0"),
    text_muted=QColor("#5e6d87"),
    accent=QColor("#5b9cf6"),
    bg_page=QColor("#1a1d23"),
)

_LIGHT_PALETTE = _Palette(
    card_bg=QColor("#ffffff"),
    card_border=QColor("#d8dce8"),
    text_primary=QColor("#1e2128"),
    text_muted=QColor("#6b7280"),
    accent=QColor("#2563eb"),
    bg_page=QColor("#f0f2f5"),
)


def _palette() -> _Palette:
    """Return the active palette for the current theme."""
    return _DARK_PALETTE if _is_dark() else _LIGHT_PALETTE


# Convenience accessors — preserve the existing call-site API.
def _card_bg() -> QColor:
    return _palette().card_bg


def _card_border() -> QColor:
    return _palette().card_border


def _text_primary() -> QColor:
    return _palette().text_primary


def _text_muted() -> QColor:
    return _palette().text_muted


def _accent() -> QColor:
    return _palette().accent


def _bg_page() -> QColor:
    return _palette().bg_page


# ── Data-loading worker ──────────────────────────────────────────────────────


class _StatsLoader(QObject):
    """Runs heavy DB queries in a background thread."""

    # heatmap_daily, stats_daily, browser, hourly, top_domains, years
    finished = Signal(object, object, object, object, list, list)

    def __init__(self, db: LocalDatabase, year: int | None, month: int | None = None, heatmap_year: int | None = None):
        super().__init__()
        self._db = db
        self._year = year
        self._month = month
        # Heatmap always shows a full year; for overview mode this is the latest year.
        self._heatmap_year = heatmap_year or year

    def run(self):
        try:
            heatmap_daily = self._db.get_daily_visit_counts(self._heatmap_year)
            stats_daily = self._db.get_daily_visit_counts(self._year, self._month)
            browser = self._db.get_browser_visit_counts(self._year, self._month)
            hourly = self._db.get_hourly_visit_counts(self._year, self._month)
            top_domains = self._db.get_top_domains(10, self._year, self._month)
            years = self._db.get_available_years()
            self.finished.emit(heatmap_daily, stats_daily, browser, hourly, top_domains, years)
        except Exception as exc:
            log.error("StatsLoader error: %s", exc)
            self.finished.emit({}, {}, {}, {}, [], [])


# ── Heatmap day-detail popup ─────────────────────────────────────────────────


class _HeatmapPopup(QWidget):
    """Floating bubble shown when hovering a heatmap cell.

    Displays:
    - Date header + total visit count
    - 24-bar hourly activity chart (bottom-aligned, QPainter)
    - Top 3 domains with visit counts
    """

    _W = 230
    _CHART_H = 48
    _PAD = 12

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._date_str = ""
        self._total = 0
        self._hourly: dict[int, int] = {}
        self._domains: list[tuple[str, int]] = []
        self._favicon_manager = None

        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)

        self.setFixedWidth(self._W)
        self.hide()

    def show_for(
        self, date_str: str, total: int, hourly: dict[int, int], domains: list[tuple[str, int]], global_pos: QPoint
    ):
        self._date_str = date_str
        self._total = total
        self._hourly = hourly
        self._domains = domains[:3]
        self._update_height()
        self._position(global_pos)
        self.update()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.96)
        self._anim.start()

    def hide_animated(self):
        if not self.isVisible():
            return
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._on_fade_done, Qt.UniqueConnection)
        self._anim.start()

    def _on_fade_done(self):
        self._anim.finished.disconnect(self._on_fade_done)
        if self.windowOpacity() < 0.05:
            self.hide()

    def _update_height(self):
        p = self._PAD
        h = p + 18 + 6 + self._CHART_H + 6  # header + gap + chart + gap
        if self._domains:
            h += 1 + 6 + len(self._domains) * 20 + 4  # divider + domains
        h += p
        self.setFixedHeight(h)

    def _position(self, global_pos: QPoint):
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        x = global_pos.x() + 16
        y = global_pos.y() - self.height() // 2
        if x + self._W > sg.right() - 4:
            x = global_pos.x() - self._W - 8
        y = max(sg.top() + 4, min(y, sg.bottom() - self.height() - 4))
        self.move(x, y)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        is_dark = _is_dark()
        bg = QColor(22, 25, 34, 242) if is_dark else QColor(250, 251, 255, 245)
        border = QColor(70, 80, 100, 130) if is_dark else QColor(200, 208, 228, 180)
        text_main = QColor("#e2e5f0") if is_dark else QColor("#1a1e2e")
        text_muted = QColor("#5a6580") if is_dark else QColor("#8896b0")
        accent = QColor("#5b9cf6") if is_dark else QColor("#2563eb")
        divider_c = QColor("#2e3347") if is_dark else QColor("#dde2f0")
        domain_c = QColor("#b0b8d0") if is_dark else QColor("#3a4260")
        count_c = QColor("#5a9cf8") if is_dark else QColor("#2563eb")

        pad = self._PAD
        w = self.width()

        # ── Background card ──────────────────────────────────────────────
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, self.height() - 1), 12, 12)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1))
        p.drawPath(path)

        y = pad

        # ── Date + total ─────────────────────────────────────────────────
        try:
            import datetime as _dt

            d = _dt.date.fromisoformat(self._date_str)
            friendly = d.strftime("%b %d, %Y")
        except ValueError:
            friendly = self._date_str

        font_date = QFont()
        font_date.setPointSize(10)
        font_date.setBold(True)
        p.setFont(font_date)
        p.setPen(QPen(text_main))
        p.drawText(pad, y + 13, friendly)

        font_cnt = QFont()
        font_cnt.setPointSize(9)
        p.setFont(font_cnt)
        p.setPen(QPen(accent))
        cnt_str = f"{self._total:,}"
        fm = QFontMetrics(font_cnt)
        p.drawText(w - pad - fm.horizontalAdvance(cnt_str), y + 13, cnt_str)

        y += 18 + 6

        # ── Hourly bar chart ─────────────────────────────────────────────
        chart_x = pad
        chart_w = w - pad * 2
        chart_h = self._CHART_H
        max_v = max(self._hourly.values(), default=1) or 1
        bar_w = chart_w / 24
        gap = max(1.0, bar_w * 0.18)
        real_bw = bar_w - gap

        bar_fill = QColor(91, 156, 246, 200) if is_dark else QColor(37, 99, 235, 180)
        bar_bg = QColor(91, 156, 246, 45) if is_dark else QColor(37, 99, 235, 30)

        for hour in range(24):
            bx = chart_x + hour * bar_w + gap / 2
            cnt = self._hourly.get(hour, 0)
            bh = int(cnt / max_v * (chart_h - 2)) if max_v else 0

            # background track (full height, bottom-aligned)
            p.setBrush(bar_bg)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(bx, y, real_bw, chart_h), 2, 2)

            # filled portion (bottom-aligned)
            if bh > 0:
                p.setBrush(bar_fill)
                p.drawRoundedRect(QRectF(bx, y + chart_h - bh, real_bw, bh), 2, 2)

        # hour axis labels
        font_axis = QFont()
        font_axis.setPointSize(7)
        p.setFont(font_axis)
        p.setPen(QPen(text_muted))
        fm_ax = QFontMetrics(font_axis)
        for label, hour in (("0", 0), ("12", 12), ("23", 23)):
            lx = chart_x + hour * bar_w + real_bw / 2 - fm_ax.horizontalAdvance(label) / 2
            p.drawText(int(lx), y + chart_h + 10, label)

        y += chart_h + 14

        # ── Divider ──────────────────────────────────────────────────────
        if self._domains:
            p.setPen(QPen(divider_c, 1))
            p.drawLine(pad, y, w - pad, y)
            y += 6

            # ── Top domains ──────────────────────────────────────────────
            font_dom = QFont()
            font_dom.setPointSize(9)
            p.setFont(font_dom)
            fm_dom = QFontMetrics(font_dom)
            row_h = 20
            icon_sz = 12
            icon_gap = icon_sz + 4

            for host, cnt in self._domains:
                icon_y = y + (row_h - icon_sz) // 2
                text_y = y + fm_dom.ascent() + (row_h - fm_dom.height()) // 2

                # Favicon
                drew_icon = False
                if self._favicon_manager:
                    try:
                        px = self._favicon_manager.get_pixmap(f"https://{host}", size=icon_sz)
                        if px and not px.isNull():
                            p.drawPixmap(pad, icon_y, px)
                            drew_icon = True
                    except Exception:
                        pass

                text_offset = pad + (icon_gap if drew_icon else 0)
                max_label_w = w - text_offset - pad - 30

                # domain name
                p.setPen(QPen(domain_c))
                clipped = fm_dom.elidedText(host, Qt.ElideRight, max_label_w)
                p.drawText(text_offset, text_y, clipped)
                # count
                p.setPen(QPen(count_c))
                cs = str(cnt)
                p.drawText(w - pad - fm_dom.horizontalAdvance(cs), text_y, cs)
                y += row_h

        p.end()


# ── Heatmap widget ───────────────────────────────────────────────────────────


class HeatmapWidget(QWidget):
    """GitHub-contribution-graph style heatmap.

    Layout (left-to-right):
        • 3-char weekday labels on the left margin
        • 52 (or 53) week columns, 7 cells each, top = Mon … bottom = Sun
        • Month name labels along the top
    """

    CELL = 13  # cell size in px
    GAP = 3  # gap between cells
    STEP = CELL + GAP

    LEFT_MARGIN = 28  # room for weekday labels
    TOP_MARGIN = 22  # room for month labels
    RADIUS = 3  # rounded-rect corner radius

    view_day_requested = Signal(str)  # emits YYYY-MM-DD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._daily: dict[str, int] = {}
        self._year: int = datetime.date.today().year
        self._max_count: int = 1
        self._db = None  # set by StatsPage after construction
        self._day_cache: collections.OrderedDict[str, tuple] = (
            collections.OrderedDict()
        )  # LRU: date_str → (hourly, top_domains)
        self._day_cache_max = 120
        self._highlight_month: int | None = None
        self._highlight_path: QPainterPath | None = None
        self._hover_date: str = ""
        self._last_mouse_pos = QPoint()
        self._popup = _HeatmapPopup()
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_popup)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def load(self, daily: dict[str, int], year: int):
        self._daily = daily
        self._year = year
        self._max_count = max(daily.values(), default=1)
        self._recalc_size()
        self._rebuild_highlight_path()
        self.update()

    def set_highlight_month(self, month: int | None):
        self._highlight_month = month
        self._rebuild_highlight_path()
        self.update()

    def _rebuild_highlight_path(self):
        """Build and cache the QPainterPath for the highlighted month.

        Each day cell is expanded by 0.5 px on all sides so adjacent cells
        overlap slightly, allowing QPainterPath.united() to merge them into
        a single smooth outer contour.  The path is rebuilt whenever the
        year or the highlighted month changes.
        """
        if not self._highlight_month:
            self._highlight_path = None
            return
        year = self._year
        month = self._highlight_month
        jan1 = datetime.date(year, 1, 1)
        start_weekday = jan1.weekday()
        last_day_num = calendar.monthrange(year, month)[1]
        expand = 0.5
        r = float(self.RADIUS)
        path = QPainterPath()
        for day in range(1, last_day_num + 1):
            d = datetime.date(year, month, day)
            day_offset = (d - jan1).days
            col = (start_weekday + day_offset) // 7
            row = d.weekday()
            x = self.LEFT_MARGIN + col * self.STEP - expand
            y = self.TOP_MARGIN + row * self.STEP - expand
            cell_path = QPainterPath()
            cell_path.addRoundedRect(QRectF(x, y, self.STEP + expand * 2, self.STEP + expand * 2), r, r)
            path = path.united(cell_path)
        self._highlight_path = path

    # ── Geometry ───────────────────────────────────────────────────────────

    def _weeks_in_year(self) -> int:
        jan1 = datetime.date(self._year, 1, 1)
        dec31 = datetime.date(self._year, 12, 31)
        # ISO week of last day; usually 52 or 53
        # We want the number of *columns* in GitHub layout (week starts Monday)
        start_col = jan1.weekday()  # 0=Mon … 6=Sun
        total_days = (dec31 - jan1).days + 1
        return math.ceil((start_col + total_days) / 7)

    def _recalc_size(self):
        weeks = self._weeks_in_year()
        w = self.LEFT_MARGIN + weeks * self.STEP
        h = self.TOP_MARGIN + 7 * self.STEP
        self.setFixedSize(w, h)

    def sizeHint(self) -> QSize:
        weeks = self._weeks_in_year()
        return QSize(
            self.LEFT_MARGIN + weeks * self.STEP,
            self.TOP_MARGIN + 7 * self.STEP,
        )

    # ── Painting ───────────────────────────────────────────────────────────

    def _color_for(self, count: int) -> QColor:
        import math

        palette = _heatmap_palette()
        if count == 0:
            return palette[0]
        # Log scaling: more sensitive to low counts
        ratio = math.log1p(count) / math.log1p(self._max_count)
        if ratio < 0.15:
            return palette[1]
        if ratio < 0.40:
            return palette[2]
        if ratio < 0.70:
            return palette[3]
        return palette[4]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Fill with card background so export always shows #ffffff (light) / dark bg
        p.fillRect(self.rect(), _card_bg())

        year = self._year
        jan1 = datetime.date(year, 1, 1)
        dec31 = datetime.date(year, 12, 31)

        # Monday-based column offset for Jan 1
        start_weekday = jan1.weekday()  # 0=Mon
        total_days = (dec31 - jan1).days + 1

        # ── Month highlight (month-granularity mode) ─────────────────────
        # Fill and outline are drawn AFTER cells (see end of cell loop below)
        # so the outline sits on top of the cell colours.

        font_small = QFont()
        font_small.setPointSize(9)
        p.setFont(font_small)

        # ── Month labels ────────────────────────────────────────────────
        p.setPen(QPen(_text_muted()))
        month_starts: list[tuple[int, str]] = []  # (col_index, abbr)
        for m in range(1, 13):
            first = datetime.date(year, m, 1)
            if first > dec31:
                break
            days_from_jan1 = (first - jan1).days
            col = (start_weekday + days_from_jan1) // 7
            abbr = calendar.month_abbr[m]
            month_starts.append((col, abbr))

        # Draw month labels (skip if too close to previous)
        prev_x = -99
        muted = _text_muted()
        muted_dim = QColor(muted.red(), muted.green(), muted.blue(), 80 if self._highlight_month else 255)
        for col, abbr in month_starts:
            x = self.LEFT_MARGIN + col * self.STEP
            if x - prev_x >= 28:
                m_num = calendar.month_abbr[:].index(abbr) if abbr in calendar.month_abbr else 0
                if self._highlight_month and m_num == self._highlight_month:
                    p.setPen(QPen(_accent()))
                    font_bold = QFont(font_small)
                    font_bold.setBold(True)
                    p.setFont(font_bold)
                else:
                    p.setPen(QPen(muted_dim))
                    p.setFont(font_small)
                p.drawText(x, self.TOP_MARGIN - 5, abbr)
                prev_x = x

        # ── Weekday labels ──────────────────────────────────────────────
        day_labels = [_("Mon"), _("Wed"), _("Fri")]  # display only alternate rows
        day_rows = [0, 2, 4]
        for label, row in zip(day_labels, day_rows, strict=False):
            y = self.TOP_MARGIN + row * self.STEP + self.CELL
            p.drawText(0, y, label[:3])

        # ── Cells ───────────────────────────────────────────────────────
        for day_offset in range(total_days):
            d = jan1 + datetime.timedelta(days=day_offset)
            col = (start_weekday + day_offset) // 7
            row = d.weekday()  # 0=Mon

            x = self.LEFT_MARGIN + col * self.STEP
            y = self.TOP_MARGIN + row * self.STEP

            date_str = d.strftime("%Y-%m-%d")
            count = self._daily.get(date_str, 0)
            color = self._color_for(count)

            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRect(x, y, self.CELL, self.CELL), self.RADIUS, self.RADIUS)

        # ── Dim non-highlighted months ───────────────────────────────────
        if self._highlight_path is not None:
            # Subtle fill + 2px outline on top of everything
            accent = _accent()
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 22))
            p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 180), 2))
            p.drawPath(self._highlight_path)

        p.end()

    # ── Tooltip ─────────────────────────────────────────────────────────

    def _date_at(self, mx: float, my: float) -> str | None:
        """Return YYYY-MM-DD for the cell under (mx, my), or None."""
        col = int((mx - self.LEFT_MARGIN) / self.STEP)
        row = int((my - self.TOP_MARGIN) / self.STEP)
        if col >= 0 and 0 <= row <= 6:
            jan1 = datetime.date(self._year, 1, 1)
            dec31 = datetime.date(self._year, 12, 31)
            max_offset = (dec31 - jan1).days  # 364 for normal years, 365 for leap years
            day_offset = col * 7 + row - jan1.weekday()
            if 0 <= day_offset <= max_offset:
                d = jan1 + datetime.timedelta(days=day_offset)
                if d.year == self._year:
                    return d.strftime("%Y-%m-%d")
        return None

    def _fetch_day_data(self, date_str: str) -> tuple[dict[int, int], list[tuple[str, int]]]:
        """Return (hourly_counts, top_domains) for date_str, using an LRU cache."""
        if date_str in self._day_cache:
            # Move to end to mark as most-recently used
            self._day_cache.move_to_end(date_str)
            return self._day_cache[date_str]
        if self._db is None:
            return {}, []
        try:
            import datetime as _dt

            d = _dt.date.fromisoformat(date_str)
            day_start = int(_dt.datetime(d.year, d.month, d.day).timestamp())
            day_end = day_start + 86400  # half-open interval, consistent with get_day_hourly_counts
            stats = self._db.get_day_stats(day_start, day_end, top_n=3)
            hourly = self._db.get_day_hourly_counts(date_str)
            top_domains = stats.get("domains", [])
        except Exception:
            hourly, top_domains = {}, []
        # Evict oldest entry when over capacity
        while len(self._day_cache) >= self._day_cache_max:
            self._day_cache.popitem(last=False)
        self._day_cache[date_str] = (hourly, top_domains)
        return self._day_cache[date_str]

    def _show_popup(self):
        date_str = self._hover_date
        if not date_str:
            return
        count = self._daily.get(date_str, 0)
        if count == 0:
            return
        hourly, top_domains = self._fetch_day_data(date_str)
        self._popup._favicon_manager = self._favicon_manager
        cursor_pos = self.mapToGlobal(self._last_mouse_pos)
        self._popup.show_for(date_str, count, hourly, top_domains, cursor_pos)

    def mouseMoveEvent(self, event):
        self._last_mouse_pos = event.position().toPoint()
        date_str = self._date_at(event.position().x(), event.position().y())
        if date_str and self._daily.get(date_str, 0) > 0:
            if date_str != self._hover_date:
                self._hover_date = date_str
                self._tooltip_timer.start(180)
                # update position if popup already visible
                if self._popup.isVisible():
                    self._show_popup()
        else:
            self._hover_date = ""
            self._tooltip_timer.stop()
            self._popup.hide_animated()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_date = ""
        self._tooltip_timer.stop()
        self._popup.hide_animated()
        super().leaveEvent(event)

    def _on_context_menu(self, pos: QPoint):
        date_str = self._date_at(pos.x(), pos.y())
        if not date_str or self._daily.get(date_str, 0) == 0:
            return
        try:
            d = datetime.date.fromisoformat(date_str)
            friendly = d.strftime("%B %d, %Y")
        except ValueError:
            friendly = date_str
        menu = StyledMenu(self)
        action = menu.addAction(_("View records for {date}").format(date=friendly))
        if menu.exec(self.mapToGlobal(pos)) == action:
            self.view_day_requested.emit(date_str)


# ── Pie chart widget ─────────────────────────────────────────────────────────


class _ChartTooltip(QWidget):
    """Lightweight floating tooltip for chart widgets (pie / bar)."""

    _W = 180
    _PAD = 10

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._lines: list[tuple[str, str, QColor | None]] = []  # (text, role, color)
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self.setFixedWidth(self._W)
        self.hide()

    def show_lines(self, lines: list[tuple[str, str, QColor | QPixmap | None]], global_pos: QPoint):
        """lines: list of (text, role, icon) where role is 'title'|'value'|'sub',
        icon is QPixmap (shown as-is), QColor (shown as swatch), or None."""
        self._lines = lines
        self._update_height()
        self._position(global_pos)
        self.update()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.95)
        self._anim.start()

    def hide_animated(self):
        if not self.isVisible():
            return
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._on_fade_done, Qt.UniqueConnection)
        self._anim.start()

    def _on_fade_done(self):
        self._anim.finished.disconnect(self._on_fade_done)
        if self.windowOpacity() < 0.05:
            self.hide()

    def _update_height(self):
        h = self._PAD
        for line in self._lines:
            h += 18 if line[1] == "title" else 16
        h += self._PAD
        self.setFixedHeight(h)

    def _position(self, global_pos: QPoint):
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        x = global_pos.x() + 14
        y = global_pos.y() - self.height() // 2
        if x + self._W > sg.right() - 4:
            x = global_pos.x() - self._W - 8
        y = max(sg.top() + 4, min(y, sg.bottom() - self.height() - 4))
        self.move(x, y)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        is_dark = _is_dark()
        bg = QColor(22, 25, 34, 240) if is_dark else QColor(250, 251, 255, 245)
        border = QColor(70, 80, 100, 120) if is_dark else QColor(200, 208, 228, 180)
        text_main = QColor("#e2e5f0") if is_dark else QColor("#1a1e2e")
        text_muted = QColor("#5a6580") if is_dark else QColor("#8896b0")

        w = self.width()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, self.height() - 1), 10, 10)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1))
        p.drawPath(path)

        pad = self._PAD
        y = pad
        for text, role, icon in self._lines:
            if role == "title":
                font = QFont()
                font.setPointSize(10)
                font.setBold(True)
                p.setFont(font)
                fm = QFontMetrics(font)
                if isinstance(icon, QPixmap) and not icon.isNull():
                    icon_sz = 14
                    icon_scaled = icon.scaled(icon_sz, icon_sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    p.drawPixmap(pad, y + (18 - icon_sz) // 2, icon_scaled)
                    p.setPen(QPen(text_main))
                    p.drawText(pad + icon_sz + 4, y + fm.ascent(), text)
                elif isinstance(icon, QColor):
                    p.setBrush(icon)
                    p.setPen(Qt.NoPen)
                    p.drawRoundedRect(QRectF(pad, y + 4, 10, 10), 2, 2)
                    p.setPen(QPen(text_main))
                    p.drawText(pad + 14, y + fm.ascent(), text)
                else:
                    p.setPen(QPen(text_main))
                    p.drawText(pad, y + fm.ascent(), text)
                y += 18
            elif role == "value":
                font = QFont()
                font.setPointSize(9)
                font.setBold(True)
                p.setFont(font)
                fm = QFontMetrics(font)
                c = icon if isinstance(icon, QColor) else text_main
                p.setPen(QPen(c))
                p.drawText(pad, y + fm.ascent(), text)
                y += 16
            else:  # sub
                font = QFont()
                font.setPointSize(8)
                p.setFont(font)
                fm = QFontMetrics(font)
                p.setPen(QPen(text_muted))
                p.drawText(pad, y + fm.ascent(), text)
                y += 16
        p.end()


class PieChartWidget(QWidget):
    """Browser-share donut chart rendered purely with QPainter."""

    MIN_SIZE = 220
    _OFFSET_PX = 8  # how far a hovered segment pops out

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, str, int, QColor]] = []  # (browser_type, label, count, color)
        self._total: int = 0
        self.setMinimumSize(self.MIN_SIZE, self.MIN_SIZE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hovered_idx: int = -1
        self._cx: int = 0
        self._cy: int = 0
        self._outer_r: int = 0
        self._inner_r: int = 0
        self._seg_angles: list[tuple[float, float]] = []  # (start_cw_from_north_deg, span_deg)
        # Animated offset: 0.0 = no pop, 1.0 = full _OFFSET_PX pop
        self._hover_progress: float = 0.0
        self._offset_anim = QTimer(self)
        self._offset_anim.setInterval(16)  # ~60 fps
        self._offset_anim.timeout.connect(self._tick_anim)
        self._anim_target: float = 0.0
        self._tooltip = _ChartTooltip()
        self.setMouseTracking(True)

    def load(self, browser_counts: dict[str, int]):
        from src.services.browser_defs import BROWSER_DEF_MAP

        sorted_items = sorted(browser_counts.items(), key=lambda kv: kv[1], reverse=True)
        self._data = []
        self._total = sum(browser_counts.values()) or 1

        for i, (bt, cnt) in enumerate(sorted_items):
            display = BROWSER_DEF_MAP[bt].display_name if bt in BROWSER_DEF_MAP else bt
            color = _BROWSER_COLORS[i % len(_BROWSER_COLORS)]
            self._data.append((bt, display, cnt, color))

        self._hovered_idx = -1
        self._hover_progress = 0.0
        self.update()

    def _tick_anim(self):
        """Ease _hover_progress toward _anim_target at ~60 fps."""
        diff = self._anim_target - self._hover_progress
        if abs(diff) < 0.02:
            self._hover_progress = self._anim_target
            self._offset_anim.stop()
        else:
            self._hover_progress += diff * 0.22  # ease-out factor
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), _card_bg())

        w, h = self.width(), self.height()
        # Reserve right 40% for legend
        chart_w = int(w * 0.58)
        legend_x = chart_w + 8

        size = min(chart_w, h) - 16
        cx = (chart_w - size) // 2 + size // 2
        cy = h // 2
        outer_r = size // 2
        inner_r = int(outer_r * 0.52)  # donut hole

        self._cx = cx
        self._cy = cy
        self._outer_r = outer_r
        self._inner_r = inner_r
        # Cache legend geometry for hit-testing in mouseMoveEvent
        font_leg_tmp = QFont()
        font_leg_tmp.setPointSize(10)
        fm_leg_tmp = QFontMetrics(font_leg_tmp)
        row_h_tmp = max(20, fm_leg_tmp.height() + 6)
        total_legend_h_tmp = len(self._data) * row_h_tmp
        self._legend_x = chart_w + 8
        self._legend_y0 = (h - total_legend_h_tmp) // 2
        self._legend_row_h = row_h_tmp

        if not self._data:
            p.setPen(QPen(_text_muted()))
            p.drawText(self.rect(), Qt.AlignCenter, _("No data"))
            p.end()
            return

        # ── Pie segments ────────────────────────────────────────────────
        start_angle = 90 * 16  # QPainter angles are in 1/16th degrees; start at top
        rect = QRect(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)

        self._seg_angles = []
        for i, (_bt, _label, count, color) in enumerate(self._data):
            span_deg = count / self._total * 360
            span = -int(span_deg * 16)  # negative = clockwise

            # Cache angle for hit detection (clockwise from north, plain degrees)
            start_deg_cw = (90 - start_angle / 16) % 360
            self._seg_angles.append((start_deg_cw, span_deg))

            # Animated offset outward for hovered segment
            draw_rect = rect
            if i == self._hovered_idx and self._hover_progress > 0:
                mid_rad = math.radians((start_angle / 16) - (span_deg / 2))
                offset = self._OFFSET_PX * self._hover_progress
                dx = int(math.cos(mid_rad) * offset)
                dy = -int(math.sin(mid_rad) * offset)
                draw_rect = rect.translated(dx, dy)

            is_hovered = i == self._hovered_idx
            seg_grad = QRadialGradient(cx, cy, outer_r)
            seg_grad.setColorAt(0.0, color.lighter(150 if is_hovered else 140))
            seg_grad.setColorAt(1.0, color.lighter(110) if is_hovered else color)
            p.setBrush(seg_grad)
            p.setPen(Qt.NoPen)
            p.drawPie(draw_rect, start_angle, span)
            start_angle += span

        # ── Donut hole ──────────────────────────────────────────────────
        p.setBrush(_card_bg())
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

        # ── Center label — show hovered segment info or total ────────────
        font_big = QFont()
        font_big.setPointSize(14)
        font_big.setBold(True)
        font_sm = QFont()
        font_sm.setPointSize(9)
        fm = QFontMetrics(font_big)
        fm2 = QFontMetrics(font_sm)

        if self._hovered_idx >= 0 and self._hovered_idx < len(self._data):
            _bt, label, count, color = self._data[self._hovered_idx]
            pct = count / self._total * 100
            top_str = f"{count:,}"
            bot_str = f"{pct:.1f}%"
            p.setPen(QPen(color))
            p.setFont(font_big)
            tw = fm.horizontalAdvance(top_str)
            p.drawText(cx - tw // 2, cy + fm.ascent() // 2 - 6, top_str)
            p.setFont(font_sm)
            p.setPen(QPen(_text_muted()))
            tw2 = fm2.horizontalAdvance(bot_str)
            p.drawText(cx - tw2 // 2, cy + fm.ascent() // 2 + 12, bot_str)
        else:
            total_str = f"{self._total:,}"
            label_str = _("visits")
            p.setPen(QPen(_text_primary()))
            p.setFont(font_big)
            tw = fm.horizontalAdvance(total_str)
            p.drawText(cx - tw // 2, cy + fm.ascent() // 2 - 6, total_str)
            p.setFont(font_sm)
            p.setPen(QPen(_text_muted()))
            tw2 = fm2.horizontalAdvance(label_str)
            p.drawText(cx - tw2 // 2, cy + fm.ascent() // 2 + 12, label_str)

        # ── Legend ──────────────────────────────────────────────────────
        from src.utils.icon_helper import get_browser_pixmap

        font_leg = QFont()
        font_leg.setPointSize(10)
        p.setFont(font_leg)
        fm_leg = QFontMetrics(font_leg)
        icon_size = 14
        row_h = max(20, fm_leg.height() + 6)
        total_legend_h = len(self._data) * row_h
        legend_y0 = (h - total_legend_h) // 2

        for i, (bt, label, count, color) in enumerate(self._data):
            y = legend_y0 + i * row_h
            icon_y = y + (row_h - icon_size) // 2
            is_hov = i == self._hovered_idx

            # Highlight row background
            if is_hov:
                hov_bg = QColor(_accent().red(), _accent().green(), _accent().blue(), 30)
                p.setBrush(hov_bg)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(legend_x - 4, y, w - legend_x, row_h), 4, 4)

            # Browser icon (fallback: colour swatch)
            px = get_browser_pixmap(bt, icon_size)
            if not px.isNull():
                p.drawPixmap(legend_x, icon_y, px)
            else:
                p.setBrush(color)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(legend_x, icon_y, icon_size, icon_size, 3, 3)

            # Label
            pct = count / self._total * 100
            text = f"{label}  {pct:.1f}%"
            p.setPen(QPen(_accent() if is_hov else _text_primary()))
            p.drawText(legend_x + icon_size + 4, y + fm_leg.ascent() + (row_h - fm_leg.height()) // 2, text)

        p.end()

    def mouseMoveEvent(self, event):
        mx, my = event.position().x(), event.position().y()
        dx, dy = mx - self._cx, my - self._cy
        dist = math.hypot(dx, dy)

        new_idx = -1
        # Hit-test pie segments
        if self._inner_r < dist <= self._outer_r:
            angle_math = math.degrees(math.atan2(-dy, dx))
            angle_cw = (90 - angle_math) % 360
            for i, (seg_start, seg_span) in enumerate(self._seg_angles):
                seg_end = (seg_start + seg_span) % 360
                if seg_span == 0:
                    continue
                if seg_start <= seg_end:
                    if seg_start <= angle_cw < seg_end:
                        new_idx = i
                        break
                elif angle_cw >= seg_start or angle_cw < seg_end:
                    new_idx = i
                    break

        # Hit-test legend rows (if not already over the pie)
        if new_idx == -1 and mx >= self._legend_x:
            row = int((my - self._legend_y0) / self._legend_row_h) if self._legend_row_h > 0 else -1
            if 0 <= row < len(self._data):
                new_idx = row

        if new_idx != self._hovered_idx:
            self._hovered_idx = new_idx
            self._anim_target = 1.0 if new_idx >= 0 else 0.0
            if not self._offset_anim.isActive():
                self._offset_anim.start()

        # Show tooltip for hovered segment
        if new_idx >= 0 and new_idx < len(self._data):
            bt, label, count, color = self._data[new_idx]
            pct = count / self._total * 100
            from src.utils.icon_helper import get_browser_pixmap

            px = get_browser_pixmap(bt, 14)
            icon = px if not px.isNull() else color
            lines = [
                (label, "title", icon),
                (_("{count} visits").format(count=f"{count:,}"), "value", color),
                (_("{pct}% of total").format(pct=f"{pct:.1f}"), "sub", None),
            ]
            self._tooltip.show_lines(lines, event.globalPosition().toPoint())
        else:
            self._tooltip.hide_animated()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_idx != -1:
            self._hovered_idx = -1
            self._anim_target = 0.0
            if not self._offset_anim.isActive():
                self._offset_anim.start()
        self._tooltip.hide_animated()
        super().leaveEvent(event)


# ── Activity bar chart widget (hour-of-day) ──────────────────────────────────


class HourBarWidget(QWidget):
    """24-bar chart showing visits per hour of day."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hourly: dict[int, int] = {}
        self._max_val: int = 1
        self._hovered_hour: int = -1
        self._tooltip = _ChartTooltip()
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def load(self, hourly: dict[int, int]):
        self._hourly = hourly
        self._max_val = max(hourly.values(), default=1)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), _card_bg())

        w, h = self.width(), self.height()
        BOTTOM_MARGIN = 22
        LEFT_MARGIN = 8
        RIGHT_MARGIN = 8
        TOP_MARGIN = 8
        chart_h = h - BOTTOM_MARGIN - TOP_MARGIN
        chart_w = w - LEFT_MARGIN - RIGHT_MARGIN

        if not self._hourly:
            p.setPen(QPen(_text_muted()))
            p.drawText(self.rect(), Qt.AlignCenter, _("No data"))
            p.end()
            return

        num_bars = 24
        bar_w = chart_w / num_bars
        gap = max(1, bar_w * 0.15)
        real_bar_w = bar_w - gap

        accent = _accent()

        font_sm = QFont()
        font_sm.setPointSize(8)
        p.setFont(font_sm)
        fm = QFontMetrics(font_sm)

        muted = _text_muted()
        grid_color = QColor(muted.red(), muted.green(), muted.blue(), 55)
        p.setPen(QPen(grid_color, 1))
        for frac in (0.25, 0.50, 0.75):
            gy = int(TOP_MARGIN + chart_h * (1.0 - frac))
            p.drawLine(LEFT_MARGIN, gy, LEFT_MARGIN + chart_w, gy)

        for hour in range(24):
            count = self._hourly.get(hour, 0)
            bar_h = int(count / self._max_val * chart_h) if self._max_val else 0

            x = LEFT_MARGIN + hour * bar_w + gap / 2
            y = TOP_MARGIN + chart_h - bar_h
            is_hov = hour == self._hovered_hour

            # Bar background (empty track)
            track_color = QColor(accent.red(), accent.green(), accent.blue(), 110 if is_hov else 80)
            p.setBrush(track_color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, TOP_MARGIN, real_bar_w, chart_h), 2, 2)

            # Filled portion
            if bar_h > 0:
                if is_hov:
                    bar_grad = QLinearGradient(x, y, x, y + bar_h)
                    bar_grad.setColorAt(0.0, accent.lighter(140))
                    bar_grad.setColorAt(1.0, accent.lighter(115))
                else:
                    bar_grad = QLinearGradient(x, y, x, y + bar_h)
                    bar_grad.setColorAt(0.0, accent.lighter(120))
                    bar_grad.setColorAt(1.0, accent)
                p.setBrush(bar_grad)
                p.drawRoundedRect(QRectF(x, y, real_bar_w, bar_h), 2, 2)

            # Hour label (every 3 hours)
            if hour % 3 == 0:
                label = f"{hour:02d}"
                lw = fm.horizontalAdvance(label)
                lx = x + real_bar_w / 2 - lw / 2
                p.setPen(QPen(accent if is_hov else _text_muted()))
                p.drawText(int(lx), h - 4, label)

        p.end()

    def _hour_at(self, mx: float) -> int:
        LEFT_MARGIN = 8
        RIGHT_MARGIN = 8
        chart_w = self.width() - LEFT_MARGIN - RIGHT_MARGIN
        bar_w = chart_w / 24
        hour = int((mx - LEFT_MARGIN) / bar_w)
        return hour if 0 <= hour <= 23 else -1

    def mouseMoveEvent(self, event):
        hour = self._hour_at(event.position().x())
        if hour != self._hovered_hour:
            self._hovered_hour = hour
            self.update()

        if hour >= 0:
            count = self._hourly.get(hour, 0)
            pct = count / self._max_val * 100 if self._max_val else 0
            accent = _accent()
            lines = [
                (_("{start}:00 - {end}:00").format(start=f"{hour:02d}", end=f"{(hour + 1) % 24:02d}"), "title", None),
                (_("{count} visits").format(count=f"{count:,}"), "value", accent),
                (_("{pct}% of peak hour").format(pct=f"{pct:.1f}"), "sub", None),
            ]
            self._tooltip.show_lines(lines, event.globalPosition().toPoint())
        else:
            self._tooltip.hide_animated()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_hour != -1:
            self._hovered_hour = -1
            self.update()
        self._tooltip.hide_animated()
        super().leaveEvent(event)


# ── Top domains bar chart ────────────────────────────────────────────────────


class TopDomainsWidget(QWidget):
    """Horizontal bar chart for top N domains."""

    _ICON_SIZE = 14
    _ROW_H = 26
    _TOP_MARGIN = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []  # (domain, count)
        self._max_val: int = 1
        self._favicon_manager = None
        self._hovered_idx: int = -1
        self._tooltip = _ChartTooltip()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(200)
        self.setMouseTracking(True)

    def set_favicon_manager(self, fm):
        self._favicon_manager = fm

    def load(self, top_domains: list[tuple[str, int]]):
        self._data = top_domains
        self._max_val = top_domains[0][1] if top_domains else 1
        n = len(top_domains)
        self.setFixedHeight(max(200, self._TOP_MARGIN + n * self._ROW_H + self._TOP_MARGIN))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), _card_bg())

        w, _h = self.width(), self.height()
        if not self._data:
            p.setPen(QPen(_text_muted()))
            p.drawText(self.rect(), Qt.AlignCenter, _("No data"))
            p.end()
            return

        font = QFont()
        font.setPointSize(10)
        p.setFont(font)
        fm = QFontMetrics(font)

        ICON_W = self._ICON_SIZE + 4  # icon + gap
        LABEL_W = 160
        RIGHT_MARGIN = 55  # count text
        TOP_MARGIN = self._TOP_MARGIN
        bar_area_w = w - LABEL_W - RIGHT_MARGIN
        row_h = self._ROW_H

        for i, (domain, count) in enumerate(self._data):
            y = TOP_MARGIN + i * row_h
            bar_h = 14
            bar_y = y + (row_h - bar_h) // 2
            text_y = y + (row_h - fm.height()) // 2 + fm.ascent()
            icon_y = y + (row_h - self._ICON_SIZE) // 2
            is_hov = i == self._hovered_idx
            accent = _BROWSER_COLORS[i % len(_BROWSER_COLORS)]
            hov_color = _accent()

            # Hover row background
            if is_hov:
                hov_bg = QColor(hov_color.red(), hov_color.green(), hov_color.blue(), 25)
                p.setBrush(hov_bg)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(0, y, w, row_h), 4, 4)

            # Favicon
            icon_x = 0
            text_x = ICON_W
            if self._favicon_manager:
                try:
                    px = self._favicon_manager.get_pixmap(f"https://{domain}", size=self._ICON_SIZE)
                    if px and not px.isNull():
                        p.drawPixmap(icon_x, icon_y, px)
                except Exception:
                    pass

            # Domain label (clipped)
            p.setPen(QPen(hov_color if is_hov else _text_primary()))
            clipped = fm.elidedText(domain, Qt.ElideRight, LABEL_W - ICON_W - 4)
            p.drawText(text_x, text_y, clipped)

            # Background track
            accent_dim = QColor(accent.red(), accent.green(), accent.blue(), 60 if is_hov else 50)
            p.setBrush(accent_dim)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(LABEL_W, bar_y, bar_area_w, bar_h), 3, 3)

            # Filled bar
            fill_w = count / self._max_val * bar_area_w
            if fill_w > 0:
                fill_grad = QLinearGradient(LABEL_W, bar_y, LABEL_W + fill_w, bar_y)
                fill_grad.setColorAt(0.0, accent.lighter(115) if is_hov else accent)
                right_alpha = 210 if is_hov else 179
                right_color = QColor(accent.red(), accent.green(), accent.blue(), right_alpha)
                fill_grad.setColorAt(1.0, right_color)
                p.setBrush(fill_grad)
                p.drawRoundedRect(QRectF(LABEL_W, bar_y, fill_w, bar_h), 3, 3)

            # Count label
            count_str = f"{count:,}"
            cw = fm.horizontalAdvance(count_str)
            p.setPen(QPen(hov_color if is_hov else _text_muted()))
            p.drawText(w - cw, text_y, count_str)

        p.end()

    def _row_at(self, my: float) -> int:
        idx = int((my - self._TOP_MARGIN) / self._ROW_H)
        return idx if 0 <= idx < len(self._data) else -1

    def mouseMoveEvent(self, event):
        idx = self._row_at(event.position().y())
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            self.update()

        if idx >= 0:
            domain, count = self._data[idx]
            pct = count / self._max_val * 100 if self._max_val else 0
            color = _BROWSER_COLORS[idx % len(_BROWSER_COLORS)]
            icon = color
            if self._favicon_manager:
                try:
                    px = self._favicon_manager.get_pixmap(f"https://{domain}", size=14)
                    if px and not px.isNull():
                        icon = px
                except Exception:
                    pass
            lines = [
                (domain, "title", icon),
                (_("{count} visits").format(count=f"{count:,}"), "value", color),
                (_("{pct}% of top domain").format(pct=f"{pct:.1f}"), "sub", None),
            ]
            self._tooltip.show_lines(lines, event.globalPosition().toPoint())
        else:
            self._tooltip.hide_animated()

        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_idx != -1:
            self._hovered_idx = -1
            self.update()
        self._tooltip.hide_animated()
        super().leaveEvent(event)


# ── Card frame helper ────────────────────────────────────────────────────────


class _CardFrame(QFrame):
    """A card-styled container that paints its own bg/border for theme-correctness."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self.setObjectName("stats_card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        # Title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("stats_card_title")
        title_row.addWidget(self._title_lbl)
        title_row.addStretch()
        self._title_actions = title_row
        outer.addLayout(title_row)

        self._body_layout = outer
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add_title_widget(self, w: QWidget):
        self._title_actions.addWidget(w)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(_card_border())
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(_card_bg())
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.end()
        super().paintEvent(event)


# ── Segmented control ───────────────────────────────────────────────────────


class _SegmentedControl(QWidget):
    """Pill-style single-select toggle: [Overview | Year | Month]."""

    value_changed = Signal(str)  # emits "overview", "year", or "month"

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._current = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)

        for key, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setProperty("seg_key", key)
            btn.clicked.connect(lambda _checked, k=key: self._select(k))
            row.addWidget(btn)
            self._buttons.append(btn)

        ThemeManager.instance().theme_changed.connect(self._apply_style)
        self._apply_style()

    def _select(self, key: str):
        if key == self._current:
            # Re-check the button (don't allow deselect)
            for btn in self._buttons:
                if btn.property("seg_key") == key:
                    btn.setChecked(True)
            return
        self._current = key
        for btn in self._buttons:
            btn.setChecked(btn.property("seg_key") == key)
        self._apply_style()
        self.value_changed.emit(key)

    def set_value(self, key: str):
        self._current = key
        for btn in self._buttons:
            btn.setChecked(btn.property("seg_key") == key)
        self._apply_style()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark()
        bg = QColor("#2a2d35") if dark else QColor("#e5e7eb")
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.end()
        super().paintEvent(event)

    def _apply_style(self, _theme: str = ""):
        dark = _is_dark()
        accent = "#5b9cf6" if dark else "#2563eb"
        text_on = "#ffffff"
        text_off = "#c0c8d8" if dark else "#4b5563"
        bg_checked = accent
        bg_off = "transparent"
        bg_hover = "#353840" if dark else "#d1d5db"

        for btn in self._buttons:
            checked = btn.isChecked()
            bg = bg_checked if checked else bg_off
            color = text_on if checked else text_off
            hover = bg_checked if checked else bg_hover

            btn.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{color}; border:none;"
                f" border-radius:6px; padding:2px 14px; font-size:12px; font-weight:500; }}"
                f" QPushButton:hover {{ background:{hover}; }}"
            )


# ── Summary stat card ────────────────────────────────────────────────────────


class _MiniStat(QWidget):
    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._val_lbl = QLabel(value)
        self._val_lbl.setObjectName("stat_value")
        self._lbl_lbl = QLabel(label.upper())
        self._lbl_lbl.setObjectName("stat_label")

        layout.addWidget(self._val_lbl)
        layout.addWidget(self._lbl_lbl)

    def set_value(self, v: str):
        self._val_lbl.setText(v)


# ── Main StatsPage ───────────────────────────────────────────────────────────


class StatsPage(QWidget):
    """Full statistics page with heatmap, pie chart, hour bars, and top domains."""

    navigate_to_date = Signal(str)  # emits YYYY-MM-DD

    def __init__(self, db: LocalDatabase, favicon_manager=None, config=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._favicon_manager = favicon_manager
        self._config = config  # AppConfig; may be None in test contexts
        self._current_year = datetime.date.today().year
        self._current_month = datetime.date.today().month
        self._granularity = "year"  # "overview", "year", "month"
        self._available_years: list[int] = []
        self._loader_thread: QThread | None = None
        # Keeps Python references to in-flight _StatsLoader objects alive until
        # their QThread emits finished.  Without this set, reassigning
        # self._loader_obj drops the only Python reference to the old loader
        # while its thread is still running, which can let Python's GC collect
        # the wrapper before the C++ finished/deleteLater chain completes.
        self._active_loaders: set = set()
        self._page_shortcuts: list[QShortcut] = []

        self._build_ui()
        self._setup_shortcuts()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # Kick off initial data load
        self._load_data()

    # ── Keyboard shortcuts ───────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        """Register period-navigation shortcuts.

        Uses Qt.WidgetWithChildrenShortcut so the shortcuts only fire while this
        page (or a child) has focus, avoiding cross-page conflicts.  Alt+Left /
        Alt+Right are chosen as defaults because bare arrow keys are consumed by
        the inner QScrollArea for scrolling.
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

        _bind("stats_prev", "Alt+Left", self._go_prev)
        _bind("stats_next", "Alt+Right", self._go_next)

    def apply_keybindings(self) -> None:
        """Re-apply shortcuts after config change."""
        self._setup_shortcuts()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── Header row ────────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        page_title = QLabel(_("Statistics"))
        page_title.setObjectName("page_title")
        page_subtitle = QLabel(_("Visualize your browsing activity"))
        page_subtitle.setObjectName("page_subtitle")
        title_col.addWidget(page_title)
        title_col.addWidget(page_subtitle)
        header_row.addLayout(title_col)
        header_row.addStretch()

        # Date navigator (year / month) — left of segmented control
        self._date_nav = self._build_date_navigator()
        header_row.addWidget(self._date_nav)

        # Granularity selector — stays anchored right
        self._granularity_ctrl = _SegmentedControl(
            [
                ("overview", _("Overview")),
                ("year", _("Year")),
                ("month", _("Month")),
            ]
        )
        self._granularity_ctrl.set_value("year")
        self._granularity_ctrl.value_changed.connect(self._on_granularity_changed)
        header_row.addWidget(self._granularity_ctrl)

        # Export button
        self._export_btn = QPushButton(_("Export PNG"))
        self._export_btn.setIcon(get_icon("download"))
        self._export_btn.setObjectName("primary_btn")
        self._export_btn.setFixedHeight(32)
        self._export_btn.clicked.connect(self._export_image)
        header_row.addWidget(self._export_btn)

        root.addLayout(header_row)

        # ── Summary mini-stats row ────────────────────────────────────
        self._stat_total = _MiniStat(_("Total visits"), "—")
        self._stat_peak = _MiniStat(_("Peak day"), "—")
        self._stat_avg = _MiniStat(_("Daily average"), "—")
        self._stat_browsers = _MiniStat(_("Browsers"), "—")

        # ── Scrollable area for charts ────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_inner = QWidget()
        scroll.setWidget(scroll_inner)
        inner_layout = QVBoxLayout(scroll_inner)
        inner_layout.setContentsMargins(0, 0, 4, 0)
        inner_layout.setSpacing(16)
        root.addWidget(scroll, 1)
        self._inner_layout = inner_layout

        # Store reference for export (we grab this widget)
        self._charts_widget = scroll_inner

        # ── Summary mini-stats card (inside scroll) ───────────────────
        stats_card = _CardFrame(_("Year at a glance"))
        self._summary_card = stats_card
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 4, 0, 0)
        stats_row.setSpacing(32)
        for ms in (self._stat_total, self._stat_peak, self._stat_avg, self._stat_browsers):
            stats_row.addWidget(ms)
        stats_row.addStretch()
        stats_card.body_layout().addLayout(stats_row)
        inner_layout.addWidget(stats_card)

        # ── Heatmap card ──────────────────────────────────────────────
        heatmap_card = _CardFrame(_("Daily activity heatmap"))
        self._heatmap = HeatmapWidget()
        self._heatmap._db = self._db
        self._heatmap._favicon_manager = self._favicon_manager
        self._heatmap.view_day_requested.connect(self.navigate_to_date)
        hm_scroll = QScrollArea()
        hm_scroll.setWidgetResizable(False)
        hm_scroll.setWidget(self._heatmap)
        hm_scroll.setFrameShape(QFrame.NoFrame)
        hm_scroll.setFixedHeight(self._heatmap.TOP_MARGIN + 7 * self._heatmap.STEP + 20)
        hm_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        hm_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        heatmap_card.body_layout().addWidget(hm_scroll)

        # Legend strip
        legend_row = self._build_heatmap_legend()
        heatmap_card.body_layout().addLayout(legend_row)

        inner_layout.addWidget(heatmap_card)

        # ── Browser pie + Hour bars (side by side) ────────────────────
        mid_row = QHBoxLayout()
        mid_row.setSpacing(16)

        pie_card = _CardFrame(_("Browser distribution"))
        self._pie = PieChartWidget()
        self._pie.setMinimumHeight(240)
        pie_card.body_layout().addWidget(self._pie, 1)
        mid_row.addWidget(pie_card, 5)

        hour_card = _CardFrame(_("Activity by hour"))
        hour_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hour_bars = HourBarWidget()
        hour_card.body_layout().addWidget(self._hour_bars, 1)
        mid_row.addWidget(hour_card, 5)

        inner_layout.addLayout(mid_row)

        # ── Top domains ───────────────────────────────────────────────
        domains_card = _CardFrame(_("Top 10 domains"))
        self._domains_widget = TopDomainsWidget()
        self._domains_widget.set_favicon_manager(self._favicon_manager)
        domains_card.body_layout().addWidget(self._domains_widget)
        inner_layout.addWidget(domains_card)

        inner_layout.addStretch()

    def _build_date_navigator(self) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self._prev_btn = QPushButton()
        self._prev_btn.setIcon(get_icon("chevron-left"))
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.clicked.connect(self._go_prev)

        self._date_lbl = QLabel(str(self._current_year))
        self._date_lbl.setObjectName("stats_year_label")
        self._date_lbl.setAlignment(Qt.AlignCenter)
        self._date_lbl.setFixedWidth(90)
        font = self._date_lbl.font()
        font.setBold(True)
        self._date_lbl.setFont(font)

        self._next_btn = QPushButton()
        self._next_btn.setIcon(get_icon("chevron-right"))
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.clicked.connect(self._go_next)

        row.addWidget(self._prev_btn)
        row.addWidget(self._date_lbl)
        row.addWidget(self._next_btn)
        return container

    def _update_date_label(self):
        if self._granularity == "month":
            month_name = _(_MONTH_NAMES[self._current_month - 1])
            self._date_lbl.setText(f"{month_name} {self._current_year}")
        else:
            self._date_lbl.setText(str(self._current_year))

    def _build_heatmap_legend(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addStretch()

        lbl = QLabel(_("Less"))
        lbl.setObjectName("stat_label")
        row.addWidget(lbl)

        self._legend_swatches: list[QLabel] = []
        palette = _heatmap_palette()
        for color in palette:
            swatch = QLabel()
            swatch.setFixedSize(13, 13)
            swatch.setStyleSheet(f"background:{color.name()}; border-radius:3px;")
            row.addWidget(swatch)
            self._legend_swatches.append(swatch)

        lbl2 = QLabel(_("More"))
        lbl2.setObjectName("stat_label")
        row.addWidget(lbl2)
        return row

    # ── Navigation ────────────────────────────────────────────────────────

    def _go_prev(self):
        if self._granularity == "month":
            if self._current_month == 1:
                if not self._available_years or self._current_year > self._available_years[0]:
                    self._current_month = 12
                    self._current_year -= 1
                else:
                    return  # already at the earliest month, do nothing
            else:
                self._current_month -= 1
        elif self._available_years:
            idx = self._available_years.index(self._current_year) if self._current_year in self._available_years else 0
            if idx > 0:
                self._current_year = self._available_years[idx - 1]
            else:
                return
        else:
            self._current_year -= 1
        self._update_date_label()
        self._update_nav_buttons()
        self._load_data()

    def _go_next(self):
        if self._granularity == "month":
            if self._current_month == 12:
                if not self._available_years or self._current_year < self._available_years[-1]:
                    self._current_month = 1
                    self._current_year += 1
            else:
                self._current_month += 1
        elif self._available_years:
            idx = (
                self._available_years.index(self._current_year)
                if self._current_year in self._available_years
                else len(self._available_years) - 1
            )
            if idx < len(self._available_years) - 1:
                self._current_year = self._available_years[idx + 1]
            else:
                return
        else:
            self._current_year += 1
        self._update_date_label()
        self._update_nav_buttons()
        self._load_data()

    def _update_nav_buttons(self):
        if not self._available_years:
            return
        cur_y = self._current_year
        if self._granularity == "month":
            self._prev_btn.setEnabled(cur_y > self._available_years[0] or self._current_month > 1)
            self._next_btn.setEnabled(cur_y < self._available_years[-1] or self._current_month < 12)
        else:
            self._prev_btn.setEnabled(cur_y != self._available_years[0])
            self._next_btn.setEnabled(cur_y != self._available_years[-1])

    def _on_granularity_changed(self, mode: str):
        self._granularity = mode
        if mode == "overview":
            self._date_nav.hide()
            # Reset to the latest year so the heatmap always shows the most recent data
            if self._available_years:
                self._current_year = self._available_years[-1]
            else:
                self._current_year = datetime.date.today().year
        else:
            self._date_nav.show()
            if mode == "month":
                # Default to current calendar month when switching to month mode
                today = datetime.date.today()
                if self._current_year == today.year:
                    self._current_month = today.month
            self._update_date_label()
            self._update_nav_buttons()
        self._load_data()

    # ── Data loading ─────────────────────────────────────────────────────

    def _load_data(self):
        """Spawn a background thread to query the DB, then update UI."""
        # Ask any in-progress thread to stop; it will clean itself up via signals.
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.quit()
            # Do NOT block with wait() — let the old thread finish on its own.
            # The old loader/thread pair are cleaned up via the
            # finished → deleteLater chain wired up when they were created.

        mode = self._granularity
        if mode == "overview":
            year, month, heatmap_year = None, None, self._current_year
        elif mode == "month":
            year, month, heatmap_year = self._current_year, self._current_month, self._current_year
        else:
            year, month, heatmap_year = self._current_year, None, self._current_year

        loader = _StatsLoader(self._db, year, month, heatmap_year)
        thread = QThread(self)
        loader.moveToThread(thread)
        loader.finished.connect(self._on_data_loaded)
        loader.finished.connect(thread.quit)
        thread.started.connect(loader.run)
        # Clean up both the thread and the loader object via signals — no hard waits.
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(lambda t=thread: self._clear_thread_ref(t))

        # Keep a Python-level reference to the loader until its thread finishes.
        # Reassigning self._loader_obj below drops the previous Python reference,
        # and PySide6 signal connections to C++ slots (deleteLater) do not
        # guarantee that the Python wrapper stays alive.  _active_loaders holds
        # the reference explicitly so the GC cannot collect the wrapper while
        # the thread is still executing loader.run().
        self._active_loaders.add(loader)
        thread.finished.connect(lambda: self._active_loaders.discard(loader))

        self._loader_thread = thread
        self._loader_obj = loader  # keep reference to the latest loader for quick access
        thread.start()

    def _clear_thread_ref(self, thread: QThread):
        """Null out the stale reference only if it still points to *this* thread."""
        if self._loader_thread is thread:
            self._loader_thread = None

    def _on_data_loaded(
        self,
        heatmap_daily: dict,
        stats_daily: dict,
        browser: dict,
        hourly: dict,
        top_domains: list,
        years: list,
    ):
        # Update available years
        if years:
            self._available_years = years
            if self._current_year not in years:
                self._current_year = years[-1]
                self._update_date_label()
            self._update_nav_buttons()

        # Update summary card title
        if self._granularity == "overview":
            self._summary_card._title_lbl.setText(_("All time"))
        elif self._granularity == "month":
            month_name = _(_MONTH_NAMES[self._current_month - 1])
            self._summary_card._title_lbl.setText(f"{month_name} {self._current_year}")
        else:
            self._summary_card._title_lbl.setText(_("Year at a glance"))

        # Heatmap (always full year)
        self._heatmap.load(heatmap_daily, self._current_year)
        self._heatmap.set_highlight_month(self._current_month if self._granularity == "month" else None)

        # Pie chart
        self._pie.load(browser)

        # Hour bars
        self._hour_bars.load(hourly)

        # Top domains
        self._domains_widget.load(top_domains)

        # Summary stats (from filtered stats_daily)
        total = sum(stats_daily.values())
        self._stat_total.set_value(f"{total:,}")
        self._stat_browsers.set_value(str(len(browser)))

        if stats_daily:
            peak_date = max(stats_daily, key=stats_daily.__getitem__)
            peak_val = stats_daily[peak_date]
            try:
                d = datetime.date.fromisoformat(peak_date)
                peak_str = d.strftime("%b %d")
            except ValueError:
                peak_str = peak_date
            self._stat_peak.set_value(f"{peak_val:,}  ({peak_str})")
            days_with_data = len([v for v in stats_daily.values() if v > 0])
            avg = total / days_with_data if days_with_data else 0
            self._stat_avg.set_value(f"{avg:.1f}")
        else:
            self._stat_peak.set_value("—")
            self._stat_avg.set_value("—")

    # ── Export ───────────────────────────────────────────────────────────

    def _export_image(self):
        if self._granularity == "overview":
            default_name = "history_stats_all_time.png"
        elif self._granularity == "month":
            default_name = f"history_stats_{self._current_year}_{self._current_month:02d}.png"
        else:
            default_name = f"history_stats_{self._current_year}.png"
        path, __ = QFileDialog.getSaveFileName(
            self,
            _("Export statistics as image"),
            str(Path.home() / default_name),
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)",
        )
        if not path:
            return

        # Build an off-screen composite render of all cards
        # Also include the summary card — grab the whole page minus header
        px = self._render_full_stats()
        ok = px.save(path, "JPEG", 95) if path.lower().endswith((".jpg", ".jpeg")) else px.save(path, "PNG")

        if ok:
            QMessageBox.information(
                self,
                _("Export successful"),
                _("Statistics image saved to:\n{path}").format(path=path),
            )
        else:
            QMessageBox.warning(
                self,
                _("Export failed"),
                _("Could not save the image to:\n{path}").format(path=path),
            )

    def _render_full_stats(self) -> QPixmap:
        """Render a nice composite PNG with title, year, and all charts."""

        # --- Dimensions ---
        margin = 32
        year = self._current_year

        # Resolve the full palette once; avoids repeated theme lookups and makes
        # it trivial to swap themes in future (just change _palette()).
        pal = _palette()
        bg = pal.bg_page
        text_primary = pal.text_primary
        text_muted = pal.text_muted

        # HiDPI support: keep logical width at 900 but scale the physical pixel
        # buffer by the screen's device-pixel ratio.  setDevicePixelRatio() tells
        # Qt that all QPainter coordinates are still in logical pixels, so none of
        # the drawing code below needs to change — Qt maps them automatically.
        # The saved PNG will be 900×dpr physical pixels wide (e.g. 1800 px on a
        # 2× Retina screen), giving a noticeably sharper export.
        dpr = max(self.devicePixelRatio(), 2.0)
        logical_w = 900
        total_w = int(logical_w * dpr)

        # Grab each section as pixmap at export resolution
        heatmap_px = self._grab_widget_clean(self._heatmap, dpr)
        pie_px = self._grab_widget_clean(self._pie, dpr)
        hour_px = self._grab_widget_clean(self._hour_bars, dpr)
        domains_px = self._grab_widget_clean(self._domains_widget, dpr)

        # ── Scale content pixmaps to their final export widths FIRST ──────
        # QPixmap.scaled/scaledToWidth operate in physical device pixels and
        # preserve devicePixelRatio, so all target values are (logical × dpr).
        # We scale before calculating layout so card heights are derived from
        # the *actual* scaled content height — not the original widget height.
        # This prevents blank space at the bottom when the UI window is wider
        # than the fixed 900-logical-px export canvas.
        pad = 24
        half_w = (logical_w - margin * 2 - pad) // 2  # logical half-column width
        TITLE_OFFSET = 32  # logical pixels from card top to content top
        BOTTOM_PAD = 16  # logical pixels breathing room below content

        max_hm_w_phys = int((logical_w - margin * 2 - 32) * dpr)
        scaled_hm = heatmap_px.scaledToWidth(min(heatmap_px.width(), max_hm_w_phys), Qt.SmoothTransformation)

        half_content_w_phys = int((half_w - 32) * dpr)
        scaled_pie = pie_px.scaledToWidth(half_content_w_phys, Qt.SmoothTransformation)
        scaled_hour = hour_px.scaledToWidth(half_content_w_phys, Qt.SmoothTransformation)

        dom_w_phys = int((logical_w - margin * 2 - 32) * dpr)
        scaled_dom = domains_px.scaledToWidth(dom_w_phys, Qt.SmoothTransformation)

        # Heights are now based on the *scaled* content so cards fit exactly.
        # pixmap.height() returns physical pixels; divide by dpr → logical.
        header_h = 70
        summary_h = 80
        heatmap_h = scaled_hm.height() / dpr + TITLE_OFFSET + BOTTOM_PAD
        mid_h = max(scaled_pie.height() / dpr, scaled_hour.height() / dpr) + TITLE_OFFSET + BOTTOM_PAD
        domains_h = scaled_dom.height() / dpr + TITLE_OFFSET + BOTTOM_PAD
        footer_h = 40
        # Explicit sum matches the actual layout:
        #   top margin + header + summary + heatmap + pad + mid + pad + domains + footer + bottom margin
        total_h = (
            margin
            + header_h
            + summary_h
            + heatmap_h
            + pad
            + mid_h
            + pad
            + domains_h
            + pad // 2
            + footer_h
            + margin // 2
        )

        # Physical-pixel canvas; setDevicePixelRatio keeps QPainter in logical space.
        canvas = QPixmap(total_w, int(total_h * dpr))
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(bg)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        from PySide6.QtWidgets import QApplication

        base_font = QApplication.font()

        y = margin

        # ── App title + year ────────────────────────────────────────
        font_title = QFont(base_font)
        font_title.setPointSize(18)
        font_title.setBold(True)
        p.setFont(font_title)
        p.setPen(QPen(text_primary))
        if self._granularity == "overview":
            export_title = _("Browsing Statistics — All Time")
        elif self._granularity == "month":
            month_name = _(_MONTH_NAMES[self._current_month - 1])
            export_title = _("Browsing Statistics — {month} {year}").format(month=month_name, year=year)
        else:
            export_title = _("Browsing Statistics — {year}").format(year=year)
        p.drawText(margin, y + 28, export_title)

        font_sub = QFont(base_font)
        font_sub.setPointSize(10)
        p.setFont(font_sub)
        p.setPen(QPen(text_muted))
        generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        p.drawText(margin, y + 50, _("Generated {ts}").format(ts=generated))
        y += header_h

        # ── Summary numbers ──────────────────────────────────────────
        summary_items = [
            (self._stat_total._val_lbl.text(), self._stat_total._lbl_lbl.text()),
            (self._stat_peak._val_lbl.text(), self._stat_peak._lbl_lbl.text()),
            (self._stat_avg._val_lbl.text(), self._stat_avg._lbl_lbl.text()),
            (self._stat_browsers._val_lbl.text(), self._stat_browsers._lbl_lbl.text()),
        ]
        card_w = (logical_w - margin * 2 - pad * 3) // 4
        accent = pal.accent
        font_val = QFont(base_font)
        font_val.setPointSize(18)
        font_val.setBold(True)
        font_lbl = QFont(base_font)
        font_lbl.setPointSize(8)
        for i, (val, lbl) in enumerate(summary_items):
            cx = margin + i * (card_w + pad)
            self._draw_card(p, cx, y, card_w, summary_h - 8)
            p.setFont(font_val)
            p.setPen(QPen(accent))
            p.drawText(cx + 16, y + 32, val)
            p.setFont(font_lbl)
            p.setPen(QPen(text_muted))
            p.drawText(cx + 16, y + 50, lbl)
        y += summary_h

        # ── Heatmap ───────────────────────────────────────────────
        # All drawing coordinates below are in logical pixels; Qt maps them to
        # physical pixels automatically via the canvas's devicePixelRatio.
        self._draw_card(p, margin, y, logical_w - margin * 2, heatmap_h - 4)
        font_sect = QFont(base_font)
        font_sect.setPointSize(11)
        font_sect.setBold(True)
        p.setFont(font_sect)
        p.setPen(QPen(text_primary))
        p.drawText(margin + 16, y + 22, _("Daily activity heatmap"))
        p.drawPixmap(margin + 16, y + TITLE_OFFSET, scaled_hm)
        y += heatmap_h + pad

        # ── Pie + Hour ────────────────────────────────────────────
        self._draw_card(p, margin, y, half_w, mid_h - 4)
        p.setFont(font_sect)
        p.setPen(QPen(text_primary))
        p.drawText(margin + 16, y + 22, _("Browser distribution"))
        p.drawPixmap(margin + 16, y + TITLE_OFFSET, scaled_pie)

        hx = margin + half_w + pad
        self._draw_card(p, hx, y, half_w, mid_h - 4)
        p.drawText(hx + 16, y + 22, _("Activity by hour"))
        p.drawPixmap(hx + 16, y + TITLE_OFFSET, scaled_hour)
        y += mid_h + pad

        # ── Top domains ───────────────────────────────────────────
        self._draw_card(p, margin, y, logical_w - margin * 2, domains_h - 4)
        p.setFont(font_sect)
        p.setPen(QPen(text_primary))
        p.drawText(margin + 16, y + 22, _("Top 10 domains"))
        p.drawPixmap(margin + 16, y + TITLE_OFFSET, scaled_dom)

        # ── Footer ────────────────────────────────────────────────
        y += domains_h + pad
        footer_y = y + footer_h // 2

        # Divider line
        divider_color = QColor(pal.card_border)
        divider_color.setAlpha(120)
        p.setPen(QPen(divider_color, 1))
        p.drawLine(margin, y, logical_w - margin, y)

        # "HistorySync" brand text with app icon (left)
        from src.utils.icon_helper import get_app_icon

        icon_sz = 20
        app_icon_px = get_app_icon().pixmap(QSize(icon_sz, icon_sz) * int(dpr))
        app_icon_px.setDevicePixelRatio(dpr)
        font_brand = QFont(base_font)
        font_brand.setPointSize(11)
        font_brand.setBold(True)
        font_brand.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(font_brand)
        fm_brand = QFontMetrics(font_brand)
        # Vertically center icon and text together on footer_y
        text_h = fm_brand.height()
        row_top = footer_y - max(icon_sz, text_h) // 2
        if not app_icon_px.isNull():
            icon_y = row_top + (max(icon_sz, text_h) - icon_sz) // 2
            p.drawPixmap(margin, icon_y, app_icon_px)
        p.setPen(QPen(pal.accent))
        brand_x = margin + (icon_sz + 6 if not app_icon_px.isNull() else 0)
        text_y = row_top + (max(icon_sz, text_h) - text_h) // 2 + fm_brand.ascent()
        p.drawText(brand_x, text_y, "HistorySync")

        # Tagline (right-aligned)
        font_tag = QFont(base_font)
        font_tag.setPointSize(9)
        p.setFont(font_tag)
        p.setPen(QPen(text_muted))
        _TAGLINES = [
            "Your history. Your story.",
            "Pages of your past.",
            "Footprints in time.",
            "Every link, a memory.",
        ]
        tagline = random.choice(_TAGLINES)
        fm_tag = QFontMetrics(font_tag)
        p.drawText(logical_w - margin - fm_tag.horizontalAdvance(tagline), text_y, tagline)

        p.end()
        return canvas

    def _draw_card(self, p: QPainter, x: int, y: int, w: int, h: int):
        p.save()
        p.setBrush(_card_bg())
        pen = QPen(_card_border())
        pen.setWidth(1)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(x, y, w, h), 12, 12)
        p.restore()

    @staticmethod
    def _grab_widget_clean(widget: QWidget, target_dpr: float = 0) -> QPixmap:
        """Grab *widget* and return a pixmap at *target_dpr* resolution.

        ``widget.grab()`` captures at the screen's native DPR.  When
        *target_dpr* is higher (e.g. 2× on a 1× screen) we scale the grab
        up with ``SmoothTransformation`` so it fills the export canvas
        without being stretched by QPainter later.
        """
        if target_dpr <= 0:
            target_dpr = widget.devicePixelRatio()

        px = widget.grab()
        # Composite card background behind transparent areas.
        bg_px = QPixmap(px.size())
        bg_px.setDevicePixelRatio(px.devicePixelRatio())
        bg_px.fill(_card_bg())
        painter = QPainter(bg_px)
        painter.drawPixmap(0, 0, px)
        painter.end()

        screen_dpr = widget.devicePixelRatio()
        if target_dpr > screen_dpr:
            # Scale physical pixels up so the pixmap matches the export DPR.
            logical_size = widget.size()
            phys_w = int(logical_size.width() * target_dpr)
            phys_h = int(logical_size.height() * target_dpr)
            bg_px = bg_px.scaled(phys_w, phys_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            bg_px.setDevicePixelRatio(target_dpr)

        return bg_px

    # ── Theme changes ────────────────────────────────────────────────────

    def _on_theme_changed(self, _resolved: str):
        # Rebuild legend swatches with new palette colours
        palette = _heatmap_palette()
        for swatch, color in zip(self._legend_swatches, palette, strict=False):
            swatch.setStyleSheet(f"background:{color.name()}; border-radius:3px;")
        self._heatmap.update()
        self._pie.update()
        self._hour_bars.update()
        self._domains_widget.update()
        self.update()
