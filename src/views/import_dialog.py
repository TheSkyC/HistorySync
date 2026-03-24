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
_COLOR_OK = "#7ecf8e"
_COLOR_ERROR = "#e07070"
_COLOR_RUNNING = "#f0c060"

_COMBO_STYLE = (
    "QComboBox { background: #252a3a; color: #c8cfe0; border: 1px solid #3d4460; "
    "border-radius: 3px; padding: 2px 6px; font-size: 12px; min-height: 24px; } "
    "QComboBox::drop-down { border: none; width: 18px; } "
    "QComboBox QAbstractItemView { background: #252a3a; color: #c8cfe0; "
    "selection-background-color: #3d4460; border: 1px solid #3d4460; }"
)

_LINE_STYLE = (
    "QLineEdit { background: #252a3a; color: #c8cfe0; border: 1px solid #3d4460; "
    "border-radius: 3px; padding: 2px 6px; font-size: 12px; min-height: 24px; }"
)


# ── 工具 ──────────────────────────────────────────────────────


def _cell_wrap(widget: QWidget) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    l = QHBoxLayout(w)
    l.setContentsMargins(4, 2, 4, 2)
    l.addWidget(widget)
    return w


def _make_combo(options, current_data=None) -> QComboBox:
    combo = QComboBox()
    combo.setStyleSheet(_COMBO_STYLE)
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

        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶部标题 ──
        header = QFrame()
        header.setStyleSheet("QFrame { background: #1a1f2e; border-bottom: 1px solid #2d3348; }")
        header.setFixedHeight(56)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel(_("Import Browser History"))
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #e8eaf0;")
        sub = QLabel(_("  ·  Drag & drop files, or click  Add Files"))
        sub.setStyleSheet("font-size: 11px; color: #3d4460;")
        hl.addWidget(title)
        hl.addWidget(sub)
        hl.addStretch()
        root.addWidget(header)

        # ── 内容区 ──
        body = QWidget()
        body.setStyleSheet("background: #151929;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 14, 20, 14)
        bl.setSpacing(10)

        # 格式提示
        hint = QLabel(
            _(
                "Supported: Chrome/Edge/Brave History  ·  Firefox places.sqlite  "
                "·  Safari History.db  ·  HistorySync history.db"
            )
        )
        hint.setStyleSheet("color: #3d4460; font-size: 11px;")
        bl.addWidget(hint)

        # 文件表格
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            [
                _("File"),
                _("Format"),
                _("Browser"),
                _("Profile"),
                _("Status"),
                "",
            ]
        )
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
        self._table.setStyleSheet(
            "QTableWidget {"
            "  background: #1a1f2e;"
            "  alternate-background-color: #1e2336;"
            "  color: #c8cfe0;"
            "  border: 1px solid #2d3348;"
            "  border-radius: 6px;"
            "  font-size: 12px;"
            "}"
            "QHeaderView::section {"
            "  background: #1e2336;"
            "  color: #6a7490;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "  border: none;"
            "  border-bottom: 1px solid #2d3348;"
            "  padding: 5px 8px;"
            "}"
            "QTableWidget::item { padding: 0px; }"
        )
        self._table.setMinimumHeight(200)
        bl.addWidget(self._table)

        # 空状态
        self._empty_lbl = QLabel(_("No files yet.\n\nDrop files here, or click  Add Files  below."))
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #2d3450; font-size: 13px;")
        self._empty_lbl.setVisible(False)
        bl.addWidget(self._empty_lbl)

        # 进度区
        self._progress_frame = QFrame()
        self._progress_frame.setStyleSheet(
            "QFrame { background: #1e2230; border: 1px solid #2d3348; border-radius: 6px; }"
        )
        pfl = QVBoxLayout(self._progress_frame)
        pfl.setContentsMargins(14, 8, 14, 8)
        pfl.setSpacing(5)
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color: #9aa3b8; font-size: 12px;")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            "QProgressBar { background: #252a3a; border-radius: 3px; }"
            "QProgressBar::chunk { background: #5b9cf6; border-radius: 3px; }"
        )
        pfl.addWidget(self._progress_lbl)
        pfl.addWidget(self._progress_bar)
        self._progress_frame.setVisible(False)
        bl.addWidget(self._progress_frame)

        root.addWidget(body, 1)

        # ── 底部分割线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2d3348;")
        root.addWidget(sep)

        # ── 底部操作 ──
        foot = QWidget()
        foot.setStyleSheet("background: #1a1f2e;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 10, 20, 10)
        fl.setSpacing(8)

        self._add_btn = QPushButton(_("Add Files…"))
        self._add_btn.setIcon(get_icon("plus"))
        self._add_btn.setStyleSheet(
            "QPushButton { background: #252a3a; color: #c8cfe0; border: 1px solid #3d4460; "
            "border-radius: 5px; padding: 6px 14px; font-size: 12px; }"
            "QPushButton:hover { background: #2d3450; }"
        )
        self._add_btn.clicked.connect(self._browse_files)
        fl.addWidget(self._add_btn)
        fl.addStretch()

        self._cancel_btn = QPushButton(_("Cancel"))
        self._cancel_btn.setFixedWidth(90)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9aa3b8; border: 1px solid #3d4460; "
            "border-radius: 5px; padding: 6px 12px; }"
            "QPushButton:hover { background: #252a3a; }"
        )
        self._cancel_btn.clicked.connect(self.reject)

        self._import_btn = QPushButton(_("Start Import"))
        self._import_btn.setIcon(get_icon("upload"))
        self._import_btn.setEnabled(False)
        self._import_btn.setStyleSheet(
            "QPushButton { background: #5b9cf6; color: white; font-weight: bold; "
            "border-radius: 5px; padding: 6px 18px; font-size: 13px; }"
            "QPushButton:hover { background: #4a8be0; }"
            "QPushButton:disabled { background: #252a3a; color: #555; border: 1px solid #3d4460; }"
        )
        self._import_btn.clicked.connect(self._start_import)

        fl.addWidget(self._cancel_btn)
        fl.addWidget(self._import_btn)
        root.addWidget(foot)

        self._refresh_empty_state()

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
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 36)

        # 文件名列
        name_item = QTableWidgetItem(path.name)
        name_item.setToolTip(str(path))
        name_item.setData(Qt.UserRole, path)
        name_item.setForeground(QColor("#c8cfe0"))
        self._table.setItem(row, _COL_FILE, name_item)

        # 自动识别
        db_type = self._importer.detect_db_type(path)

        # 格式 combo
        type_opts = list(_DB_TYPE_LABELS.items())  # [(DbType, label), ...]
        # 反转为 (label, DbType) 供 _make_combo，并在此处翻译标签
        format_combo = _make_combo([(_(lbl), t) for t, lbl in type_opts], current_data=db_type)
        self._table.setCellWidget(row, _COL_FORMAT, _cell_wrap(format_combo))

        # 浏览器 combo
        browser_combo = self._make_browser_combo(db_type)
        self._table.setCellWidget(row, _COL_BROWSER, _cell_wrap(browser_combo))

        # 猜测 browser_type
        guessed_bt = self._importer.guess_browser_type_from_path(path)
        if guessed_bt:
            idx = browser_combo.findData(guessed_bt)
            if idx >= 0:
                browser_combo.setCurrentIndex(idx)

        # Profile 文本框
        profile_edit = QLineEdit()
        profile_edit.setPlaceholderText(_("e.g. Default"))
        profile_edit.setStyleSheet(_LINE_STYLE)
        guessed_pn = self._importer.guess_profile_name(path)
        if guessed_pn:
            profile_edit.setText(guessed_pn)
        self._table.setCellWidget(row, _COL_PROFILE, _cell_wrap(profile_edit))

        # 状态标签
        init_color = _COLOR_ERROR if db_type == DbType.UNKNOWN else _COLOR_PENDING
        init_text = _("⚠ Unknown") if db_type == DbType.UNKNOWN else _("Ready")
        sl = _status_lbl(init_text, init_color)
        self._table.setCellWidget(row, _COL_STATUS, _cell_wrap(sl))

        # 删除按钮
        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(24, 24)
        rm_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #3d4460; border: none; "
            "font-size: 13px; border-radius: 3px; }"
            "QPushButton:hover { background: #3a1e1e; color: #e07070; }"
        )
        rm_btn.clicked.connect(lambda _chk, p=path: self._remove_row_by_path(p))
        self._table.setCellWidget(row, _COL_REMOVE, _cell_wrap(rm_btn))

        # 联动：format_combo 变化 → 更新浏览器/profile/状态
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
            # 切换浏览器选项列表
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

    def _make_browser_combo(self, db_type: DbType) -> QComboBox:
        if db_type == DbType.FIREFOX:
            opts = [(name, bt) for bt, name in FIREFOX_BROWSER_OPTIONS]
        else:
            opts = [(name, bt) for bt, name in CHROMIUM_BROWSER_OPTIONS]
        return _make_combo(opts)

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
