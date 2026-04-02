# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

from PySide6.QtCore import (
    QDate,
    QObject,
    QThread,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.services.exporter import _COLUMN_HEADERS, ALL_COLUMNS, Exporter, ResolvedExportParams
from src.services.favicon_cache import FaviconCache
from src.services.local_db import LocalDatabase
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.views.option_selector import OptionSelector

log = get_logger("export_dialog")


def _unix_to_qdate(ts: int | None) -> QDate | None:
    if ts is None:
        return None
    try:
        dt = datetime.fromtimestamp(ts, tz=UTC)
        return QDate(dt.year, dt.month, dt.day)
    except Exception:
        return None


def _qdate_to_unix_start(qdate: QDate) -> int:
    return int(datetime(qdate.year(), qdate.month(), qdate.day(), 0, 0, 0).timestamp())


def _qdate_to_unix_end(qdate: QDate) -> int:
    return int(datetime(qdate.year(), qdate.month(), qdate.day(), 23, 59, 59).timestamp())


def _infer_fmt(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".json":
        return "json"
    if ext in {".html", ".htm"}:
        return "html"
    return "csv"


# ── Worker ────────────────────────────────────────────────────────────────────


class ExportWorker(QObject):
    progress = Signal(int, int)  # current, total
    finished = Signal(int)  # exported_count
    error = Signal(str)

    def __init__(self, exporter: Exporter, params: ResolvedExportParams) -> None:
        super().__init__()
        self._exporter = exporter
        self._params = params
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            count = self._exporter.export(
                self._params,
                progress_callback=self.progress.emit,
                cancel_check=lambda: self._cancelled,
            )
            self.finished.emit(count)
        except Exception as exc:
            log.exception("Export failed")
            self.error.emit(str(exc))


# ── Dialog ────────────────────────────────────────────────────────────────────


class ExportDialog(QDialog):
    """
    Export dialog.

    Parameters
    ----------
    db : LocalDatabase
    favicon_cache : FaviconCache
    resolved_params : ResolvedExportParams | None
        If supplied (Entry A from HistoryPage), the dialog shows a filter
        summary and lets the user optionally narrow the date range.
        If None (Entry B from Settings), the user configures everything.
    """

    def __init__(
        self,
        db: LocalDatabase,
        favicon_cache: FaviconCache | None,
        resolved_params: ResolvedExportParams | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._favicon_cache = favicon_cache
        self._resolved_params = resolved_params
        self._entry_a = resolved_params is not None
        self._thread: QThread | None = None
        self._worker: ExportWorker | None = None

        self.setWindowTitle(_("Export History"))
        self.setMinimumWidth(580)
        self.setModal(True)

        self._build_ui()
        self._refresh_count()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(24, 20, 24, 20)

        # ── Filter summary (Entry A) ──────────────────────────────────────────
        if self._entry_a:
            self._summary_lbl = QLabel()
            self._summary_lbl.setObjectName("muted")
            self._summary_lbl.setWordWrap(True)
            self._summary_lbl.setText(self._build_summary_text())
            root.addWidget(self._summary_lbl)

        # ── Date range ───────────────────────────────────────────────────────
        date_group = QGroupBox(_("Date Range"))
        date_layout = QHBoxLayout(date_group)
        date_layout.setSpacing(10)

        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")

        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")

        # Populate defaults
        if self._entry_a and self._resolved_params:
            p = self._resolved_params
            from_qd = _unix_to_qdate(p.date_from) or QDate(2000, 1, 1)
            to_qd = _unix_to_qdate(p.date_to) or QDate.currentDate()
            self._orig_date_from = from_qd
            self._orig_date_to = to_qd
        else:
            from_qd = QDate(2000, 1, 1)
            to_qd = QDate.currentDate()
            self._orig_date_from = None
            self._orig_date_to = None

        self._date_from.setDate(from_qd)
        self._date_to.setDate(to_qd)

        self._date_from.dateChanged.connect(self._on_date_changed)
        self._date_to.dateChanged.connect(self._on_date_changed)

        self._date_warning = QLabel()
        self._date_warning.setObjectName("warning")
        self._date_warning.setVisible(False)

        date_layout.addWidget(QLabel(_("From:")))
        date_layout.addWidget(self._date_from)
        date_layout.addWidget(QLabel(_("To:")))
        date_layout.addWidget(self._date_to)
        date_layout.addStretch()
        root.addWidget(date_group)
        root.addWidget(self._date_warning)

        # ── Format ───────────────────────────────────────────────────────────
        fmt_group = QGroupBox(_("Export Format"))
        fmt_layout = QVBoxLayout(fmt_group)
        fmt_layout.setSpacing(8)

        combo_row = QHBoxLayout()
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItem("CSV (.csv)", "csv")
        self._fmt_combo.addItem("JSON (.json)", "json")
        self._fmt_combo.addItem("HTML (.html)", "html")
        self._fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)

        combo_row.addWidget(self._fmt_combo)
        combo_row.addStretch()
        fmt_layout.addLayout(combo_row)

        # Move below and hide by default
        self._embed_icons_chk = QCheckBox(_("Embed favicons"))
        self._embed_icons_chk.setVisible(False)
        fmt_layout.addWidget(self._embed_icons_chk)

        root.addWidget(fmt_group)

        # ── Columns ──────────────────────────────────────────────────────────
        col_group = QGroupBox(_("Columns"))
        col_outer = QVBoxLayout(col_group)
        col_outer.setSpacing(8)

        col_select_all = QHBoxLayout()
        select_all_btn = QPushButton(_("Select All"))
        select_none_btn = QPushButton(_("Select None"))
        select_all_btn.clicked.connect(self._select_all_columns)
        select_none_btn.clicked.connect(self._select_no_columns)
        col_select_all.addWidget(select_all_btn)
        col_select_all.addWidget(select_none_btn)
        col_select_all.addStretch()
        col_outer.addLayout(col_select_all)

        # Animated toggle-button selector — colours are managed by ThemeManager
        _options = [(col, _(_COLUMN_HEADERS.get(col, col))) for col in ALL_COLUMNS]
        self._col_selector = OptionSelector(_options)
        self._col_selector.select_all()
        col_outer.addWidget(self._col_selector)

        root.addWidget(col_group)

        # ── Output path ──────────────────────────────────────────────────────
        path_group = QGroupBox(_("Output File"))
        path_layout = QHBoxLayout(path_group)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(_("Choose output file path…"))
        self._path_edit.textChanged.connect(self._on_path_changed)

        browse_btn = QPushButton(_("Browse…"))
        browse_btn.setIcon(get_icon("folder"))
        browse_btn.clicked.connect(self._browse)

        path_layout.addWidget(self._path_edit)
        path_layout.addWidget(browse_btn)
        root.addWidget(path_group)

        # ── Record count ─────────────────────────────────────────────────────
        self._count_lbl = QLabel(_("Calculating…"))
        self._count_lbl.setObjectName("muted")
        root.addWidget(self._count_lbl)

        # ── Progress bar ─────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._export_btn = QPushButton(_("Export"))
        self._export_btn.setObjectName("primary_btn")
        self._export_btn.setIcon(get_icon("download"))
        self._export_btn.clicked.connect(self._start_export)

        self._cancel_btn = QPushButton(_("Cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._open_folder_btn = QPushButton(_("Open Folder"))
        self._open_folder_btn.setIcon(get_icon("folder"))
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.clicked.connect(self._open_output_folder)

        btn_row.addStretch()
        btn_row.addWidget(self._open_folder_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _build_summary_text(self) -> str:
        p = self._resolved_params
        if not p:
            return ""
        parts = []
        if p.keyword:
            parts.append(_("Keyword: {kw}").format(kw=p.keyword))
        if p.browser_type:
            parts.append(_("Browser: {b}").format(b=p.browser_type))
        if p.date_from:
            parts.append(datetime.fromtimestamp(p.date_from).strftime("%Y-%m-%d") + " →")
        if p.date_to:
            parts.append(datetime.fromtimestamp(p.date_to).strftime("%Y-%m-%d"))
        if p.bookmarked_only:
            parts.append(_("Bookmarked only"))
        if p.has_annotation:
            parts.append(_("Has annotation"))
        if p.bookmark_tag:
            parts.append(_("Tag: {tag}").format(tag=p.bookmark_tag))
        if parts:
            return _("Current filter: ") + "  ·  ".join(parts)
        return _("Exporting all records (no active filters)")

    def _on_fmt_changed(self) -> None:
        fmt = self._fmt_combo.currentData()
        is_html = fmt == "html"

        self._embed_icons_chk.setVisible(is_html)
        if not is_html:
            self._embed_icons_chk.setChecked(False)

        path = self._path_edit.text().strip()
        if path:
            p = Path(path)
            ext_map = {"csv": ".csv", "json": ".json", "html": ".html"}
            new_path = p.with_suffix(ext_map.get(fmt, ".csv"))
            self._path_edit.setText(str(new_path))

    def _on_path_changed(self) -> None:
        path = self._path_edit.text().strip()
        if path:
            inferred = _infer_fmt(path)
            idx = {"csv": 0, "json": 1, "html": 2}.get(inferred, 0)
            self._fmt_combo.blockSignals(True)
            self._fmt_combo.setCurrentIndex(idx)
            self._fmt_combo.blockSignals(False)

            is_html = inferred == "html"
            self._embed_icons_chk.setVisible(is_html)
            if not is_html:
                self._embed_icons_chk.setChecked(False)

    def _on_date_changed(self) -> None:
        if self._entry_a and self._orig_date_from and self._orig_date_to:
            from_d = self._date_from.date()
            to_d = self._date_to.date()
            warn = from_d < self._orig_date_from or to_d > self._orig_date_to
            if warn:
                self._date_warning.setText(_("⚠ The selected range extends beyond the original filter range."))
                self._date_warning.setVisible(True)
            else:
                self._date_warning.setVisible(False)
        self._refresh_count()

    def _select_all_columns(self) -> None:
        self._col_selector.select_all()

    def _select_no_columns(self) -> None:
        self._col_selector.select_none()

    def _browse(self) -> None:
        fmt = self._fmt_combo.currentData()
        filters = {
            "csv": _("CSV Files (*.csv);;All Files (*)"),
            "json": _("JSON Files (*.json);;All Files (*)"),
            "html": _("HTML Files (*.html);;All Files (*)"),
        }
        ext_map = {"csv": ".csv", "json": ".json", "html": ".html"}

        from datetime import datetime

        date_suffix = datetime.now().strftime("%Y%m%d")
        default_filename = f"history_export_{date_suffix}{ext_map.get(fmt, '.csv')}"

        path, __ = QFileDialog.getSaveFileName(
            self,
            _("Export History"),
            str(Path.home() / default_filename),
            filters.get(fmt, _("All Files (*)")),
        )
        if path:
            self._path_edit.setText(path)

    def _refresh_count(self) -> None:
        params = self._build_params(output_path=Path("dummy"))
        if params is None:
            self._count_lbl.setText("")
            return
        try:
            count = self._db.get_filtered_count(
                keyword=params.keyword,
                browser_type=params.browser_type,
                date_from=params.date_from,
                date_to=params.date_to,
                domain_ids=params.domain_ids,
                excludes=params.excludes,
                title_only=params.title_only,
                url_only=params.url_only,
                use_regex=params.use_regex,
                bookmarked_only=params.bookmarked_only,
                has_annotation=params.has_annotation,
                bookmark_tag=params.bookmark_tag,
            )
            self._count_lbl.setText(_("{count} records will be exported").format(count=f"{count:,}"))
        except Exception as exc:
            self._count_lbl.setText(_("Count error: {e}").format(e=exc))

    # ── Build params ──────────────────────────────────────────────────────────

    def _build_params(self, output_path: Path) -> ResolvedExportParams | None:
        from_ts = _qdate_to_unix_start(self._date_from.date())
        to_ts = _qdate_to_unix_end(self._date_to.date())
        fmt = self._fmt_combo.currentData() or "csv"
        columns = self._col_selector.get_selection()
        embed = self._embed_icons_chk.isChecked()

        if self._entry_a and self._resolved_params:
            p = self._resolved_params
            return ResolvedExportParams(
                output_path=output_path,
                fmt=fmt,
                columns=columns,
                embed_icons=embed,
                keyword=p.keyword,
                browser_type=p.browser_type,
                date_from=from_ts,
                date_to=to_ts,
                domain_ids=p.domain_ids,
                excludes=p.excludes,
                title_only=p.title_only,
                url_only=p.url_only,
                use_regex=p.use_regex,
                bookmarked_only=p.bookmarked_only,
                has_annotation=p.has_annotation,
                bookmark_tag=p.bookmark_tag,
            )
        return ResolvedExportParams(
            output_path=output_path,
            fmt=fmt,
            columns=columns,
            embed_icons=embed,
            date_from=from_ts,
            date_to=to_ts,
        )

    # ── Export execution ──────────────────────────────────────────────────────

    def _start_export(self) -> None:
        path_str = self._path_edit.text().strip()
        if not path_str:
            self._browse()
            path_str = self._path_edit.text().strip()
            if not path_str:
                return

        output_path = Path(path_str)
        params = self._build_params(output_path)
        if params is None:
            return

        columns = self._col_selector.get_selection()
        if not columns:
            QMessageBox.warning(self, _("No Columns"), _("Please select at least one column to export."))
            return

        self._set_controls_enabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._open_folder_btn.setVisible(False)
        self._export_btn.setEnabled(False)
        self._cancel_btn.setText(_("Cancel"))
        self._count_lbl.setText(_("Exporting…"))

        exporter = Exporter(self._db, self._favicon_cache)
        self._worker = ExportWorker(exporter, params)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    @Slot(int, int)
    def _on_progress(self, current: int, total: int) -> None:
        if total > 0:
            pct = int(current * 100 / total)
            self._progress.setValue(pct)
            self._count_lbl.setText(_("Exporting… {c} / {t}").format(c=f"{current:,}", t=f"{total:,}"))

    @Slot(int)
    def _on_finished(self, count: int) -> None:
        self._cleanup_thread()
        self._progress.setValue(100)
        self._count_lbl.setText(_("Successfully exported {n} records.").format(n=f"{count:,}"))
        self._set_controls_enabled(True)
        self._export_btn.setEnabled(True)
        self._cancel_btn.setText(_("Close"))
        self._open_folder_btn.setVisible(True)
        self._progress.setVisible(False)

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._progress.setVisible(False)
        self._set_controls_enabled(True)
        self._export_btn.setEnabled(True)
        self._cancel_btn.setText(_("Close"))
        QMessageBox.critical(self, _("Export Failed"), msg)
        self._count_lbl.setText(_("Export failed."))

    def _on_cancel(self) -> None:
        if self._worker and self._thread and self._thread.isRunning():
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setText(_("Cancelling…"))
        else:
            self.reject()

    def _cleanup_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
        self._worker = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._date_from.setEnabled(enabled)
        self._date_to.setEnabled(enabled)
        self._fmt_combo.setEnabled(enabled)
        self._embed_icons_chk.setEnabled(enabled)
        self._col_selector.setEnabled(enabled)
        self._path_edit.setEnabled(enabled)

    def _open_output_folder(self) -> None:
        path_str = self._path_edit.text().strip()
        if not path_str:
            return
        folder = Path(path_str).parent
        if folder.exists():
            import subprocess
            import sys

            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])

    def closeEvent(self, event) -> None:
        if self._thread and self._thread.isRunning():
            if self._worker:
                self._worker.cancel()
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
