# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class StyledComboBox(QWidget):
    """Fully custom-drawn ComboBox with rounded corners and fade animation."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # List of (text, data) tuples
        self._current_index = -1
        self._popup = None
        self._hovered = False
        self._pressed = False

        self.setMinimumHeight(32)
        self.setMinimumWidth(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    # ── Public API (QComboBox compatible) ────────────────────────

    def addItem(self, text_or_icon, text_or_data=None, data=None):
        """Add an item to the combo box. Supports both QComboBox signatures:
        - addItem(text, data=None)
        - addItem(icon, text, data=None)
        """
        from PySide6.QtGui import QIcon

        if isinstance(text_or_icon, QIcon):
            # addItem(icon, text, data)
            icon = text_or_icon
            text = text_or_data if text_or_data is not None else ""
            item_data = data
        else:
            # addItem(text, data)
            icon = None
            text = text_or_icon
            item_data = text_or_data

        self._items.append((text, item_data, icon))
        if self._current_index == -1:
            self._current_index = 0
        self.update()

    def addItems(self, texts: list[str]):
        """Add multiple items."""
        for text in texts:
            self.addItem(text)

    def clear(self):
        """Clear all items."""
        self._items.clear()
        self._current_index = -1
        self.update()

    def count(self) -> int:
        """Return number of items."""
        return len(self._items)

    def currentIndex(self) -> int:
        """Return current index."""
        return self._current_index

    def setCurrentIndex(self, index: int):
        """Set current index."""
        if 0 <= index < len(self._items) and index != self._current_index:
            self._current_index = index
            self.currentIndexChanged.emit(index)
            self.update()

    def currentText(self) -> str:
        """Return current text."""
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][0]
        return ""

    def setCurrentText(self, text: str):
        """Set current item by text."""
        for i, item in enumerate(self._items):
            if item[0] == text:
                self.setCurrentIndex(i)
                return

    def currentData(self):
        """Return current data."""
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][1]
        return None

    def itemText(self, index: int) -> str:
        """Return text at index."""
        if 0 <= index < len(self._items):
            return self._items[index][0]
        return ""

    def itemData(self, index: int):
        """Return data at index."""
        if 0 <= index < len(self._items):
            return self._items[index][1]
        return None

    def findData(self, data) -> int:
        """Find index by data."""
        for i, item in enumerate(self._items):
            if item[1] == data:
                return i
        return -1

    def setMinimumWidth(self, width: int):
        """Set minimum width."""
        super().setMinimumWidth(width)

    def blockSignals(self, block: bool) -> bool:
        """Block signals."""
        return super().blockSignals(block)

    # ── Events ────────────────────────────────────────────────────

    def enterEvent(self, event):
        """Mouse enter."""
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        """Mouse leave."""
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        """Mouse press."""
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event):
        """Mouse release - toggle popup."""
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            self.update()

            # Toggle popup - if already open, close it
            if self._popup and self._popup.isVisible():
                self._popup.hide()
            else:
                self._show_popup()

    def paintEvent(self, event):
        """Draw the combo box."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        from src.utils.theme_manager import ThemeManager

        is_dark = ThemeManager.instance().current == "dark"

        # Colors
        if self._pressed:
            bg_color = QColor("#222530" if is_dark else "#e8ecf0")
            border_color = QColor("#3a5aaa" if is_dark else "#2563eb")
        elif self._hovered:
            bg_color = QColor("#2d3140" if is_dark else "#f5f7fa")
            border_color = QColor("#404858" if is_dark else "#b0b6c8")
        else:
            bg_color = QColor("#20232c" if is_dark else "#ffffff")
            border_color = QColor("#303540" if is_dark else "#c8ccd8")

        text_color = QColor("#c0c8d8" if is_dark else "#2a2f3d")

        # Draw background
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 7, 7)
        painter.fillPath(path, bg_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        # Draw icon and text
        if 0 <= self._current_index < len(self._items):
            text, _, icon = self._items[self._current_index]
            x_offset = 12

            # Draw icon if present
            if icon is not None and not icon.isNull():
                icon_size = 16
                icon_y = (self.height() - icon_size) // 2
                icon.paint(painter, x_offset, icon_y, icon_size, icon_size)
                x_offset += icon_size + 6

            # Draw text
            painter.setPen(text_color)
            text_rect = self.rect().adjusted(x_offset, 0, -32, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

        # Draw arrow
        arrow_color = QColor("#a0a8b8" if is_dark else "#6b7280")
        painter.setPen(QPen(arrow_color, 2))
        cx = self.width() - 16
        cy = self.height() // 2
        painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
        painter.drawLine(cx, cy + 2, cx + 4, cy - 2)

    def _show_popup(self):
        """Show the popup menu."""
        if not self._items:
            return

        if self._popup is None:
            self._popup = _ComboPopup(self)
            self._popup.item_clicked.connect(self._on_item_clicked)

        self._popup.set_items(self._items, self._current_index)

        # Position popup below the combo box
        pos = self.mapToGlobal(QPoint(0, self.height() + 2))
        self._popup.move(pos)
        self._popup.setFixedWidth(self.width())
        self._popup.show()

    def _on_item_clicked(self, index: int):
        """Handle item selection."""
        self.setCurrentIndex(index)
        if self._popup:
            self._popup.hide()


class _ComboPopup(QWidget):
    """Popup menu for combo box."""

    item_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._items = []
        self._current_index = -1
        self._hovered_index = -1
        self._item_height = 30
        self._scroll_offset = 0
        self._total_height = 0

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # Fade-in animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(150)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_items(self, items: list, current_index: int):
        """Set items to display."""
        self._items = items
        self._current_index = current_index
        self._hovered_index = current_index  # Start with current item hovered

        # Calculate height - no limit, show all items with scrolling if needed
        visible_items = min(len(items), 10)  # Show max 10 items at once
        height = visible_items * self._item_height + 8
        self.setFixedHeight(height)
        self._total_height = len(items) * self._item_height + 8
        self._scroll_offset = 0

        # Scroll to show current item
        if current_index >= 0:
            self._ensure_visible(current_index)

    def showEvent(self, event):
        """Trigger fade-in animation."""
        super().showEvent(event)
        self._fade_animation.stop()
        self._fade_animation.start()

    def mouseMoveEvent(self, event):
        """Track hovered item."""
        # Only track if mouse is within widget bounds
        if not self.rect().contains(event.pos()):
            if self._hovered_index != -1:
                self._hovered_index = -1
                self.update()
            return

        y = event.pos().y() - 4 + self._scroll_offset
        index = y // self._item_height
        if 0 <= index < len(self._items):
            if index != self._hovered_index:
                self._hovered_index = index
                self.update()
        elif self._hovered_index != -1:
            self._hovered_index = -1
            self.update()

    def mousePressEvent(self, event):
        """Handle item click - both left and right button."""
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            # Check if click is within the widget bounds
            if not self.rect().contains(event.pos()):
                # Click outside - close popup
                self.hide()
                return

            # Check if click is within an item
            y = event.pos().y() - 4 + self._scroll_offset
            if y < 0 or y >= len(self._items) * self._item_height:
                # Click in padding area - close popup
                self.hide()
                return

            index = y // self._item_height
            if 0 <= index < len(self._items):
                self.item_clicked.emit(index)

    def wheelEvent(self, event):
        """Handle mouse wheel scrolling."""
        if len(self._items) <= 10:
            return  # No scrolling needed

        delta = event.angleDelta().y()
        scroll_amount = -delta // 120 * self._item_height

        max_scroll = max(0, self._total_height - self.height())
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset + scroll_amount))
        self.update()

    def keyPressEvent(self, event):
        """Handle keyboard navigation."""
        if event.key() == Qt.Key_Up:
            if self._hovered_index > 0:
                self._hovered_index -= 1
                self._ensure_visible(self._hovered_index)
                self.update()
        elif event.key() == Qt.Key_Down:
            if self._hovered_index < len(self._items) - 1:
                self._hovered_index += 1
                self._ensure_visible(self._hovered_index)
                self.update()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if 0 <= self._hovered_index < len(self._items):
                self.item_clicked.emit(self._hovered_index)
        elif event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _ensure_visible(self, index: int):
        """Ensure the given index is visible by scrolling if needed."""
        if len(self._items) <= 10:
            return

        item_top = index * self._item_height
        item_bottom = item_top + self._item_height

        visible_top = self._scroll_offset
        visible_bottom = self._scroll_offset + self.height() - 8

        if item_top < visible_top:
            self._scroll_offset = item_top
        elif item_bottom > visible_bottom:
            self._scroll_offset = item_bottom - self.height() + 8

        max_scroll = max(0, self._total_height - self.height())
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset))

    def focusOutEvent(self, event):
        """Close popup when focus is lost."""
        super().focusOutEvent(event)
        self.hide()

    def leaveEvent(self, event):
        """Clear hover state."""
        self._hovered_index = -1
        self.update()

    def paintEvent(self, event):
        """Draw the popup."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        from src.utils.theme_manager import ThemeManager

        is_dark = ThemeManager.instance().current == "dark"

        # Background
        bg_color = QColor("#20232c" if is_dark else "#ffffff")
        border_color = QColor("#303540" if is_dark else "#c8ccd8")
        text_color = QColor("#c0c8d8" if is_dark else "#2a2f3d")
        hover_color = QColor("#252a35" if is_dark else "#f5f7fa")
        selected_color = QColor("#1e2840" if is_dark else "#eef3ff")

        # Draw background with rounded corners
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        painter.fillPath(path, bg_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        # Set clipping to rounded rect
        painter.setClipPath(path)

        # Calculate visible range
        first_visible = max(0, self._scroll_offset // self._item_height)
        last_visible = min(len(self._items), (self._scroll_offset + self.height()) // self._item_height + 1)

        # Draw items
        for i in range(first_visible, last_visible):
            item = self._items[i]
            text, _, icon = item
            y = 4 + i * self._item_height - self._scroll_offset
            item_rect = QRect(4, y, self.width() - 8, self._item_height)

            # Skip if completely outside visible area
            if y + self._item_height < 0 or y > self.height():
                continue

            # Draw item background
            if i == self._hovered_index:
                item_path = QPainterPath()
                item_path.addRoundedRect(item_rect, 5, 5)
                painter.fillPath(item_path, hover_color if i != self._current_index else selected_color)
            elif i == self._current_index:
                item_path = QPainterPath()
                item_path.addRoundedRect(item_rect, 5, 5)
                painter.fillPath(item_path, selected_color)

            # Draw icon and text
            x_offset = 8
            if icon is not None and not icon.isNull():
                icon_size = 16
                icon_y = y + (self._item_height - icon_size) // 2
                icon.paint(painter, item_rect.x() + x_offset, icon_y, icon_size, icon_size)
                x_offset += icon_size + 6

            painter.setPen(text_color)
            text_rect = item_rect.adjusted(x_offset, 0, -8, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
