# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ctypes as _ctypes
import json

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QMouseEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_browser_pixmap, get_icon
from src.utils.logger import get_logger
from src.utils.path_helper import get_config_dir
from src.utils.search_highlighter import get_highlight_spans

log = get_logger("view.search_autocomplete")


_WM_MOUSEACTIVATE = 0x0021
_MA_NOACTIVATE = 3


class _WinMSG(_ctypes.Structure):
    _fields_ = [
        ("hwnd", _ctypes.c_void_p),
        ("message", _ctypes.c_uint),
        ("wParam", _ctypes.c_size_t),
        ("lParam", _ctypes.c_size_t),
        ("time", _ctypes.c_uint),
        ("pt_x", _ctypes.c_long),
        ("pt_y", _ctypes.c_long),
    ]


# ── Constants ────────────────────────────────────────────
_MAX_RECENT = 20
_FIELD_TOKENS = (
    "domain:",
    "after:",
    "before:",
    "title:",
    "url:",
    "browser:",
    "device:",
    "is:bookmarked",
    "has:note",
    "tag:",
)

# Sub-value candidates for tokens that accept a fixed/known set of values.
# Keys are the token prefix (including colon).
_FIELD_VALUES: dict[str, tuple[str, ...]] = {
    "browser:": (
        "chrome",
        "chrome_beta",
        "chrome_canary",
        "chrome_dev",
        "chrome_for_testing",
        "edge",
        "edge_beta",
        "edge_dev",
        "edge_canary",
        "brave",
        "brave_beta",
        "brave_dev",
        "brave_nightly",
        "opera",
        "opera_gx",
        "vivaldi",
        "arc",
        "chromium",
        "yandex",
        "whale",
        "coccoc",
        "thorium",
        "firefox",
        "waterfox",
        "librewolf",
        "palemoon",
        "basilisk",
        "seamonkey",
        "safari",
        "qq_browser",
        "sogou",
        "twinkstar",
        "centbrowser",
        "browser_2345",
        "liebao",
        "uc",
    ),
    "is:": ("bookmarked",),
    "has:": ("note",),
}


# ── RecentSearchStore ────────────────────────────────────


class RecentSearchStore:
    """Persists recent search queries to a JSON file in the config directory."""

    def __init__(self, max_items: int = _MAX_RECENT):
        self._max = max_items
        self._path = get_config_dir() / "recent_searches.json"
        self._items: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text("utf-8"))
                if isinstance(data, list):
                    return [s for s in data if isinstance(s, str)][: self._max]
        except Exception:
            log.warning("Failed to load recent searches", exc_info=True)
        return []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._items, ensure_ascii=False), "utf-8")
        except Exception:
            log.debug("Failed to save recent searches")

    def add(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        # Move to front if already present
        if query in self._items:
            self._items.remove(query)
        self._items.insert(0, query)
        self._items = self._items[: self._max]
        self._save()

    def items(self) -> list[str]:
        return self._items.copy()

    def remove(self, query: str) -> None:
        if query in self._items:
            self._items.remove(query)
            self._save()

    def clear(self) -> None:
        self._items.clear()
        self._save()


# ── Suggestion item roles ────────────────────────────────

_ROLE_TYPE = Qt.UserRole + 1  # "recent" | "domain" | "field" | "browser"
_ROLE_INSERT = Qt.UserRole + 2  # text to insert
_ROLE_BROWSER_TYPE = Qt.UserRole + 3  # str: browser_type for brand icon rendering
_ROLE_DELETABLE = Qt.UserRole + 4  # bool: show × delete button (recent items)
_ROLE_PINNED = Qt.UserRole + 5  # bool: browser exists in DB (pinned at top)
_ROLE_HEADER = Qt.UserRole + 6  # bool: non-selectable section header row

_DELETE_ZONE_WIDTH = 28  # px width of the delete button hit area on the right


# ── SearchSuggestionModel ────────────────────────────────


class SearchSuggestionModel(QAbstractListModel):
    """Provides suggestion items: recent searches, top domains, field tokens, browsers."""

    def __init__(self, recent_store: RecentSearchStore, parent=None):
        super().__init__(parent)
        self._recent = recent_store
        self._top_domains: list[tuple[str, int]] = []
        self._available_browsers: list[str] = []  # browser types present in DB
        self._available_devices: list[str] = []  # device names present in DB
        self._available_tags: list[str] = []  # bookmark tags present in DB
        self._rows: list[dict] = []

    # ── Public API ───────────────────────────────────────

    def set_top_domains(self, domains: list[tuple[str, int]]) -> None:
        self._top_domains = domains

    def set_available_browsers(self, browsers: list[str]) -> None:
        self._available_browsers = [b.lower() for b in browsers]

    def set_available_devices(self, devices: list[str]) -> None:
        self._available_devices = devices

    def set_available_tags(self, tags: list[str]) -> None:
        self._available_tags = tags

    def update_suggestions(self, text: str) -> None:
        """Rebuild the suggestion list based on current input text."""
        self.beginResetModel()
        self._rows.clear()

        stripped = text.strip()
        # Determine the token being typed (last whitespace-separated word)
        prefix = ""
        if text and not text.endswith(" "):
            parts = text.split()
            prefix = parts[-1].lower() if parts else ""

        # ── Group 1: Field token completions ─────────────
        _field_rows: list[dict] = []
        _seen_field: set[str] = set()

        # Partial token completions (e.g. user typed "dom" → "domain:")
        if prefix and ":" not in prefix:
            for tok in _FIELD_TOKENS:
                if tok.startswith(prefix) and tok != prefix:
                    if tok not in _seen_field:
                        _seen_field.add(tok)
                        _field_rows.append({"display": tok, "type": "field", "insert": tok, "icon": "filter"})

        # Browser sub-value completions
        if prefix.startswith("browser:"):
            sub = prefix[8:]
            for val in self._available_browsers:
                if sub and sub not in val:
                    continue
                full = "browser:" + val
                if full == prefix or full in _seen_field:
                    continue
                _seen_field.add(full)
                _field_rows.append(
                    {"display": full, "type": "browser", "insert": full, "browser_type": val, "pinned": True}
                )
            for val in _FIELD_VALUES["browser:"]:
                if sub and sub not in val:
                    continue
                full = "browser:" + val
                if full == prefix or full in _seen_field:
                    continue
                _seen_field.add(full)
                _field_rows.append(
                    {"display": full, "type": "browser", "insert": full, "browser_type": val, "pinned": False}
                )
        elif prefix.startswith("is:") or prefix.startswith("has:"):
            for token_key, values in _FIELD_VALUES.items():
                if token_key == "browser:":
                    continue
                if not prefix.startswith(token_key):
                    continue
                sub = prefix[len(token_key) :]
                for val in values:
                    if sub and sub not in val:
                        continue
                    full = token_key + val
                    if full == prefix or full in _seen_field:
                        continue
                    _seen_field.add(full)
                    _field_rows.append({"display": full, "type": "field", "insert": full, "icon": "filter"})
                break
        elif prefix.startswith("device:"):
            sub = prefix[7:]
            for val in self._available_devices:
                if sub and sub not in val.lower():
                    continue
                full = "device:" + val
                if full == prefix or full in _seen_field:
                    continue
                _seen_field.add(full)
                _field_rows.append({"display": full, "type": "field", "insert": full, "icon": "filter"})
        elif prefix.startswith("tag:"):
            sub = prefix[4:]
            for val in self._available_tags:
                if sub and sub not in val.lower():
                    continue
                full = "tag:" + val
                if full == prefix or full in _seen_field:
                    continue
                _seen_field.add(full)
                _field_rows.append({"display": full, "type": "field", "insert": full, "icon": "tag"})
        elif not prefix and stripped:
            for tok in _FIELD_TOKENS:
                _field_rows.append({"display": tok, "type": "field", "insert": tok, "icon": "filter"})

        # ── Group 2: Recent searches ─────────────────────
        _recent_rows: list[dict] = []
        _seen_recent: set[str] = set()
        recent = self._recent.items()
        words = stripped.lower().split() if stripped else []
        for q in recent:
            q_lower = q.lower()
            if words and not all(w in q_lower for w in words):
                continue
            if q not in _seen_recent:
                _seen_recent.add(q)
                _recent_rows.append({"display": q, "type": "recent", "insert": q, "icon": "clock"})
            if len(_recent_rows) >= 5:
                break

        # ── Group 3: Domain suggestions ──────────────────
        _domain_rows: list[dict] = []
        _seen_domain: set[str] = set()
        domain_prefix = ""
        if prefix.startswith("domain:"):
            domain_prefix = prefix[7:]
        elif prefix and ":" not in prefix:
            domain_prefix = prefix

        if prefix.startswith("domain:") or (domain_prefix and self._top_domains):
            for host, count in self._top_domains:
                if domain_prefix and domain_prefix not in host:
                    continue
                key = f"domain:{host}"
                if key not in _seen_domain:
                    _seen_domain.add(key)
                    _domain_rows.append(
                        {
                            "display": key,
                            "type": "domain",
                            "insert": key,
                            "count": count,
                            "icon": "globe",
                        }
                    )
                if len(_domain_rows) >= 6:
                    break

        # ── Assemble rows with section headers ───────────
        if _field_rows:
            self._rows.extend(_field_rows)
        if _recent_rows:
            self._rows.append({"display": _("Recent"), "type": "header", "insert": "", "header": True})
            self._rows.extend(_recent_rows)
        if _domain_rows:
            self._rows.append({"display": _("Domains"), "type": "header", "insert": "", "header": True})
            self._rows.extend(_domain_rows)

        self.endResetModel()

    def has_suggestions(self) -> bool:
        """Return True if there is at least one non-header suggestion row."""
        return any(not r.get("header") for r in self._rows)

    # ── QAbstractListModel interface ─────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == _ROLE_HEADER:
            return row.get("header", False)
        if role == Qt.DisplayRole:
            return row["display"]
        if role == _ROLE_TYPE:
            return row["type"]
        if role == _ROLE_INSERT:
            return row["insert"]
        if role == _ROLE_BROWSER_TYPE:
            return row.get("browser_type")
        if role == _ROLE_DELETABLE:
            return row.get("type") == "recent" and not row.get("header", False)
        if role == _ROLE_PINNED:
            return row.get("pinned", False)
        if row.get("header"):
            return None
        if role == Qt.DecorationRole:
            bt = row.get("browser_type")
            if bt:
                return None
            return get_icon(row.get("icon", "search"))
        if role == Qt.ToolTipRole:
            stype = row["type"]
            if stype == "domain":
                return _("{count} visits").format(count=row.get("count", 0))
            if stype in ("field", "browser"):
                return _("Search filter")
            return _("Recent search")
        return None


# ── SuggestionDelegate ───────────────────────────────────


class _SuggestionDelegate(QStyledItemDelegate):
    """Renders suggestion items with icon, text, type badge, and optional delete button."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        # ── Section header row ───────────────────────────
        if index.data(_ROLE_HEADER):
            painter.save()
            text = index.data(Qt.DisplayRole) or ""
            palette = opt.widget.palette() if opt.widget else None
            is_dark = palette and palette.window().color().lightness() < 128
            font = opt.font
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() - 1)
            painter.setFont(font)
            painter.setPen(QColor("#8892a8") if is_dark else QColor("#6B7280"))
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            text_rect = opt.rect.adjusted(10, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            line_start_x = text_rect.left() + text_width + 10
            line_end_x = opt.rect.right() - 10
            line_y = opt.rect.center().y()
            if line_start_x < line_end_x:
                painter.setPen(QColor("#303540") if is_dark else QColor("#d0d4de"))
                painter.drawLine(line_start_x, line_y, line_end_x, line_y)
            painter.restore()
            return

        painter.save()

        # Draw background (selection highlight)
        style = opt.widget.style() if opt.widget else QListView().style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

        rect = opt.rect
        x = rect.x() + 8
        y_center = rect.y() + rect.height() // 2

        # Use palette to adapt to light/dark theme
        palette = opt.widget.palette() if opt.widget else None
        is_dark = False
        if palette:
            is_dark = palette.window().color().lightness() < 128

        # Draw icon — browser items use brand pixmap, others use generic QIcon
        icon_size = 16
        browser_type = index.data(_ROLE_BROWSER_TYPE)
        if browser_type:
            px = get_browser_pixmap(browser_type, icon_size)
            if not px.isNull():
                painter.drawPixmap(x, y_center - icon_size // 2, px)
                x += icon_size + 6
        else:
            icon: QIcon = index.data(Qt.DecorationRole)
            if isinstance(icon, QIcon) and not icon.isNull():
                icon.paint(painter, x, y_center - icon_size // 2, icon_size, icon_size)
                x += icon_size + 6

        stype = index.data(_ROLE_TYPE) or ""
        is_deletable = index.data(_ROLE_DELETABLE) or False
        is_pinned = index.data(_ROLE_PINNED) or False

        if opt.widget and hasattr(opt.widget, "viewport"):
            true_right = opt.widget.viewport().width() - 1
        else:
            true_right = rect.right()

        # Right-side element: delete button for recent items, badge for others
        right_margin = 8
        if is_deletable:
            # Draw × delete button in the right zone
            del_x = true_right - _DELETE_ZONE_WIDTH
            del_color = QColor("#ef4444") if is_dark else QColor("#dc2626")
            painter.setPen(del_color)
            fm = painter.fontMetrics()
            painter.drawText(del_x, rect.y(), _DELETE_ZONE_WIDTH, rect.height(), Qt.AlignCenter, "×")
            right_margin = _DELETE_ZONE_WIDTH + 4
        elif stype:
            # Draw type badge
            if stype == "field":
                bg_color = QColor("#1e2d4a") if is_dark else QColor("#dbeafe")
                fg_color = QColor("#93c5fd") if is_dark else QColor("#1d4ed8")
                badge = _("Filter")
            elif stype == "domain":
                bg_color = QColor("#1e2d4a") if is_dark else QColor("#dbeafe")
                fg_color = QColor("#93c5fd") if is_dark else QColor("#1d4ed8")
                badge = _("Domain")
            elif stype == "browser" and is_pinned:
                bg_color = QColor("#1e2d4a") if is_dark else QColor("#dbeafe")
                fg_color = QColor("#93c5fd") if is_dark else QColor("#1d4ed8")
                badge = _("Available")
            elif stype == "browser":
                bg_color = QColor("#2d3448") if is_dark else QColor("#f1f5f9")
                fg_color = QColor("#8892a8") if is_dark else QColor("#475569")
                badge = _("Browser")
            else:  # recent (non-deletable fallback)
                bg_color = QColor("#2d3448") if is_dark else QColor("#f1f5f9")
                fg_color = QColor("#8892a8") if is_dark else QColor("#475569")
                badge = _("Recent")

            fm = painter.fontMetrics()
            badge_w = fm.horizontalAdvance(badge) + 12
            badge_h = fm.height() + 2
            badge_x = true_right - badge_w - 8
            badge_y = y_center - badge_h // 2

            painter.setPen(Qt.NoPen)
            painter.setBrush(bg_color)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 4, 4)
            painter.setPen(fg_color)
            painter.drawText(badge_x, badge_y, badge_w, badge_h, Qt.AlignCenter, badge)
            right_margin = badge_w + 12

        # Draw display text (clipped to avoid overlapping right-side element)
        display = index.data(Qt.DisplayRole) or ""
        text_rect = rect.adjusted(x - rect.x(), 0, -right_margin, 0)
        painter.setPen(opt.palette.text().color())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, display)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if index.data(_ROLE_HEADER):
            return QSize(0, 22)
        return QSize(0, 32)


# ── _OperatorFooter ──────────────────────────────────────

_OPERATOR_CHIPS = ("AND", "OR", "NOT")
_OPERATOR_ICONS = {"AND": "logic-and", "OR": "logic-or", "NOT": "logic-not"}


class _OperatorFooter(QWidget):
    """Fixed footer strip showing clickable operator chips."""

    chip_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("operator_footer")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self._chips: list[QPushButton] = []
        self._focused_index: int = -1

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 0, 6, 0)
        outer.setSpacing(6)
        outer.setAlignment(Qt.AlignVCenter)

        label = QLabel(_("Logic:"), self)
        label.setObjectName("footer_label")
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        outer.addWidget(label, 0, Qt.AlignVCenter)

        # Chip container inside a scroll area (scrollbar hidden; wheel scrolls)
        chip_widget = QWidget()
        chip_layout = QHBoxLayout(chip_widget)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(4)
        chip_layout.setAlignment(Qt.AlignVCenter)

        for op in _OPERATOR_CHIPS:
            btn = QPushButton(op, chip_widget)
            btn.setObjectName("operator_chip")
            btn.setFocusPolicy(Qt.TabFocus)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            icon_name = _OPERATOR_ICONS.get(op)
            if icon_name:
                btn.setIcon(get_icon(icon_name, size=14, color="#A855F7"))
            btn.clicked.connect(lambda checked=False, t=op: self.chip_clicked.emit(t))
            chip_layout.addWidget(btn, 0, Qt.AlignVCenter)
            self._chips.append(btn)
        chip_layout.addStretch()

        scroll = QScrollArea(self)
        scroll.setWidget(chip_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setMinimumHeight(28)
        scroll.wheelEvent = lambda e: scroll.horizontalScrollBar().setValue(
            scroll.horizontalScrollBar().value() - e.angleDelta().y() // 2
        )
        outer.addWidget(scroll, 1, Qt.AlignVCenter)

    def sizeHint(self):
        return QSize(-1, 32)

    def focus_next_chip(self) -> None:
        if not self._chips:
            return
        self._focused_index = (self._focused_index + 1) % len(self._chips)
        self._chips[self._focused_index].setFocus()


# ── SuggestionDropdown ───────────────────────────────────


class SuggestionDropdown(QFrame):
    """Popup container that appears below the search input.

    Uses ToolTip window flags instead of Popup to prevent Qt from
    auto-closing the dropdown when the line-edit keeps focus.

    Key design constraint: this window must NEVER steal focus or deactivate
    the main window.  Three complementary measures achieve this:
      1. Qt.WA_ShowWithoutActivating  — Qt level: don't activate on show.
      2. Qt.WA_X11DoNotAcceptFocus    — X11/Wayland: tell the WM not to give
                                        us focus even on click.
      3. viewport eventFilter         — intercept the click at the Qt event
                                        level, emit item_selected, and call
                                        ignore() so the event is NOT forwarded
                                        to the native window system, preventing
                                        the OS-level focus transfer that would
                                        deactivate the main window on Windows.
    """

    item_selected = Signal(str, str)  # insert_text, stype
    delete_requested = Signal(str)  # insert_text of the recent item to delete
    operator_selected = Signal(str)  # operator text from footer chip

    def __init__(self, parent: QWidget | None = None):
        self._anchor_widget: QWidget | None = None
        self._tracked_window: QWidget | None = None
        super().__init__(parent)
        # ToolTip stays visible while the parent keeps focus; Popup auto-closes.
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_X11DoNotAcceptFocus, True)

        # ── Inner list ───────────────────────────────────
        self._list = QListView(self)
        self._list.setObjectName("suggestion_dropdown")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setItemDelegate(_SuggestionDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.viewport().installEventFilter(self)

        # ── Footer ───────────────────────────────────────
        self._footer = _OperatorFooter(self)
        self._footer.chip_clicked.connect(self._on_chip_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list)
        layout.addWidget(self._footer)

    # ── Model delegation ─────────────────────────────────

    def setModel(self, model) -> None:
        self._list.setModel(model)

    def model(self):
        return self._list.model()

    def currentIndex(self):
        return self._list.currentIndex()

    def setCurrentIndex(self, index) -> None:
        self._list.setCurrentIndex(index)

    # ── Slots ─────────────────────────────────────────────

    def _on_chip_clicked(self, operator_text: str) -> None:
        self.operator_selected.emit(operator_text)
        self.hide()

    # ── Focus prevention ──────────────────────────────────

    def nativeEvent(self, event_type: bytes, message) -> tuple[bool, int]:
        """Return MA_NOACTIVATE for WM_MOUSEACTIVATE on Windows."""
        if event_type == b"windows_generic_MSG":
            msg = _WinMSG.from_address(int(message))
            if msg.message == _WM_MOUSEACTIVATE:
                return True, _MA_NOACTIVATE
        return super().nativeEvent(event_type, message)

    # ── Anchor / positioning ──────────────────────────────

    def set_anchor_widget(self, widget: QWidget) -> None:
        """Track the anchor widget's top-level window for move/resize/minimize events."""
        self._anchor_widget = widget
        top = widget.window()
        if top is not self._tracked_window:
            if self._tracked_window is not None:
                self._tracked_window.removeEventFilter(self)
            self._tracked_window = top
            if top is not None:
                top.installEventFilter(self)

    def show_below(self, widget: QWidget) -> None:
        """Position and resize the dropdown below the given widget."""
        model = self.model()
        if not model or not model.has_suggestions():
            self.hide()
            return
        self.set_anchor_widget(widget)

        # Accumulate height: 22px headers, 32px normal rows; cap at 8 data rows
        data_rows_seen = 0
        list_h = 4  # border padding
        for r in range(model.rowCount()):
            idx = model.index(r, 0)
            is_hdr = idx.data(_ROLE_HEADER)
            list_h += 22 if is_hdr else 32
            if not is_hdr:
                data_rows_seen += 1
            if data_rows_seen >= 8:
                break

        footer_h = self._footer.sizeHint().height()
        w = widget.width()
        pos = widget.mapToGlobal(QPoint(0, widget.height() + 2))
        self.setFixedSize(w, list_h + footer_h)
        self._list.setFixedHeight(list_h)
        self.move(pos)
        if not self.isVisible():
            self.show()

    # ── Event handling ────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Viewport mouse press — handle item selection without stealing focus
        if obj is self._list.viewport() and event.type() == QEvent.MouseButtonPress:
            index = self._list.indexAt(event.position().toPoint())
            if index.isValid():
                is_header = index.data(_ROLE_HEADER) or False
                insert_text = index.data(_ROLE_INSERT) or ""
                if not is_header and insert_text:
                    stype = index.data(_ROLE_TYPE) or ""
                    is_deletable = index.data(_ROLE_DELETABLE) or False
                    if is_deletable:
                        vp_width = self._list.viewport().width()
                        if event.position().x() >= vp_width - _DELETE_ZONE_WIDTH:
                            self.delete_requested.emit(insert_text)
                            event.ignore()
                            return True
                    self.item_selected.emit(insert_text, stype)
                    self.hide()
            event.ignore()
            return True

        # Window tracking — hide on parent window move/resize/minimize
        if obj is self._tracked_window:
            etype = event.type()
            if etype in (
                QEvent.Move,
                QEvent.Resize,
                QEvent.WindowStateChange,
                QEvent.Hide,
                QEvent.Close,
            ):
                self.hide()
            elif etype == QEvent.WindowDeactivate:
                active = QApplication.activeWindow()
                if active is not self and active is not self._tracked_window:
                    self.hide()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """Handle Up/Down navigation, Enter to select, Tab for footer chips, Escape to close."""
        key = event.key()
        if key == Qt.Key_Down:
            self._move_selection(1)
            return
        if key == Qt.Key_Up:
            self._move_selection(-1)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            idx = self._list.currentIndex()
            if idx.isValid() and not (idx.data(_ROLE_HEADER) or False):
                insert_text = idx.data(_ROLE_INSERT) or ""
                if insert_text:
                    self.item_selected.emit(insert_text, idx.data(_ROLE_TYPE) or "")
                    self.hide()
            return
        if key == Qt.Key_Tab:
            self._footer.focus_next_chip()
            return
        if key == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def _move_selection(self, delta: int) -> None:
        model = self._list.model()
        if not model or model.rowCount() == 0:
            return
        count = model.rowCount()
        idx = self._list.currentIndex().row()
        if idx < 0:
            idx = 0 if delta > 0 else count - 1
        else:
            idx += delta
        # Skip header rows with wrap-around so Up at the first item wraps to last
        for _ in range(count):
            if idx < 0:
                idx = count - 1
            elif idx >= count:
                idx = 0
            if not model.index(idx, 0).data(_ROLE_HEADER):
                self._list.setCurrentIndex(model.index(idx, 0))
                return
            idx += delta


# ── _SearchHighlighter ───────────────────────────────────


class _SearchHighlighter(QSyntaxHighlighter):
    """Attaches to QPlainTextEdit's document; colorizes field tokens etc."""

    _KIND_FMT: dict[str, QTextCharFormat] = {}

    def __init__(self, document):
        super().__init__(document)
        self._build_formats()

    def _build_formats(self) -> None:
        # (color, underline, has_background)
        defs = {
            "field": ("#3B82F6", False, True),
            "malformed": ("#F59E0B", True, True),
            "operator": ("#A855F7", False, False),
            "exclusion": ("#EF4444", False, True),
        }
        for kind, (color, underline, has_bg) in defs.items():
            fmt = QTextCharFormat()
            c = QColor(color)
            fmt.setForeground(c)
            if has_bg:
                bg = QColor(color)
                bg.setAlpha(45)
                fmt.setBackground(bg)
            if underline:
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
                fmt.setUnderlineColor(c)
            self._KIND_FMT[kind] = fmt

    def highlightBlock(self, text: str) -> None:
        for span in get_highlight_spans(text):
            fmt = self._KIND_FMT.get(span.kind)
            if fmt:
                self.setFormat(span.start, span.end - span.start, fmt)


# ── SmartSearchLineEdit ──────────────────────────────────


class SmartSearchLineEdit(QWidget):
    """Single-line search box with QSyntaxHighlighter-based token coloring.

    Wraps a QPlainTextEdit (for highlighter support) inside a styled frame,
    with toolbar buttons for regex toggle, help, and clear. Exposes the same
    public API as the old QLineEdit-based version so callers need no changes.
    """

    # Mirrors QLineEdit signals used by HistoryPage
    textChanged = Signal(str)
    regex_toggled = Signal(bool)
    search_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._use_regex = False
        self.setObjectName("search_box_container")

        # ── Inner editor ─────────────────────────────────
        self._editor = QPlainTextEdit(self)
        self._editor.setObjectName("search_box")
        self._editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setTabChangesFocus(True)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        self._editor.document().setDefaultTextOption(opt)
        self._editor.setFixedHeight(self._editor.fontMetrics().height() + 18)
        self._editor.setPlaceholderText(_("Search title or URL..."))

        # Attach highlighter
        self._highlighter = _SearchHighlighter(self._editor.document())

        # ── Toolbar buttons (right side) ─────────────────
        self._btn_regex = QToolButton(self)
        self._btn_regex.setIcon(get_icon("regex"))
        self._btn_regex.setCheckable(True)
        self._btn_regex.setToolTip(_("Regex Mode"))
        self._btn_regex.setAutoRaise(True)
        self._btn_regex.setFixedSize(24, 24)
        self._btn_regex.toggled.connect(self._toggle_regex)

        self._btn_clear = QToolButton(self)
        self._btn_clear.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton))
        self._btn_clear.setToolTip(_("Clear"))
        self._btn_clear.setAutoRaise(True)
        self._btn_clear.setFixedSize(24, 24)
        self._btn_clear.setVisible(False)
        self._btn_clear.clicked.connect(self.clear)

        self._btn_help = QToolButton(self)
        self._btn_help.setIcon(get_icon("help-circle"))
        self._btn_help.setToolTip(_("Search Syntax Help"))
        self._btn_help.setAutoRaise(True)
        self._btn_help.setFixedSize(24, 24)
        self._btn_help.clicked.connect(self._show_help)

        # ── Layout ────────────────────────────────────────
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(0)
        layout.addWidget(self._editor)
        # _btn_clear is NOT in the layout — it floats inside the editor
        layout.addWidget(self._btn_regex)
        layout.addWidget(self._btn_help)

        # ── Autocomplete ──────────────────────────────────
        self._recent_store = RecentSearchStore()
        self._suggestion_model = SearchSuggestionModel(self._recent_store, self)
        self._dropdown = SuggestionDropdown(self.window() or self)
        self._dropdown.setModel(self._suggestion_model)
        self._dropdown.item_selected.connect(self._accept_suggestion)
        self._dropdown.delete_requested.connect(self._on_delete_recent)
        self._dropdown.operator_selected.connect(self._accept_operator)

        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(150)
        self._suggest_timer.timeout.connect(self._update_suggestions)

        # Wire editor signals
        self._editor.document().contentsChanged.connect(self._on_contents_changed)
        self._editor.installEventFilter(self)
        self._focus_gained_reentrancy_guard = False  # re-entrancy guard for _on_focus_gained
        _app = QApplication.instance()
        _app.focusChanged.connect(self._on_focus_changed)
        self.destroyed.connect(lambda: _app.focusChanged.disconnect(self._on_focus_changed))
        # App-level filter: catch mouse presses anywhere to hide dropdown / blur editor
        QApplication.instance().installEventFilter(self)

    # ── Public API (mirrors QLineEdit) ───────────────────

    def text(self) -> str:
        return self._editor.toPlainText()

    def setText(self, text: str) -> None:
        if self._editor.toPlainText() == text:
            return
        self._editor.blockSignals(True)
        self._editor.setPlainText(text)
        self._editor.blockSignals(False)
        # Move cursor to end
        cur = self._editor.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self._editor.setTextCursor(cur)
        self._on_contents_changed()

    def clear(self) -> None:
        self._editor.clear()

    def setFocus(self) -> None:  # type: ignore[override]
        self._editor.setFocus()

    def hasFocus(self) -> bool:
        return self._editor.hasFocus()

    def selectAll(self) -> None:
        self._editor.selectAll()

    def setPlaceholderText(self, text: str) -> None:
        self._editor.setPlaceholderText(text)

    def setObjectName(self, name: str) -> None:
        # Container always keeps "search_box_container" for QSS targeting.
        # Forward the name only to the inner editor.
        if hasattr(self, "_editor"):
            self._editor.setObjectName(name)
        else:
            super().setObjectName(name)

    @property
    def use_regex(self) -> bool:
        return self._use_regex

    def set_top_domains(self, domains: list[tuple[str, int]]) -> None:
        self._suggestion_model.set_top_domains(domains)

    def set_available_browsers(self, browsers: list[str]) -> None:
        self._suggestion_model.set_available_browsers(browsers)

    def set_available_devices(self, devices: list[str]) -> None:
        self._suggestion_model.set_available_devices(devices)

    def set_available_tags(self, tags: list[str]) -> None:
        self._suggestion_model.set_available_tags(tags)

    def record_search(self, query: str) -> None:
        self._recent_store.add(query)

    # ── Internal slots ────────────────────────────────────

    def _on_contents_changed(self) -> None:
        t = self._editor.toPlainText()
        # Block newlines — paste or IME may insert them
        if "\n" in t:
            cleaned = t.replace("\n", " ").rstrip()
            self._editor.blockSignals(True)
            self._editor.setPlainText(cleaned)
            cur = self._editor.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            self._editor.setTextCursor(cur)
            self._editor.blockSignals(False)
            t = cleaned
        has_text = bool(t)
        self._btn_clear.setVisible(has_text)
        self._editor.setViewportMargins(0, 0, 28 if has_text else 0, 0)
        self._reposition_clear_btn()
        self.textChanged.emit(t)
        self._suggest_timer.start()

    def _update_suggestions(self) -> None:
        if self._use_regex:
            self._dropdown.hide()
            return
        # Use cursor position to determine the token being typed, not end-of-text
        full_text = self.text()
        cursor_pos = self._editor.textCursor().position()
        text_before_cursor = full_text[:cursor_pos]
        self._suggestion_model.update_suggestions(text_before_cursor)
        if self._suggestion_model.has_suggestions() and self._editor.hasFocus():
            self._dropdown.show_below(self)
        else:
            self._dropdown.hide()

    def _accept_suggestion(self, insert_text: str, stype: str = "") -> None:
        full_text = self.text()
        cursor_pos = self._editor.textCursor().position()

        if stype == "recent":
            self.setText(insert_text)
        elif stype in ("field", "domain", "browser"):
            # Replace the partial token at cursor, preserve text after cursor
            text_before = full_text[:cursor_pos]
            text_after = full_text[cursor_pos:]
            if text_before.endswith(" "):
                # Cursor is after a space — append new token without disturbing existing content
                prefix = text_before
            else:
                parts = text_before.rsplit(None, 1)
                prefix = parts[0] + " " if len(parts) > 1 else ""
            suffix = " " if not insert_text.endswith(":") else ""
            new_text = prefix + insert_text + suffix + text_after.lstrip()
            new_cursor_pos = len(prefix) + len(insert_text) + len(suffix)
            self._editor.blockSignals(True)
            self._editor.setPlainText(new_text)
            self._editor.blockSignals(False)
            cur = self._editor.textCursor()
            cur.setPosition(new_cursor_pos)
            self._editor.setTextCursor(cur)
            self._on_contents_changed()
        else:
            self.setText(insert_text)

        self._suggest_timer.stop()
        self._dropdown.hide()
        if stype in ("field", "domain", "browser"):

            def _show_next():
                cp = self._editor.textCursor().position()
                self._suggestion_model.update_suggestions(self.text()[:cp])
                if self._suggestion_model.has_suggestions():
                    self._dropdown.show_below(self)

            QTimer.singleShot(0, self._editor.setFocus)
            QTimer.singleShot(0, _show_next)
        else:
            QTimer.singleShot(0, self._editor.setFocus)

    def _accept_operator(self, operator_text: str) -> None:
        """Insert an operator chip at the current cursor position."""
        cursor = self._editor.textCursor()
        pos = cursor.position()
        text = self.text()
        left_sep = "" if pos == 0 or text[pos - 1] == " " else " "
        right_sep = "" if pos == len(text) or text[pos] == " " else " "
        insert_str = f"{left_sep}{operator_text}{right_sep}"
        new_text = text[:pos] + insert_str + text[pos:]
        self._editor.blockSignals(True)
        self._editor.setPlainText(new_text)
        self._editor.blockSignals(False)
        new_cursor = self._editor.textCursor()
        new_cursor.setPosition(pos + len(insert_str))
        self._editor.setTextCursor(new_cursor)
        self._on_contents_changed()
        self._suggest_timer.stop()
        self._dropdown.hide()
        QTimer.singleShot(0, self._editor.setFocus)

    def _on_delete_recent(self, query: str) -> None:
        """Remove a recent search entry and refresh the dropdown in-place."""
        self._recent_store.remove(query)
        self._suggestion_model.update_suggestions(self.text())
        if self._suggestion_model.has_suggestions():
            self._dropdown.show_below(self)
        else:
            self._dropdown.hide()

    def _toggle_regex(self, checked: bool) -> None:
        self._use_regex = checked
        if checked:
            self._editor.setPlaceholderText(_("Regex: e.g. github\\.com.*release"))
            self._highlighter.setDocument(None)
        else:
            self._editor.setPlaceholderText(_("Search title or URL..."))
            self._highlighter.setDocument(self._editor.document())
        # Update dynamic property so QSS [regex="true"] selector applies
        self._editor.setProperty("regex", "true" if checked else "false")
        self._editor.style().unpolish(self._editor)
        self._editor.style().polish(self._editor)
        self._dropdown.hide()
        self.regex_toggled.emit(checked)

    def _show_help(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = _(
            "<b>Advanced Search Syntax:</b><br><br>"
            "• <code>domain:example.com</code> - Filter by domain<br>"
            "• <code>after:2023-01-01</code> - Visit after date<br>"
            "• <code>before:2023-12-31</code> - Visit before date<br>"
            "• <code>-keyword</code> - Exclude term<br>"
            "• <code>title:keyword</code> - Search only titles<br>"
            "• <code>url:keyword</code> - Search only URLs<br>"
            "• <code>browser:chrome</code> - Filter by browser type<br>"
            "• <code>device:laptop</code> - Filter by device name<br><br>"
            "<b>Bookmark Filters:</b><br>"
            "• <code>is:bookmarked</code> - Only bookmarked records<br>"
            "• <code>has:note</code> - Only records with annotations<br>"
            "• <code>tag:work</code> - Filter by bookmark tag<br><br>"
            "<i>Tip: You can combine these tokens with regular text.</i>"
        )
        QMessageBox.information(self, _("Search Help"), msg)

    # ── Keyboard navigation ───────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        # App-level mouse press: hide dropdown and blur editor when clicking outside
        if event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if self._dropdown.isVisible() or self._editor.hasFocus():
                # Use object identity — coordinate math is unreliable because the
                # dropdown (ToolTip top-level) visually overlaps the editor's rect.
                in_editor = obj is self._editor or obj is self._editor.viewport()
                # Walk up the parent chain: dropdown children may receive the event
                in_dropdown = False
                if self._dropdown.isVisible():
                    w = obj
                    while w is not None:
                        if w is self._dropdown:
                            in_dropdown = True
                            break
                        w = w.parent() if callable(getattr(w, "parent", None)) else None
                if not in_editor and not in_dropdown:
                    self._dropdown.hide()
                    self._editor.clearFocus()

        if obj is self._editor:
            etype = event.type()
            # 字体变化（FontManager/QSS 修改后）时重算搜索框高度
            if etype == QEvent.Type.FontChange:
                self._editor.setFixedHeight(self._editor.fontMetrics().height() + 18)
            if etype == QEvent.KeyPress:
                key = event.key()
                if self._dropdown.isVisible():
                    if key in (Qt.Key_Down, Qt.Key_Up):
                        self._dropdown.keyPressEvent(event)
                        return True
                    if key in (Qt.Key_Return, Qt.Key_Enter):
                        idx = self._dropdown.currentIndex()
                        if idx.isValid() and not (idx.data(_ROLE_HEADER) or False):
                            insert_text = idx.data(_ROLE_INSERT)
                            if insert_text:
                                self._accept_suggestion(insert_text, idx.data(_ROLE_TYPE) or "")
                                return True
                    if key == Qt.Key_Tab:
                        self._dropdown.keyPressEvent(event)
                        return True
                    if key == Qt.Key_Escape:
                        self._dropdown.hide()
                        return True
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    text = self.text().strip()
                    if text:
                        self._recent_store.add(text)
                    self._dropdown.hide()
                    self.search_submitted.emit(text)
                    return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_clear_btn()

    def _reposition_clear_btn(self) -> None:
        e = self._editor
        btn_w, btn_h = 24, 24
        x = e.x() + e.width() - btn_w - 2
        y = e.y() + (e.height() - btn_h) // 2
        self._btn_clear.move(x, y)
        self._btn_clear.raise_()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)

    def _on_focus_gained(self, new_widget) -> None:
        """Show dropdown when editor gains focus — based on text before cursor."""
        if new_widget is not self._editor and new_widget is not self._editor.viewport():
            return
        if self._use_regex or self._focus_gained_reentrancy_guard:
            return
        self._focus_gained_reentrancy_guard = True
        try:
            cursor_pos = self._editor.textCursor().position()
            text_before = self.text()[:cursor_pos]
            self._suggestion_model.update_suggestions(text_before)
            if self._suggestion_model.has_suggestions():
                self._dropdown.show_below(self)
        finally:
            self._focus_gained_reentrancy_guard = False

    def _on_focus_changed(self, old_widget, new_widget) -> None:
        """Show dropdown when editor gains focus; hide it when focus moves outside."""
        # Show on focus gained
        if new_widget is self._editor or new_widget is self._editor.viewport():
            self._on_focus_gained(new_widget)
            return
        # Hide when focus moves outside the editor and dropdown
        if not self._dropdown.isVisible():
            return
        if new_widget is None:
            self._dropdown.hide()
            return
        # Keep if focus moved into the dropdown container or any of its children
        w = new_widget
        while w is not None:
            if w is self._dropdown:
                return
            w = w.parent()
        self._dropdown.hide()

    def _maybe_hide_dropdown(self) -> None:
        if not self._dropdown.isVisible():
            return
        if self._editor.hasFocus():
            return
        self._dropdown.hide()
