# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.services.db_importer import (
    CHROMIUM_BROWSER_OPTIONS,
    FIREFOX_BROWSER_OPTIONS,
    DatabaseImporter,
    DbType,
)
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.theme_manager import ThemeManager
from src.viewmodels.import_viewmodel import ImportTask, ImportViewModel, TaskResult

log = get_logger("view.import_dialog")


# ── 常量 ─────────────────────────────────────────────────────

_DB_TYPE_LABELS: dict[DbType, str] = {
    DbType.CHROMIUM: N_("Chromium History"),
    DbType.FIREFOX: N_("Firefox places.sqlite"),
    DbType.SAFARI: N_("Safari History.db"),
    DbType.HISTORYSYNC: N_("HistorySync Backup"),
    DbType.WEBASSIST: N_("Edge WebAssistDatabase"),
    DbType.UNKNOWN: N_("Unknown (Skip)"),
}

_COL_FILE = 0
_COL_FORMAT = 1
_COL_BROWSER = 2
_COL_PROFILE = 3
_COL_STATUS = 4
_COL_REMOVE = 5

_COLOR_PENDING = "#9aa3b8"
_COLOR_OK = "#4caf6e"
_COLOR_ERROR = "#e07070"
_COLOR_RUNNING = "#e0a030"


# ── 主题色板 ──────────────────────────────────────────────────


class _Palette:
    """根据 ThemeManager 当前主题返回一组 UI 颜色。"""

    def __init__(self, theme: str):
        self._dark = theme == "dark"

    @property
    def bg_base(self) -> str:
        return "#151929" if self._dark else "#f0f2f7"

    @property
    def bg_surface(self) -> str:
        return "#1a1f2e" if self._dark else "#ffffff"

    @property
    def bg_surface2(self) -> str:
        return "#1e2336" if self._dark else "#f5f7fa"

    @property
    def bg_input(self) -> str:
        return "#252a3a" if self._dark else "#ffffff"

    @property
    def bg_progress(self) -> str:
        return "#1e2230" if self._dark else "#eef1f7"

    @property
    def border(self) -> str:
        return "#2d3348" if self._dark else "#d0d5e0"

    @property
    def border_input(self) -> str:
        return "#3d4460" if self._dark else "#c0c7d8"

    @property
    def text_primary(self) -> str:
        return "#e8eaf0" if self._dark else "#1a1f2e"

    @property
    def text_secondary(self) -> str:
        return "#c8cfe0" if self._dark else "#3a4060"

    @property
    def text_muted(self) -> str:
        return "#6a7490" if self._dark else "#7a84a0"

    @property
    def text_hint(self) -> str:
        return "#3d4460" if self._dark else "#9098b0"

    @property
    def accent(self) -> str:
        return "#5b9cf6" if self._dark else "#2563eb"

    @property
    def accent_hover(self) -> str:
        return "#4a8be0" if self._dark else "#1d4ed8"

    @property
    def btn_secondary_hover(self) -> str:
        return "#2d3450" if self._dark else "#e8ecf5"

    @property
    def rm_btn_hover_bg(self) -> str:
        return "#3a1e1e" if self._dark else "#fce8e8"

    def combo_style(self) -> str:
        return (
            f"QComboBox {{ background: {self.bg_input}; color: {self.text_secondary}; "
            f"border: 1px solid {self.border_input}; "
            f"border-radius: 3px; padding: 2px 6px; font-size: 12px; min-height: 24px; }} "
            f"QComboBox::drop-down {{ border: none; width: 18px; }} "
            f"QComboBox QAbstractItemView {{ background: {self.bg_input}; color: {self.text_secondary}; "
            f"selection-background-color: {self.border_input}; border: 1px solid {self.border_input}; }}"
        )

    def line_style(self) -> str:
        return (
            f"QLineEdit {{ background: {self.bg_input}; color: {self.text_secondary}; "
            f"border: 1px solid {self.border_input}; "
            f"border-radius: 3px; padding: 2px 6px; font-size: 12px; min-height: 24px; }}"
        )

    def table_style(self) -> str:
        return (
            f"QTableWidget {{"
            f"  background: {self.bg_surface};"
            f"  alternate-background-color: {self.bg_surface2};"
            f"  color: {self.text_secondary};"
            f"  border: 1px solid {self.border};"
            f"  border-radius: 6px;"
            f"  font-size: 12px;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {self.bg_surface2};"
            f"  color: {self.text_muted};"
            f"  font-size: 11px;"
            f"  font-weight: bold;"
            f"  border: none;"
            f"  border-bottom: 1px solid {self.border};"
            f"  padding: 5px 8px;"
            f"}}"
            f"QTableWidget::item {{ padding: 0px; }}"
        )


def _get_palette() -> _Palette:
    return _Palette(ThemeManager.instance().current)


# ── 工具 ──────────────────────────────────────────────────────


def _cell_wrap(widget: QWidget) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    l = QHBoxLayout(w)
    l.setContentsMargins(4, 2, 4, 2)
    l.addWidget(widget)
    return w


def _make_combo(options, current_data=None, palette: _Palette | None = None) -> QComboBox:
    combo = QComboBox()
    combo.setStyleSheet((palette or _get_palette()).combo_style())
    for label, data in options:
        combo.addItem(label, data)
    if current_data is not None:
        idx = combo.findData(current_data)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    return combo


def _status_lbl(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; font-size: 12px; padding: 0 4px; background: transparent;")
    lbl.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
    return lbl


# ── 主对话框 ──────────────────────────────────────────────────


class ImportDialog(QDialog):
    import_finished = Signal(int)  # total inserted

    def __init__(self, import_vm: ImportViewModel, importer: DatabaseImporter, parent=None):
        super().__init__(parent)
        self._vm = import_vm
        self._importer = importer

        self.setWindowTitle(_("Import Browser History"))
        self.setMinimumSize(860, 480)
        self.resize(920, 540)
        self.setAcceptDrops(True)

        self._vm.progress_updated.connect(self._on_progress)
        self._vm.task_done.connect(self._on_task_done)
        self._vm.import_finished.connect(self._on_import_finished)
        self._vm.import_error.connect(self._on_import_error)

        # 监听主题切换，实时重绘
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        self._setup_ui()

    def _setup_ui(self):
        p = _get_palette()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部标题 ──
        self._header = QFrame()
        self._header.setFixedHeight(56)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(20, 0, 20, 0)
        self._title_lbl = QLabel(_("Import Browser History"))
        self._sub_lbl = QLabel(_("  ·  Drag & drop files, or click  Add Files"))
        hl.addWidget(self._title_lbl)
        hl.addWidget(self._sub_lbl)
        hl.addStretch()
        root.addWidget(self._header)

        # ── 内容区 ──
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(20, 14, 20, 14)
        bl.setSpacing(10)

        self._hint_lbl = QLabel(
            _(
                "Supported: Chrome/Edge/Brave History  ·  Firefox places.sqlite  "
                "·  Safari History.db  ·  HistorySync history.db"
            )
        )
        bl.addWidget(self._hint_lbl)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([_("File"), _("Format"), _("Browser"), _("Profile"), _("Status"), ""])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_COL_FILE, QHeaderView.Stretch)
        hh.setSectionResizeMode(_COL_FORMAT, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_BROWSER, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_PROFILE, QHeaderView.Stretch)
        hh.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(_COL_REMOVE, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_REMOVE, 36)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setMinimumHeight(200)
        bl.addWidget(self._table)

        self._empty_lbl = QLabel(_("No files yet.\n\nDrop files here, or click  Add Files  below."))
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setVisible(False)
        bl.addWidget(self._empty_lbl)

        self._progress_frame = QFrame()
        pfl = QVBoxLayout(self._progress_frame)
        pfl.setContentsMargins(14, 8, 14, 8)
        pfl.setSpacing(5)
        self._progress_lbl = QLabel("")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        pfl.addWidget(self._progress_lbl)
        pfl.addWidget(self._progress_bar)
        self._progress_frame.setVisible(False)
        bl.addWidget(self._progress_frame)

        root.addWidget(self._body, 1)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        root.addWidget(self._sep)

        self._foot = QWidget()
        fl = QHBoxLayout(self._foot)
        fl.setContentsMargins(20, 10, 20, 10)
        fl.setSpacing(8)

        self._add_btn = QPushButton(_("Add Files…"))
        self._add_btn.setIcon(get_icon("plus"))
        self._add_btn.clicked.connect(self._browse_files)
        fl.addWidget(self._add_btn)
        fl.addStretch()

        self._cancel_btn = QPushButton(_("Cancel"))
        self._cancel_btn.setFixedWidth(90)
        self._cancel_btn.clicked.connect(self.reject)

        self._import_btn = QPushButton(_("Start Import"))
        self._import_btn.setIcon(get_icon("upload"))
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._start_import)

        fl.addWidget(self._cancel_btn)
        fl.addWidget(self._import_btn)
        root.addWidget(self._foot)

        self._refresh_empty_state()
        self._apply_theme(p)

    # ── 主题应用 ──────────────────────────────────────────────

    def _apply_theme(self, p: _Palette):
        self._header.setStyleSheet(f"QFrame {{ background: {p.bg_surface}; border-bottom: 1px solid {p.border}; }}")
        self._title_lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {p.text_primary};")
        self._sub_lbl.setStyleSheet(f"font-size: 11px; color: {p.text_hint};")
        self._body.setStyleSheet(f"background: {p.bg_base};")
        self._hint_lbl.setStyleSheet(f"color: {p.text_hint}; font-size: 11px;")
        self._table.setStyleSheet(p.table_style())
        self._empty_lbl.setStyleSheet(f"color: {p.text_hint}; font-size: 13px;")
        self._progress_frame.setStyleSheet(
            f"QFrame {{ background: {p.bg_progress}; border: 1px solid {p.border}; border-radius: 6px; }}"
        )
        self._progress_lbl.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {p.bg_input}; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}"
        )
        self._sep.setStyleSheet(f"color: {p.border};")
        self._foot.setStyleSheet(f"background: {p.bg_surface};")
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {p.bg_input}; color: {p.text_secondary}; "
            f"border: 1px solid {p.border_input}; "
            f"border-radius: 5px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {p.btn_secondary_hover}; }}"
        )
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_muted}; "
            f"border: 1px solid {p.border_input}; "
            f"border-radius: 5px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ background: {p.bg_input}; }}"
        )
        self._import_btn.setStyleSheet(
            f"QPushButton {{ background: {p.accent}; color: white; font-weight: bold; "
            f"border-radius: 5px; padding: 6px 18px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: {p.accent_hover}; }}"
            f"QPushButton:disabled {{ background: {p.bg_input}; color: {p.text_hint}; "
            f"border: 1px solid {p.border_input}; }}"
        )
        # 刷新已有行中的子控件样式
        combo_style = p.combo_style()
        line_style = p.line_style()
        rm_style = (
            f"QPushButton {{ background: transparent; color: {p.text_hint}; border: none; "
            f"font-size: 13px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {p.rm_btn_hover_bg}; color: {_COLOR_ERROR}; }}"
        )
        for row in range(self._table.rowCount()):
            for col in (_COL_FORMAT, _COL_BROWSER):
                w = self._table.cellWidget(row, col)
                if w:
                    cb = w.findChild(QComboBox)
                    if cb:
                        cb.setStyleSheet(combo_style)
            w = self._table.cellWidget(row, _COL_PROFILE)
            if w:
                le = w.findChild(QLineEdit)
                if le:
                    le.setStyleSheet(line_style)
            w = self._table.cellWidget(row, _COL_REMOVE)
            if w:
                btn = w.findChild(QPushButton)
                if btn:
                    btn.setStyleSheet(rm_style)
            item = self._table.item(row, _COL_FILE)
            if item:
                item.setForeground(QColor(p.text_secondary))

    def _on_theme_changed(self, theme: str):
        self._apply_theme(_Palette(theme))

    # ── 拖拽 ──────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            if any(u.isLocalFile() for u in event.mimeData().urls()):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self._add_files(paths)

    # ── 文件管理 ──────────────────────────────────────────────

    def _browse_files(self):
        files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            _("Select Browser History Database Files"),
            "",
            _("Database Files (History *.sqlite *.db);;All Files (*)"),
        )
        if files:
            self._add_files([Path(f) for f in files])

    def _add_files(self, paths: list[Path]):
        for path in paths:
            if not path.is_file():
                continue
            if self._already_added(path):
                continue
            self._append_row(path)
        self._refresh_empty_state()

    def _already_added(self, path: Path) -> bool:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_FILE)
            if item and item.data(Qt.UserRole) == path:
                return True
        return False

    def _append_row(self, path: Path):
        p = _get_palette()
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 36)

        name_item = QTableWidgetItem(path.name)
        name_item.setToolTip(str(path))
        name_item.setData(Qt.UserRole, path)
        name_item.setForeground(QColor(p.text_secondary))
        self._table.setItem(row, _COL_FILE, name_item)

        db_type = self._importer.detect_db_type(path)

        type_opts = list(_DB_TYPE_LABELS.items())
        format_combo = _make_combo([(_(lbl), t) for t, lbl in type_opts], current_data=db_type, palette=p)
        self._table.setCellWidget(row, _COL_FORMAT, _cell_wrap(format_combo))

        browser_combo = self._make_browser_combo(db_type, p)
        self._table.setCellWidget(row, _COL_BROWSER, _cell_wrap(browser_combo))

        guessed_bt = self._importer.guess_browser_type_from_path(path)
        if guessed_bt:
            idx = browser_combo.findData(guessed_bt)
            if idx >= 0:
                browser_combo.setCurrentIndex(idx)

        profile_edit = QLineEdit()
        profile_edit.setPlaceholderText(_("e.g. Default"))
        profile_edit.setStyleSheet(p.line_style())
        guessed_pn = self._importer.guess_profile_name(path)
        if guessed_pn:
            profile_edit.setText(guessed_pn)
        self._table.setCellWidget(row, _COL_PROFILE, _cell_wrap(profile_edit))

        init_color = _COLOR_ERROR if db_type == DbType.UNKNOWN else _COLOR_PENDING
        init_text = _("⚠ Unknown") if db_type == DbType.UNKNOWN else _("Ready")
        sl = _status_lbl(init_text, init_color)
        self._table.setCellWidget(row, _COL_STATUS, _cell_wrap(sl))

        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(24, 24)
        rm_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_hint}; border: none; "
            f"font-size: 13px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {p.rm_btn_hover_bg}; color: {_COLOR_ERROR}; }}"
        )
        rm_btn.clicked.connect(lambda _chk, path=path: self._remove_row_by_path(path))
        self._table.setCellWidget(row, _COL_REMOVE, _cell_wrap(rm_btn))

        def _on_fmt_changed(_idx, fc=format_combo, bc=browser_combo, pe=profile_edit, s=sl):
            t = fc.currentData()
            bc.setVisible(t in (DbType.CHROMIUM, DbType.FIREFOX))
            pe.setEnabled(t != DbType.UNKNOWN)
            if t == DbType.UNKNOWN:
                s.setText(_("⚠ Skip"))
                s.setStyleSheet(f"color: {_COLOR_ERROR}; font-size: 12px; padding: 0 4px; background: transparent;")
            else:
                s.setText(_("Ready"))
                s.setStyleSheet(f"color: {_COLOR_PENDING}; font-size: 12px; padding: 0 4px; background: transparent;")
            if t == DbType.FIREFOX:
                self._repopulate_combo(bc, [(name, bt) for bt, name in FIREFOX_BROWSER_OPTIONS])
            elif t == DbType.CHROMIUM:
                self._repopulate_combo(bc, [(name, bt) for bt, name in CHROMIUM_BROWSER_OPTIONS])

        format_combo.currentIndexChanged.connect(_on_fmt_changed)
        _on_fmt_changed(0)

        self._import_btn.setEnabled(True)

    @staticmethod
    def _repopulate_combo(combo: QComboBox, options: list[tuple[str, object]]):
        combo.blockSignals(True)
        combo.clear()
        for label, data in options:
            combo.addItem(label, data)
        combo.blockSignals(False)

    def _make_browser_combo(self, db_type: DbType, palette: _Palette | None = None) -> QComboBox:
        if db_type == DbType.FIREFOX:
            opts = [(name, bt) for bt, name in FIREFOX_BROWSER_OPTIONS]
        else:
            opts = [(name, bt) for bt, name in CHROMIUM_BROWSER_OPTIONS]
        return _make_combo(opts, palette=palette)

    def _remove_row_by_path(self, path: Path):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_FILE)
            if item and item.data(Qt.UserRole) == path:
                self._table.removeRow(row)
                break
        self._import_btn.setEnabled(self._table.rowCount() > 0)
        self._refresh_empty_state()

    def _refresh_empty_state(self):
        has = self._table.rowCount() > 0
        self._table.setVisible(has)
        self._empty_lbl.setVisible(not has)

    # ── 导入 ──────────────────────────────────────────────────

    def _start_import(self):
        tasks: list[ImportTask] = []
        for row in range(self._table.rowCount()):
            path = self._table.item(row, _COL_FILE).data(Qt.UserRole)

            fmt_w = self._table.cellWidget(row, _COL_FORMAT)
            fmt_c: QComboBox = fmt_w.findChild(QComboBox)
            db_type: DbType = fmt_c.currentData()
            if db_type == DbType.UNKNOWN:
                continue

            brw_w = self._table.cellWidget(row, _COL_BROWSER)
            brw_c: QComboBox = brw_w.findChild(QComboBox)

            prf_w = self._table.cellWidget(row, _COL_PROFILE)
            prf_e: QLineEdit = prf_w.findChild(QLineEdit)

            if db_type == DbType.SAFARI:
                browser_type = "safari"
            elif db_type == DbType.HISTORYSYNC:
                browser_type = ""
            elif db_type == DbType.WEBASSIST:
                browser_type = "edge"
            else:
                browser_type = brw_c.currentData() if (brw_c and brw_c.isVisible()) else "imported"

            profile_name = (prf_e.text().strip() if prf_e else "") or "imported"
            tasks.append(ImportTask(path, db_type, browser_type, profile_name))

        if not tasks:
            QMessageBox.information(
                self,
                _("Import"),
                _("No valid files to import.\nMark at least one file with a known format."),
            )
            return

        self._add_btn.setEnabled(False)
        self._import_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._table.setEnabled(False)
        self._progress_frame.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_lbl.setText(_("Starting import…"))
        self._vm.start_import(tasks)

    # ── 信号回调 ──────────────────────────────────────────────

    def _on_progress(self, current: int, total: int, filename: str, msg: str):
        if total > 0:
            self._progress_bar.setValue(int(current / total * 100))
        self._progress_lbl.setText(f"{filename}  —  {msg}" if filename else msg)
        if filename and current < total:
            self._set_row_status(filename, _("⏳ Importing…"), _COLOR_RUNNING)

    def _on_task_done(self, result: TaskResult):
        if result.ok:
            self._set_row_status(
                result.file_path.name,
                f"✓  +{result.inserted:,}  ({result.skipped:,} dup)",
                _COLOR_OK,
            )
        else:
            self._set_row_status(
                result.file_path.name,
                f"✗  {result.error[:28]}",
                _COLOR_ERROR,
            )

    def _on_import_finished(self, extracted: int, inserted: int):
        self._progress_bar.setValue(100)
        skipped = extracted - inserted
        self._progress_lbl.setText(
            _("Done — {ins} new records added, {skip} duplicates skipped.").format(
                ins=inserted,
                skip=skipped,
            )
        )
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText(_("Close"))
        self._cancel_btn.clicked.disconnect()
        self._cancel_btn.clicked.connect(self.accept)
        self.import_finished.emit(inserted)

    def _on_import_error(self, msg: str):
        QMessageBox.critical(self, _("Import Error"), msg)
        self._add_btn.setEnabled(True)
        self._import_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._table.setEnabled(True)
        self._progress_frame.setVisible(False)

    def _set_row_status(self, filename: str, text: str, color: str):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_FILE)
            if item and item.data(Qt.UserRole).name == filename:
                w = self._table.cellWidget(row, _COL_STATUS)
                if w:
                    lbl = w.findChild(QLabel)
                    if lbl:
                        lbl.setText(text)
                        lbl.setStyleSheet(f"color: {color}; font-size: 12px; padding: 0 4px; background: transparent;")
                break

    def closeEvent(self, event):
        if self._vm.is_running:
            event.ignore()
        else:
            super().closeEvent(event)
