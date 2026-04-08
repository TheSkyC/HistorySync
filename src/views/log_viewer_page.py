# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import LOG_FILENAME
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.styled_combobox import StyledComboBox
from src.utils.theme_manager import ThemeManager

log = get_logger("view.log_viewer")

# Color coding for log levels — dark theme
_LEVEL_COLORS_DARK = {
    "DEBUG": "#888888",
    "INFO": "#d4d4d4",
    "WARNING": "#f0c060",
    "ERROR": "#ff6060",
    "CRITICAL": "#ff2020",
}

# Color coding for log levels — light theme
_LEVEL_COLORS_LIGHT = {
    "DEBUG": "#9ca3af",
    "INFO": "#1e2128",
    "WARNING": "#b45309",
    "ERROR": "#dc2626",
    "CRITICAL": "#991b1b",
}


def _level_colors() -> dict:
    return _LEVEL_COLORS_LIGHT if ThemeManager.instance().current == "light" else _LEVEL_COLORS_DARK


_REFRESH_INTERVAL_MS = 2000


class LogViewerPage(QWidget):
    """Real-time log viewer with filtering and auto-refresh."""

    def __init__(self, log_dir: Path, parent=None):
        super().__init__(parent)
        self._log_dir = log_dir
        self._log_file = log_dir / LOG_FILENAME
        self._last_pos = 0
        self._auto_scroll = True
        self._paused = True  # Default to paused — start only when user requests

        self._init_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_log)
        # Timer starts only when user clicks Resume — default is paused

        # Sync pause button UI to match default paused state
        self._pause_btn.setChecked(True)
        self._pause_btn.setText(_("Resume"))
        self._pause_btn.setIcon(get_icon("play"))

        # Re-color logs when theme changes
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        # _load_full_log() is deferred to showEvent so it does NOT run during
        # application startup (saves ~150 ms + 25 K _level_colors calls).
        self._log_loaded = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._log_loaded:
            self._log_loaded = True
            self._load_full_log()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 16)
        layout.setSpacing(12)

        # ── Header ────────────────────────────────────────────
        hdr = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel(_("Log Viewer"))
        title_lbl.setObjectName("page_title")
        sub_lbl = QLabel(_("Real-time application log — auto-refreshes every 2 seconds"))
        sub_lbl.setObjectName("page_subtitle")
        title_col.addWidget(title_lbl)
        title_col.addWidget(sub_lbl)
        hdr.addLayout(title_col)
        hdr.addStretch()
        layout.addLayout(hdr)

        # ── Toolbar ───────────────────────────────────────────
        from PySide6.QtWidgets import QLineEdit

        toolbar_container = QVBoxLayout()
        toolbar_container.setSpacing(6)

        # Row 1: Filter controls
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        level_lbl = QLabel(_("Level:"))
        level_lbl.setObjectName("muted")
        self._level_combo = StyledComboBox()
        self._level_combo.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self._level_combo.setCurrentText("INFO")
        self._level_combo.setMinimumWidth(100)
        self._level_combo.currentTextChanged.connect(self._apply_filter)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(_("Filter text..."))
        self._filter_edit.setObjectName("search_box")
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_edit.setMaximumWidth(240)

        self._autoscroll_cb = QCheckBox(_("Auto-scroll"))
        self._autoscroll_cb.setChecked(True)
        self._autoscroll_cb.stateChanged.connect(lambda s: setattr(self, "_auto_scroll", bool(s)))

        filter_row.addWidget(level_lbl)
        filter_row.addWidget(self._level_combo)
        filter_row.addWidget(self._filter_edit)
        filter_row.addStretch()
        filter_row.addWidget(self._autoscroll_cb)
        toolbar_container.addLayout(filter_row)

        # Row 2: Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._pause_btn = QPushButton(_("Pause"))
        self._pause_btn.setIcon(get_icon("pause"))
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)

        reload_btn = QPushButton(_("Reload"))
        reload_btn.setIcon(get_icon("refresh"))
        reload_btn.clicked.connect(self._load_full_log)

        clear_btn = QPushButton(_("Clear View"))
        clear_btn.setIcon(get_icon("trash"))
        clear_btn.clicked.connect(self._clear_view)

        export_btn = QPushButton(_("Export..."))
        export_btn.setIcon(get_icon("download"))
        export_btn.clicked.connect(self._export_log)

        delete_btn = QPushButton(_("Delete Logs"))
        delete_btn.setObjectName("danger_btn")
        delete_btn.setIcon(get_icon("trash"))
        delete_btn.clicked.connect(self._delete_logs)

        action_row.addWidget(self._pause_btn)
        action_row.addWidget(reload_btn)
        action_row.addWidget(clear_btn)
        action_row.addWidget(export_btn)
        action_row.addStretch()
        action_row.addWidget(delete_btn)
        toolbar_container.addLayout(action_row)

        layout.addLayout(toolbar_container)

        # ── Log text area ──────────────────────────────────────
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        font = QFont("Consolas, Courier New, monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self._log_text.setFont(font)
        self._log_text.setMaximumBlockCount(1001)
        self._log_text.setObjectName("log_viewer")
        layout.addWidget(self._log_text, 1)

        # ── Status bar ────────────────────────────────────────
        status_row = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("muted")
        self._line_count_lbl = QLabel("")
        self._line_count_lbl.setObjectName("muted")
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()
        status_row.addWidget(self._line_count_lbl)
        layout.addLayout(status_row)

    def _on_theme_changed(self, _theme: str):
        doc = self._log_text.document()
        if doc.blockCount() == 0:
            return
        colors = _level_colors()
        level_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        cursor = self._log_text.textCursor()
        fmt = QTextCharFormat()
        doc.blockSignals(True)
        try:
            block = doc.begin()
            while block.isValid():
                text = block.text()
                line_level = "INFO"
                for lvl in level_order:
                    if lvl in text:
                        line_level = lvl
                        break
                color_hex = colors.get(line_level, colors.get("INFO", "#d4d4d4"))
                cursor.setPosition(block.position())
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                fmt.setForeground(QColor(color_hex))
                cursor.setCharFormat(fmt)
                block = block.next()
        finally:
            doc.blockSignals(False)

    def _load_full_log(self):
        """Load entire log file into the view."""
        self._log_text.clear()
        self._last_pos = 0
        if not self._log_file.exists():
            self._status_lbl.setText(_("Log file not found: {}").format(self._log_file))
            return
        try:
            with self._log_file.open(encoding="utf-8", errors="replace") as f:
                content = f.read()
                self._last_pos = f.tell()
            self._append_filtered_lines(content.splitlines())
            self._status_lbl.setText(_("Log file: {}").format(self._log_file))
        except Exception as exc:
            self._status_lbl.setText(str(exc))

    def _refresh_log(self):
        """Append only new lines since last read."""
        if self._paused or not self._log_file.exists():
            return
        try:
            size = self._log_file.stat().st_size
            if size < self._last_pos:
                # File rotated
                self._last_pos = 0
            if size == self._last_pos:
                return
            with self._log_file.open(encoding="utf-8", errors="replace") as f:
                f.seek(self._last_pos)
                new_content = f.read()
                self._last_pos = f.tell()
            if new_content.strip():
                self._append_filtered_lines(new_content.splitlines())
        except Exception:
            pass

    def _append_filtered_lines(self, lines: list[str]):
        """Append lines to display, applying level and keyword filters."""
        min_level = self._level_combo.currentText()
        keyword = self._filter_edit.text().strip().lower()
        level_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALL"]
        min_idx = level_order.index(min_level) if min_level in level_order else 0

        filtered: list[tuple[str, str]] = []  # (line_text, color_hex)

        # Resolve color map once for the whole batch — not per line.
        colors = _level_colors()

        for line in lines:
            if not line.strip():
                continue

            # Detect level
            line_level = "INFO"
            for lvl in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                if lvl in line:
                    line_level = lvl
                    break

            # Level filter
            line_idx = level_order.index(line_level) if line_level in level_order else 1
            if min_level != "ALL" and line_idx < min_idx:
                continue

            # Keyword filter
            if keyword and keyword not in line.lower():
                continue

            color = colors.get(line_level, colors.get("INFO", "#d4d4d4"))
            filtered.append((line, color))

        if not filtered:
            return

        max_blocks = self._log_text.maximumBlockCount()  # 1000

        if len(filtered) > max_blocks:
            filtered = filtered[-max_blocks:]

        doc = self._log_text.document()
        cursor = QTextCursor(doc)

        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        for line_text, color_hex in filtered:
            fmt.setForeground(QColor(color_hex))
            cursor.insertBlock()
            cursor.setCharFormat(fmt)
            cursor.insertText(line_text)

        cursor.endEditBlock()

        if self._auto_scroll:
            self._log_text.setTextCursor(cursor)
            self._log_text.ensureCursorVisible()

        count = max(0, doc.blockCount() - 1)
        self._line_count_lbl.setText(_("{n} lines displayed").format(n=count))

    def _apply_filter(self):
        """Reload and refilter the entire log."""
        self._load_full_log()

    def _toggle_pause(self, paused: bool):
        self._paused = paused
        if paused:
            self._refresh_timer.stop()
            self._pause_btn.setText(_("Resume"))
            self._pause_btn.setIcon(get_icon("play"))
        else:
            self._refresh_timer.start()
            self._pause_btn.setText(_("Pause"))
            self._pause_btn.setIcon(get_icon("pause"))

    def _clear_view(self):
        self._log_text.clear()
        self._last_pos = 0

    def _export_log(self):
        if not self._log_file.exists():
            QMessageBox.warning(self, _("Export"), _("No log file found."))
            return
        dest, __ = QFileDialog.getSaveFileName(
            self,
            _("Export Log"),
            str(Path.home() / LOG_FILENAME),
            _("Log Files (*.log *.txt);;All Files (*)"),
        )
        if dest:
            import shutil

            shutil.copy2(self._log_file, dest)
            QMessageBox.information(self, _("Export"), _("Log exported to:\n{}").format(dest))

    def _delete_logs(self):
        reply = QMessageBox.warning(
            self,
            _("Delete Log Files"),
            _("This will permanently delete all log files. Continue?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        deleted = 0
        for p in self._log_dir.glob("historysync*.log*"):
            try:
                p.unlink()
                deleted += 1
            except OSError:
                pass
        self._log_text.clear()
        self._last_pos = 0
        self._status_lbl.setText(_("Deleted {n} log file(s)").format(n=deleted))
