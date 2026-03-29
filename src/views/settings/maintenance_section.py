# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size: 30,123,456 → '28.7 MB'."""
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


class MaintenanceSection(QWidget):
    """Database Maintenance card.

    Signals:
        vacuum_requested()
        normalize_domains_requested()
        rebuild_fts_requested()

    Exposes:
        refresh_stats(stats: DbStats)
        set_running(running: bool)
        append_log(text: str)
        set_result(saved_bytes: int)        - called after vacuum finishes
    """

    vacuum_requested = Signal()
    normalize_domains_requested = Signal()
    rebuild_fts_requested = Signal()
    export_requested = Signal()  # Entry B: open ExportDialog with no pre-filter
    full_resync_requested = Signal()  # Trigger full browser history re-extraction
    migrate_legacy_requested = Signal()  # Open the migration wizard manually

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # ── Stats row — direct label refs, no findChildren magic ─
        stats_row = QHBoxLayout()
        stats_row.setSpacing(0)

        (self._val_file_size, w1) = self._stat_widget(_("Database size"))
        (self._val_wasted, w2) = self._stat_widget(_("Wasted space"))
        (self._val_records, w3) = self._stat_widget(_("Records"))
        (self._val_domains, w4) = self._stat_widget(_("Unique domains"))
        # keep a ref to the wasted value label for colour changes
        self._wasted_val_lbl = self._val_wasted

        for w in (w1, w2, w3, w4):
            stats_row.addWidget(w)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # ── Action buttons ────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._vacuum_btn = QPushButton(_("Vacuum && Optimize"))
        self._vacuum_btn.setObjectName("primary_btn")
        self._vacuum_btn.setIcon(get_icon("zap"))
        self._vacuum_btn.setToolTip(
            _(
                "Reclaim wasted space, defragment pages, and update query planner statistics.\n"
                "Requires ~2× the current DB size as free disk space."
            )
        )
        self._vacuum_btn.clicked.connect(self.vacuum_requested)

        self._normalize_btn = QPushButton(_("Normalize Domains"))
        self._normalize_btn.setIcon(get_icon("link"))
        self._normalize_btn.setToolTip(
            _(
                "Extract and index domain names from all URLs.\n"
                "Speeds up domain-based queries and enables domain analytics."
            )
        )
        self._normalize_btn.clicked.connect(self.normalize_domains_requested)

        self._fts_btn = QPushButton(_("Rebuild FTS Index"))
        self._fts_btn.setIcon(get_icon("search"))
        self._fts_btn.setToolTip(
            _(
                "Rebuild the full-text search index from scratch.\n"
                "Run this if search results seem incomplete or incorrect."
            )
        )
        self._fts_btn.clicked.connect(self.rebuild_fts_requested)

        self._export_btn = QPushButton(_("Export History…"))
        self._export_btn.setIcon(get_icon("download"))
        self._export_btn.setToolTip(
            _(
                "Export the entire history database to CSV, JSON, or HTML.\n"
                "You can filter by date range and choose which columns to include."
            )
        )
        self._export_btn.clicked.connect(self.export_requested)

        self._resync_btn = QPushButton(_("Full Resync"))
        self._resync_btn.setIcon(get_icon("refresh-cw"))
        self._resync_btn.setToolTip(
            _(
                "Re-extract the complete browser history from scratch and upsert all records.\n"
                "Use this to back-fill fields (e.g. Visit Count) that were not captured\n"
                "in earlier syncs. Existing records are never deleted — only updated.\n"
                "This may take a while for large histories."
            )
        )
        self._resync_btn.clicked.connect(self.full_resync_requested)

        btn_row.addWidget(self._vacuum_btn)
        btn_row.addWidget(self._normalize_btn)
        btn_row.addWidget(self._fts_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Action buttons — Row 2: export / sync / migration ─
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)

        btn_row2.addWidget(self._export_btn)
        btn_row2.addWidget(self._resync_btn)

        self._migrate_btn = QPushButton(_("Migrate Legacy Data…"))
        self._migrate_btn.setIcon(get_icon("upload"))
        self._migrate_btn.setToolTip(
            _("Import data from a previous HistorySync installation.\nUseful if you skipped migration on first launch.")
        )
        self._migrate_btn.clicked.connect(self._on_migrate_requested)
        btn_row2.addWidget(self._migrate_btn)
        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        # ── Progress bar (hidden when idle) ───────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── Log output ────────────────────────────────────────
        self._log_lbl = QLabel("")
        self._log_lbl.setObjectName("muted")
        self._log_lbl.setWordWrap(True)
        layout.addWidget(self._log_lbl)

        self._all_btns = [
            self._vacuum_btn,
            self._normalize_btn,
            self._fts_btn,
            self._export_btn,
            self._resync_btn,
            self._migrate_btn,
        ]

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _stat_widget(label: str) -> tuple[QLabel, QWidget]:
        """Return (value_label, container_widget) — a small stat column."""
        w = QWidget()
        w.setMinimumWidth(130)
        w.setAttribute(Qt.WA_NoSystemBackground, True)
        w.setAutoFillBackground(False)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 12, 0)
        v.setSpacing(4)
        lbl = QLabel(label)
        lbl.setObjectName("muted")
        val = QLabel("—")
        val.setObjectName("settings_stat_value")  # distinct from dashboard stat_value
        v.addWidget(lbl)
        v.addWidget(val)
        return val, w

    # ── Public API ────────────────────────────────────────────

    def refresh_stats(self, stats):
        """Populate the stat widgets from a ``DbStats`` instance."""
        self._val_file_size.setText(_fmt_bytes(stats.file_size_bytes))

        wasted = stats.wasted_bytes
        wasted_pct = stats.wasted_pct
        if wasted > 0:
            self._val_wasted.setText(f"{_fmt_bytes(wasted)}  ({wasted_pct:.0f}%)")
            # Amber tint when fragmentation exceeds 10 %
            obj = "warning" if wasted_pct > 10 else "settings_stat_value"
            self._val_wasted.setObjectName(obj)
            self._val_wasted.style().unpolish(self._val_wasted)
            self._val_wasted.style().polish(self._val_wasted)
        else:
            self._val_wasted.setText(_("None"))
            self._val_wasted.setObjectName("settings_stat_value")

        self._val_records.setText(f"{stats.record_count:,}")
        self._val_domains.setText(f"{stats.domain_count:,}")

    def set_resync_running(self, running: bool):
        """Disable/enable all buttons while a full resync is in progress."""
        for btn in self._all_btns:
            btn.setEnabled(not running)
        self._progress.setVisible(running)
        if running:
            self._log_lbl.setText(_("Full resync in progress — re-reading all browser history…"))
            self._log_lbl.setObjectName("muted")
        else:
            self._log_lbl.style().unpolish(self._log_lbl)
            self._log_lbl.style().polish(self._log_lbl)

    def set_resync_done(self, new_count: int):
        """Show the result after a full resync finishes."""
        self._log_lbl.setText(_("✓ Full resync complete — {n} new records upserted.").format(n=f"{new_count:,}"))
        self._log_lbl.setObjectName("success")
        self._log_lbl.style().unpolish(self._log_lbl)
        self._log_lbl.style().polish(self._log_lbl)

    def set_resync_error(self, msg: str):
        """Show an error message after a full resync fails."""
        self._log_lbl.setText(_("✗ Full resync failed: {msg}").format(msg=msg))
        self._log_lbl.setObjectName("error")
        self._log_lbl.style().unpolish(self._log_lbl)
        self._log_lbl.style().polish(self._log_lbl)

    def set_running(self, running: bool):
        """Disable/enable all buttons and show/hide the progress bar."""
        for btn in self._all_btns:
            btn.setEnabled(not running)
        self._progress.setVisible(running)
        if running:
            self._log_lbl.setText("")

    def append_log(self, text: str):
        """Append a line to the inline log label."""
        current = self._log_lbl.text()
        self._log_lbl.setText((current + "\n" + text).strip())

    def set_result(self, saved_bytes: int):
        """Show a final summary after vacuum completes."""
        if saved_bytes > 0:
            self._log_lbl.setObjectName("success")
        else:
            self._log_lbl.setObjectName("muted")
        self._log_lbl.style().unpolish(self._log_lbl)
        self._log_lbl.style().polish(self._log_lbl)

    def _on_migrate_requested(self) -> None:
        """Open the migration wizard; offer a force-migrate option when no legacy data is found."""
        from src.utils.migration_detector import detect_legacy_installation
        from src.views.migration_wizard import MigrationWizard

        legacy = detect_legacy_installation()
        if not legacy.found:
            from PySide6.QtWidgets import QMessageBox

            msg = QMessageBox(self)
            msg.setWindowTitle(_("No Legacy Data"))
            msg.setText(_("No legacy HistorySync data was found.\n\nNothing to migrate."))
            msg.setInformativeText(
                _(
                    "If legacy data was not detected automatically, or you want to "
                    "test the migration pipeline, you can force-run it on current data "
                )
            )
            msg.setIcon(QMessageBox.Information)
            force_btn = msg.addButton(_("Force Migrate\u2026"), QMessageBox.ActionRole)
            ok_btn = msg.addButton(QMessageBox.Ok)
            msg.setDefaultButton(ok_btn)
            msg.exec()

            if msg.clickedButton() is not force_btn:
                return

            # User explicitly chose to run a real migration on current data.
            from src.utils.migration_detector import build_force_migrate_result

            legacy = build_force_migrate_result()

        wizard = MigrationWizard(legacy, parent=self)
        wizard.exec()
