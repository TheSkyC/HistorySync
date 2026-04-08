# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.services.migration_service import MigrationReport, MigrationService, MigrationStep
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.utils.migration_detector import LegacyDetectionResult
from src.utils.theme_manager import ThemeManager

log = get_logger("view.migration_wizard")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


def _make_colored_circle(color: str, size: int = 10) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    # Use 1-pixel margin to ensure circle is fully within pixmap and centered
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return px


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setObjectName("muted")
    line.setFixedHeight(1)
    return line


def _icon_label(icon_name: str, size: int = 16) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(get_icon(icon_name, size).pixmap(size, size))
    return lbl


def _icon_banner(icon_name: str, icon_size: int, text: str, text_style: str, bg_light: str, bg_dark: str) -> QWidget:
    """Return a rounded banner widget with a Feather icon on the left and wrapped text on the right.

    Args:
        icon_name: Feather icon name
        icon_size: Icon size in pixels
        text: Banner text content
        text_style: CSS style for text (color, font-size, etc.)
        bg_light: Background color for light theme (opaque hex color)
        bg_dark: Background color for dark theme (opaque hex color)
    """
    container = QWidget()

    # Use theme-aware background color to avoid double-layer effect
    theme = ThemeManager.instance().current
    bg_color = bg_light if theme == "light" else bg_dark
    container.setStyleSheet(f"background: {bg_color}; border-radius: 6px;")

    row = QHBoxLayout(container)
    row.setContentsMargins(10, 8, 10, 8)
    row.setSpacing(8)
    ic = _icon_label(icon_name, icon_size)
    row.addWidget(ic, 0, Qt.AlignTop)
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(text_style)
    row.addWidget(lbl, 1)
    return container


def _update_icon_label(lbl: QLabel, icon_name: str, size: int = 16) -> None:
    """Swap the pixmap of an existing icon QLabel."""
    lbl.setPixmap(get_icon(icon_name, size).pixmap(size, size))


# ---------------------------------------------------------------------------
# Step indicator widget (like FirstRunWizard's _ProgressIndicator)
# ---------------------------------------------------------------------------


class _StepIndicator(QWidget):
    """Horizontal row of numbered step dots."""

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self._count = count
        self._current = 0
        self.setMinimumHeight(32)
        layout = QHBoxLayout(self)
        layout.setSpacing(0)
        layout.addStretch()

        self._dots: list[QLabel] = []
        for i in range(count):
            if i > 0:
                connector = QLabel("·" * 3)
                connector.setObjectName("muted")
                connector.setAlignment(Qt.AlignCenter)
                layout.addWidget(connector)
                self._dots.append(None)  # placeholder

            dot = QLabel(str(i + 1))
            dot.setFixedSize(22, 22)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("border-radius: 11px; font-size: 11px; font-weight: 600;")
            layout.addWidget(dot)
            self._dots.append(dot)

        layout.addStretch()
        ThemeManager.instance().theme_changed.connect(self._refresh)
        self._refresh()

    def _get_inactive_colors(self) -> tuple[str, str]:
        """Return (background_color, text_color) for inactive steps."""
        theme = ThemeManager.instance().current
        if theme == "light":
            return "#d8dce8", "#8892a4"
        # dark
        return "#333", "#888"

    def set_step(self, idx: int) -> None:
        self._current = idx
        self._refresh()

    def _refresh(self) -> None:
        real_idx = 0
        for item in self._dots:
            if item is None:
                continue
            if real_idx < self._current:
                item.setStyleSheet(
                    "border-radius: 11px; font-size: 11px; font-weight: 600;background: #3b82f6; color: white;"
                )
            elif real_idx == self._current:
                item.setStyleSheet(
                    "border-radius: 11px; font-size: 11px; font-weight: 600;background: #5b9cf6; color: white;"
                )
            else:
                bg_color, text_color = self._get_inactive_colors()
                item.setStyleSheet(
                    f"border-radius: 11px; font-size: 11px; font-weight: 600;"
                    f"background: {bg_color}; color: {text_color};"
                )
            real_idx += 1


# ---------------------------------------------------------------------------
# Page base
# ---------------------------------------------------------------------------


class _PageBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def on_enter(self) -> None:
        """Called when this page becomes visible."""


# ---------------------------------------------------------------------------
# Page 0: Detection Report
# ---------------------------------------------------------------------------


class _DetectionPage(_PageBase):
    def __init__(self, result: LegacyDetectionResult, parent=None):
        super().__init__(parent)
        self._result = result
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(12)

        is_force = self._result.is_force_mode

        # Header
        header = QHBoxLayout()
        icon = _icon_label("flask" if is_force else "search", 28)
        header.addWidget(icon)
        header.addSpacing(8)
        title = QLabel(_("Force Migration") if is_force else _("Legacy Data Detected"))
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        if is_force:
            # Prominent warning banner so the user knows this is a test run
            warn = _icon_banner(
                "alert-triangle",
                14,
                _("Force-migration mode"),
                "font-size: 12px; color: #f59e0b;",
                "#f0e9dd",  # Light theme: blended orange
                "#2f2920",  # Dark theme: blended orange
            )
            layout.addWidget(warn)
            subtitle = QLabel(_("The following items will be processed:"))
        else:
            subtitle = QLabel(
                _(
                    "We found existing HistorySync data from a previous version.\n"
                    "The following items can be safely migrated to the current version:"
                )
            )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        layout.addWidget(_divider())

        # Data items
        r = self._result
        items = []

        if r.db_file:
            size_str = _fmt_bytes(r.db_size_bytes) if r.db_size_bytes else ""
            count_str = _("{n} records").format(n=f"{r.db_record_count:,}")
            detail = f"{count_str}  ({size_str})" if size_str else count_str
            items.append((_("History Database"), detail, True))

        if r.webdav_enabled:
            items.append((_("WebDAV Sync Configuration"), _("Enabled"), True))

        if r.favicon_db:
            items.append((_("Site Icon Cache"), _("{n} icons").format(n=f"{r.favicon_count:,}"), True))

        if r.secret_key:
            items.append((_("Encryption Key"), _("Found"), True))

        for label, detail, _ok in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setPixmap(_make_colored_circle("#22c55e", 10))
            row.addWidget(dot, 0, Qt.AlignVCenter)
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet("font-weight: 500;")
            row.addWidget(name_lbl, 0, Qt.AlignVCenter)
            row.addStretch()
            detail_lbl = QLabel(detail)
            detail_lbl.setObjectName("muted")
            row.addWidget(detail_lbl, 0, Qt.AlignVCenter)
            layout.addLayout(row)

        layout.addWidget(_divider())

        # Path info
        path_lbl = QLabel(_("Data location:  {path}").format(path=r.config_dir))
        path_lbl.setObjectName("muted")
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(path_lbl)

        # Safety note
        note = _icon_banner(
            "shield",
            14,
            _(
                "Migration is safe — your data will be backed up first.\n"
                "If anything fails, we will automatically restore everything."
            ),
            "font-size: 12px; color: #5b9cf6;",
            "#e4ebf5",  # Light theme: blended blue
            "#1f2733",  # Dark theme: blended blue
        )
        layout.addWidget(note)
        layout.addStretch()


# ---------------------------------------------------------------------------
# Page 1: Migration Plan / Confirm
# ---------------------------------------------------------------------------


class _ConfirmPage(_PageBase):
    def __init__(self, result: LegacyDetectionResult, parent=None):
        super().__init__(parent)
        self._result = result
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        icon = _icon_label("clipboard", 28)
        header.addWidget(icon)
        header.addSpacing(8)
        title = QLabel(_("Migration Plan"))
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        intro = QLabel(_("The following steps will be performed (all are reversible):"))
        intro.setObjectName("muted")
        layout.addWidget(intro)

        layout.addWidget(_divider())

        steps = [
            ("1", _("Create a backup of your current data")),
            ("2", _("Upgrade the database schema")),
            ("3", _("Merge your configuration")),
            ("4", _("Verify the migration result")),
        ]
        for num, desc in steps:
            row = QHBoxLayout()
            row.setSpacing(10)
            num_lbl = QLabel(num)
            num_lbl.setFixedSize(22, 22)
            num_lbl.setAlignment(Qt.AlignCenter)
            num_lbl.setStyleSheet(
                "border-radius: 11px; background: #3b82f6; color: white; font-weight: 700; font-size: 11px;"
            )
            row.addWidget(num_lbl, 0, Qt.AlignVCenter)
            desc_lbl = QLabel(desc)
            row.addWidget(desc_lbl, 1, Qt.AlignVCenter)
            layout.addLayout(row)

        layout.addWidget(_divider())

        # Guarantees
        if self._result.is_force_mode:
            guarantee = _icon_banner(
                "alert-triangle",
                14,
                _(
                    "Force-migration mode: this will run the real migration pipeline on your "
                    "current live data.\n"
                    "A backup is created in the first step.  All records will be preserved."
                ),
                "font-size: 12px; color: #f59e0b;",
                "#f0e9dd",  # Light theme: blended orange
                "#2f2920",  # Dark theme: blended orange
            )
        else:
            guarantee = _icon_banner(
                "info",
                14,
                _(
                    "All history records, WebDAV settings, privacy rules and UI "
                    "preferences will be fully preserved — nothing will be deleted."
                ),
                "font-size: 12px; color: #5b9cf6;",
                "#e4ebf5",  # Light theme: blended blue
                "#1f2733",  # Dark theme: blended blue
            )
        layout.addWidget(guarantee)

        warning_row = QHBoxLayout()
        warning_row.setSpacing(6)
        warning_row.addWidget(_icon_label("alert-circle", 13))
        warning_lbl = QLabel(_("Please do not close the application during migration.   Estimated time: < 30 s"))
        warning_lbl.setObjectName("muted")
        warning_lbl.setStyleSheet("font-size: 11px;")
        warning_row.addWidget(warning_lbl)
        warning_row.addStretch()
        layout.addLayout(warning_row)

        layout.addStretch()


# ---------------------------------------------------------------------------
# Page 2: Progress
# ---------------------------------------------------------------------------

_STEP_LABELS = {
    MigrationStep.BACKUP: N_("Create backup"),
    MigrationStep.DB_MIGRATE: N_("Upgrade database schema"),
    MigrationStep.CONFIG_MERGE: N_("Merge configuration"),
    MigrationStep.VERIFY: N_("Verify result"),
}

_STEP_ICON_PENDING = "circle"
_STEP_ICON_RUNNING = "refresh"
_STEP_ICON_DONE = "check-circle"
_STEP_ICON_FAILED = "x-circle"

_ICON_SIZE_STEP = 16


class _ProgressPage(_PageBase):
    def __init__(self, result: LegacyDetectionResult, parent=None):
        super().__init__(parent)
        self._result = result
        # (icon_lbl, desc_lbl)
        self._step_rows: dict[MigrationStep, tuple[QLabel, QLabel]] = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        icon = _icon_label("settings", 28)
        header.addWidget(icon)
        header.addSpacing(8)
        self._title_lbl = QLabel(_("Migrating Data…"))
        self._title_lbl.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(self._title_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Progress bar
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setValue(0)
        self._prog_bar.setFixedHeight(6)
        self._prog_bar.setTextVisible(False)
        layout.addWidget(self._prog_bar)

        layout.addWidget(_divider())

        # Step rows — use icon labels instead of text chars
        for step in (
            MigrationStep.BACKUP,
            MigrationStep.DB_MIGRATE,
            MigrationStep.CONFIG_MERGE,
            MigrationStep.VERIFY,
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            status_icon = _icon_label(_STEP_ICON_PENDING, _ICON_SIZE_STEP)
            status_icon.setFixedSize(_ICON_SIZE_STEP, _ICON_SIZE_STEP)
            desc_lbl = QLabel(_(_STEP_LABELS[step]))
            desc_lbl.setObjectName("muted")
            row.addWidget(status_icon)
            row.addWidget(desc_lbl, 1)
            layout.addLayout(row)
            self._step_rows[step] = (status_icon, desc_lbl)

        layout.addWidget(_divider())

        # Record count detail
        self._detail_lbl = QLabel("")
        self._detail_lbl.setObjectName("muted")
        layout.addWidget(self._detail_lbl)

        # Error detail (hidden initially)
        self._error_lbl = QLabel("")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setStyleSheet(
            "color: #ef4444; padding: 8px; background: rgba(239,68,68,0.08); border-radius: 6px;"
        )
        self._error_lbl.setVisible(False)
        layout.addWidget(self._error_lbl)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public update methods — called from the wizard via Qt signals
    # ------------------------------------------------------------------

    def mark_step_running(self, step: MigrationStep) -> None:
        icon_lbl, desc_lbl = self._step_rows[step]
        _update_icon_label(icon_lbl, _STEP_ICON_RUNNING, _ICON_SIZE_STEP)
        icon_lbl.setStyleSheet("color: #f59e0b;")  # tint hint (works if icon is template)
        desc_lbl.setStyleSheet("color: inherit;")

    def mark_step_done(self, step: MigrationStep) -> None:
        icon_lbl, desc_lbl = self._step_rows[step]
        _update_icon_label(icon_lbl, _STEP_ICON_DONE, _ICON_SIZE_STEP)
        desc_lbl.setStyleSheet("color: #22c55e;")

    def mark_step_failed(self, step: MigrationStep) -> None:
        icon_lbl, desc_lbl = self._step_rows[step]
        _update_icon_label(icon_lbl, _STEP_ICON_FAILED, _ICON_SIZE_STEP)
        desc_lbl.setStyleSheet("color: #ef4444;")

    def set_progress(self, pct: int) -> None:
        self._prog_bar.setValue(pct)

    def set_detail(self, text: str) -> None:
        self._detail_lbl.setText(text)

    def show_error(self, step: MigrationStep, message: str) -> None:
        self._title_lbl.setText(_("Migration Failed"))
        self._title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #ef4444;")
        self.mark_step_failed(step)
        self._error_lbl.setText(_("Error: {msg}").format(msg=message))
        self._error_lbl.setVisible(True)

    def show_rollback_done(self) -> None:
        self._detail_lbl.setText(_("Your original data has been restored from backup."))

    def reset(self) -> None:
        """Reset to initial state before starting a migration run."""
        self._title_lbl.setText(_("Migrating Data…"))
        self._title_lbl.setStyleSheet("font-size: 18px; font-weight: 700;")
        self._prog_bar.setValue(0)
        self._error_lbl.setVisible(False)
        self._error_lbl.setText("")
        self._detail_lbl.setText("")
        for _step, (icon_lbl, desc_lbl) in self._step_rows.items():
            _update_icon_label(icon_lbl, _STEP_ICON_PENDING, _ICON_SIZE_STEP)
            icon_lbl.setStyleSheet("")
            desc_lbl.setStyleSheet("")
            desc_lbl.setObjectName("muted")


# ---------------------------------------------------------------------------
# Page 3: Done (success)
# ---------------------------------------------------------------------------


class _DonePage(_PageBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._backup_dir: Path | None = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(14)
        layout.addStretch()

        icon = _icon_label("check-circle", 52)
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignCenter)

        title = QLabel(_("Migration Complete!"))
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #22c55e;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setAlignment(Qt.AlignCenter)
        self._summary_lbl.setObjectName("muted")
        layout.addWidget(self._summary_lbl)

        layout.addWidget(_divider())

        # Backup location
        backup_row = QHBoxLayout()
        backup_row.addStretch()
        backup_icon = _icon_label("folder", 14)
        backup_row.addWidget(backup_icon, 0, Qt.AlignVCenter)
        backup_row.addSpacing(4)
        self._backup_lbl = QLabel("")
        self._backup_lbl.setObjectName("muted")
        self._backup_lbl.setStyleSheet("font-size: 11px;")
        self._backup_lbl.setWordWrap(True)
        backup_row.addWidget(self._backup_lbl, 1, Qt.AlignVCenter)
        backup_row.addStretch()
        layout.addLayout(backup_row)

        layout.addStretch()

    def populate(self, report: MigrationReport) -> None:
        after = report.db_record_count_after
        self._summary_lbl.setText(
            _("All your data has been migrated successfully.\n{n} history records are intact.").format(n=f"{after:,}")
        )
        if report.backup_dir:
            self._backup_lbl.setText(_("Backup saved to:  {path}").format(path=report.backup_dir))
        else:
            self._backup_lbl.setText("")


# ---------------------------------------------------------------------------
# Page 4: Skipped
# ---------------------------------------------------------------------------


class _SkipPage(_PageBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(14)
        layout.addStretch()

        icon = _icon_label("skip-forward", 48)
        icon.setFixedSize(48, 48)
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignCenter)

        title = QLabel(_("Migration Skipped"))
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        note = QLabel(
            _(
                "Your previous data has not been changed.\n\n"
                "HistorySync will start with a fresh configuration.\n"
                "You can always run the migration later from\n"
                "Settings → Maintenance → Migrate from Legacy Data."
            )
        )
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        note.setObjectName("muted")
        layout.addWidget(note)

        layout.addStretch()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


class _MigrationWorker(QThread):
    """Runs MigrationService.run() in a background thread."""

    step_started = Signal(str)  # step.value
    step_progress = Signal(str, float, str)  # step.value, 0-1, message
    finished = Signal(object)  # MigrationReport

    def __init__(self, result: LegacyDetectionResult, parent=None):
        super().__init__(parent)
        self._result = result
        self._service: MigrationService | None = None

    def run(self) -> None:
        last_step = [None]

        def _cb(step: MigrationStep, fraction: float, msg: str):
            if step != last_step[0]:
                self.step_started.emit(step.value)
                last_step[0] = step
            self.step_progress.emit(step.value, fraction, msg)

        self._service = MigrationService(self._result, _cb)
        report = self._service.run()
        self.finished.emit(report)


# ---------------------------------------------------------------------------
# MigrationWizard
# ---------------------------------------------------------------------------

_PAGE_DETECTION = 0
_PAGE_CONFIRM = 1
_PAGE_PROGRESS = 2
_PAGE_DONE = 3
_PAGE_SKIP = 4


class MigrationWizard(QDialog):
    """
    Multi-page migration wizard.

    Signals
    -------
    migration_completed(bool):
        Emitted on close.  True = migration done (success or already rolled
        back), False = user skipped or quit without migrating.
    """

    migration_completed = Signal(bool)

    def __init__(self, result: LegacyDetectionResult, parent=None):
        super().__init__(parent)
        self._result = result
        self._worker: _MigrationWorker | None = None
        self._report: MigrationReport | None = None
        self._user_quit = False  # True if user closed the window mid-migration
        self._migration_done = False  # True once migration finished (success or rollback)

        self.setWindowTitle(_("HistorySync — Migration Wizard"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(540, 460)
        self.setMaximumHeight(560)
        self.resize(540, 490)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Step indicator (5 visible pages: 0-3 + skip)
        self._step_indicator = _StepIndicator(4, self)
        root.addWidget(self._step_indicator)

        # Page stack
        self._stack = QStackedWidget()

        self._page_detection = _DetectionPage(self._result)
        self._page_confirm = _ConfirmPage(self._result)
        self._page_progress = _ProgressPage(self._result)
        self._page_done = _DonePage()
        self._page_skip = _SkipPage()

        for page in (
            self._page_detection,
            self._page_confirm,
            self._page_progress,
            self._page_done,
            self._page_skip,
        ):
            self._stack.addWidget(page)

        root.addWidget(self._stack, 1)

        # Navigation bar
        nav = QHBoxLayout()
        nav.setContentsMargins(20, 10, 20, 16)
        nav.setSpacing(8)

        self._skip_btn = QPushButton(_("Skip — Start Fresh"))
        self._skip_btn.setObjectName("muted")
        self._skip_btn.clicked.connect(self._on_skip)

        self._back_btn = QPushButton(_("Back"))
        self._back_btn.setIcon(get_icon("chevron-left", 16))
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self._go_back)

        self._next_btn = QPushButton(_("Start Migration"))
        self._next_btn.setIcon(get_icon("chevron-right", 16))
        self._next_btn.setLayoutDirection(Qt.RightToLeft)
        self._next_btn.setObjectName("primary_btn")
        self._next_btn.clicked.connect(self._go_next)

        nav.addWidget(self._skip_btn)
        nav.addStretch()
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        self._refresh_nav()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _idx(self) -> int:
        return self._stack.currentIndex()

    def _go_next(self) -> None:
        idx = self._idx()

        if idx == _PAGE_DETECTION:
            self._go_to(_PAGE_CONFIRM)

        elif idx == _PAGE_CONFIRM:
            self._start_migration()

        elif idx == _PAGE_PROGRESS:
            # Should not happen (button hidden during progress)
            pass

        elif idx in (_PAGE_DONE, _PAGE_SKIP):
            self._finish()

    def _go_back(self) -> None:
        idx = self._idx()
        if idx == _PAGE_CONFIRM:
            self._go_to(_PAGE_DETECTION)

    def _go_to(self, page_idx: int) -> None:
        self._stack.setCurrentIndex(page_idx)
        # Update step indicator for the first 4 pages
        if page_idx < 4:
            self._step_indicator.set_step(page_idx)
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        idx = self._idx()

        # Skip button visibility
        self._skip_btn.setVisible(idx in (_PAGE_DETECTION, _PAGE_CONFIRM))
        # Back button
        self._back_btn.setVisible(idx == _PAGE_CONFIRM)
        # Next button text / icon
        if idx == _PAGE_DETECTION:
            self._next_btn.setText(_("Start Migration"))
            self._next_btn.setEnabled(True)
            self._next_btn.setVisible(True)
        elif idx == _PAGE_CONFIRM:
            self._next_btn.setText(_("Migrate Now"))
            self._next_btn.setEnabled(True)
            self._next_btn.setVisible(True)
        elif idx == _PAGE_PROGRESS:
            self._next_btn.setVisible(False)
        elif idx in (_PAGE_DONE, _PAGE_SKIP):
            self._next_btn.setText(_("Launch HistorySync"))
            self._next_btn.setIcon(get_icon("play", 16))
            self._next_btn.setEnabled(True)
            self._next_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Migration orchestration
    # ------------------------------------------------------------------

    def _start_migration(self) -> None:
        self._page_progress.reset()
        self._go_to(_PAGE_PROGRESS)

        self._worker = _MigrationWorker(self._result, self)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.finished.connect(self._on_migration_finished)
        self._worker.start()

    def _on_step_started(self, step_value: str) -> None:
        step = MigrationStep(step_value)
        self._page_progress.mark_step_running(step)

    def _on_step_progress(self, step_value: str, fraction: float, message: str) -> None:
        step = MigrationStep(step_value)
        overall_pct = int(fraction * 100)
        self._page_progress.set_progress(overall_pct)
        self._page_progress.set_detail(message)

        # Mark done when a step reaches 100 %
        if fraction >= 1.0:
            self._page_progress.mark_step_done(step)

    def _on_migration_finished(self, report: MigrationReport) -> None:
        self._report = report
        self._migration_done = True

        if report.success:
            log.info("Migration wizard: success")
            self._page_done.populate(report)
            self._go_to(_PAGE_DONE)
        else:
            log.error("Migration wizard: failed — %s", report.error)
            if report.error_step:
                self._page_progress.show_error(report.error_step, report.error)
            if report.rollback_ok:
                self._page_progress.show_rollback_done()
            # Show error dialog
            rb_note = (
                _("\n\nYour original data has been restored from the backup.")
                if report.rollback_ok
                else _("\n\nAutomatic rollback also failed. Please restore from the backup directory manually.")
            )
            QMessageBox.critical(
                self,
                _("Migration Failed"),
                _("Migration failed at step: {step}\n\nError: {err}{note}").format(
                    step=_(report.error_step.value) if report.error_step else _("unknown"),
                    err=report.error,
                    note=rb_note,
                ),
            )
            # Stay on progress page, re-enable skip/close
            self._skip_btn.setVisible(True)
            self._skip_btn.setText(_("Close"))
            self._skip_btn.clicked.disconnect()
            self._skip_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # Skip / finish
    # ------------------------------------------------------------------

    def _on_skip(self) -> None:
        reply = QMessageBox.question(
            self,
            _("Skip Migration?"),
            _(
                "Are you sure you want to skip migration?\n\n"
                "HistorySync will start fresh with default settings.\n"
                "Your legacy data will not be changed.\n\n"
                "You can run the migration later from Settings → Maintenance."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Mark first_run_completed so we don't show migration wizard again
        # on the next launch (user consciously chose to skip).
        try:
            from src.models.app_config import AppConfig

            cfg = AppConfig.from_dict(self._result.raw_config)
            cfg.first_run_completed = True
            cfg.save()
            log.info("Migration wizard: user skipped — marked first_run_completed=True")
        except Exception as exc:
            log.warning("Migration wizard: skip save failed: %s", exc)

        self._go_to(_PAGE_SKIP)

    def _finish(self) -> None:
        self.migration_completed.emit(self._migration_done)
        self.accept()

    # ------------------------------------------------------------------
    # Close-button guard
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                _("Migration in Progress"),
                _(
                    "Migration is still running.\n\n"
                    "Closing now may leave your data in an inconsistent state.\n"
                    "Are you sure you want to quit?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._worker.quit()
            self._worker.wait(3000)

        self.migration_completed.emit(False)
        event.accept()
