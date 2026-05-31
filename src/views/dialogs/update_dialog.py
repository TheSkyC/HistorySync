# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Update detail dialog — shown when the user clicks a banner or "Check for Updates".

Displays:
* Version transition (current → new), channel, and publish date.
* Localized release summary.
* Changelog entries grouped by type (feature / fix / …).
* Download progress bar (when downloading).
* Action buttons: Update Now / Skip This Version / Remind Me Later / View Release.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.services.update_debug import effective_current_version
from src.services.update_models import ChangelogEntry, UpdateInfo
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger

log = get_logger("view.update_dialog")

# Emoji/icon prefix per changelog entry type — mirrors the release notes style.
_TYPE_ICONS: dict[str, str] = {
    "feature": "\u2728",  # ✨
    "fix": "\U0001f41b",  # 🐛
    "improvement": "\U0001f527",  # 🔧
    "performance": "\U0001f680",  # 🚀
    "security": "\U0001f512",  # 🔒
    "breaking": "\u26a0\ufe0f",  # ⚠️
    "docs": "\U0001f4d6",  # 📖
    "deprecated": "\U0001f6ab",  # 🚫
    "internal": "\U0001f3d7\ufe0f",  # 🏗️
}

_TYPE_DISPLAY: dict[str, str] = {
    "feature": N_("Features"),
    "fix": N_("Bug Fixes"),
    "improvement": N_("Improvements"),
    "performance": N_("Performance"),
    "security": N_("Security"),
    "breaking": N_("Breaking Changes"),
    "docs": N_("Documentation"),
    "deprecated": N_("Deprecated"),
    "internal": N_("Internal"),
}


class UpdateDialog(QDialog):
    """Modal dialog presenting an available update with changelog and actions."""

    update_requested = Signal()  # user wants to download/install
    skip_requested = Signal(str)  # user wants to skip this version
    remind_later = Signal()  # user wants to dismiss for now
    view_release_requested = Signal(str)  # open release notes URL

    def __init__(self, info: UpdateInfo, can_self_update: bool = True, allow_download: bool = True, parent=None):
        super().__init__(parent)
        self._info = info
        self._can_self_update = can_self_update
        self._allow_download = allow_download
        self.setWindowTitle(_("Update Available"))
        self.setMinimumSize(520, 400)
        self.resize(580, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()

    # ── UI construction ───────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Header ────────────────────────────────────────────
        header = QVBoxLayout()
        header.setSpacing(4)

        title = QLabel(_("A new version of HistorySync is available!"))
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)

        version_text = _("{current} → {new}").format(
            current=effective_current_version(),
            new=self._info.release.version,
        )
        channel = self._info.release.channel
        if channel and channel != "stable":
            version_text += f"  ({channel})"
        if self._info.release.published_at:
            # Show date portion only
            date_part = self._info.release.published_at[:10]
            version_text += f"  ·  {date_part}"

        ver_lbl = QLabel(version_text)
        ver_lbl.setObjectName("muted")
        header.addWidget(ver_lbl)
        layout.addLayout(header)

        # ── Summary ───────────────────────────────────────────
        if self._info.release.summary:
            summary_lbl = QLabel(self._info.release.summary)
            summary_lbl.setWordWrap(True)
            summary_lbl.setTextFormat(Qt.PlainText)
            summary_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout.addWidget(summary_lbl)

        # ── Changelog ─────────────────────────────────────────
        if self._info.release.changelog:
            changelog_frame = self._build_changelog()
            layout.addWidget(changelog_frame, 1)

        # ── Download info ─────────────────────────────────────
        if self._info.asset is not None:
            info_parts: list[str] = []
            if self._info.asset.label:
                info_parts.append(self._info.asset.label)
            if self._info.asset.size_bytes:
                mb = self._info.asset.size_bytes / (1024 * 1024)
                info_parts.append(f"{mb:.1f} MB")
            if info_parts:
                asset_lbl = QLabel("  ·  ".join(info_parts))
                asset_lbl.setObjectName("muted")
                layout.addWidget(asset_lbl)

        # ── Progress bar (hidden by default) ──────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("muted")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        # ── Buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._view_btn = QPushButton(_("View Release"))
        self._view_btn.setFlat(True)
        self._view_btn.setCursor(Qt.PointingHandCursor)
        self._view_btn.clicked.connect(lambda: self.view_release_requested.emit(self._info.release.notes_url))
        btn_row.addWidget(self._view_btn)

        btn_row.addStretch()

        self._skip_btn = QPushButton(_("Skip This Version"))
        self._skip_btn.clicked.connect(self._on_skip_clicked)
        btn_row.addWidget(self._skip_btn)

        self._later_btn = QPushButton(_("Remind Me Later"))
        self._later_btn.clicked.connect(self.remind_later)
        self._later_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._later_btn)

        self._update_btn = QPushButton(self._action_button_text())
        self._update_btn.setObjectName("primary_btn")
        self._update_btn.setMinimumWidth(110)
        self._update_btn.setMinimumHeight(34)
        self._update_btn.setIcon(get_icon("download", 14))
        self._update_btn.clicked.connect(self.update_requested)
        self._update_btn.setVisible(self._allow_download)
        btn_row.addWidget(self._update_btn)

        layout.addLayout(btn_row)

    def _build_changelog(self) -> QWidget:
        """Build a scrollable, type-grouped changelog widget."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(220)

        content = QWidget()
        cl_layout = QVBoxLayout(content)
        cl_layout.setContentsMargins(0, 0, 0, 0)
        cl_layout.setSpacing(8)

        # Group entries by type
        groups: dict[str, list[ChangelogEntry]] = {}
        for entry in self._info.release.changelog:
            groups.setdefault(entry.entry_type, []).append(entry)

        # Display in a stable order
        type_order = list(_TYPE_DISPLAY.keys())
        for entry_type in type_order:
            entries = groups.pop(entry_type, None)
            if not entries:
                continue
            self._add_changelog_group(cl_layout, entry_type, entries)

        # Remaining types not in predefined order
        for entry_type, entries in groups.items():
            self._add_changelog_group(cl_layout, entry_type, entries)

        cl_layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _add_changelog_group(self, layout: QVBoxLayout, entry_type: str, entries: list[ChangelogEntry]) -> None:
        icon = _TYPE_ICONS.get(entry_type, "•")
        label = _(_TYPE_DISPLAY.get(entry_type, entry_type.capitalize()))
        group_title = QLabel(f"{icon}  {label}")
        group_title.setTextFormat(Qt.PlainText)
        group_title.setStyleSheet("font-weight: 600; font-size: 12px; margin-top: 4px;")
        layout.addWidget(group_title)

        for entry in entries:
            scope_prefix = f"[{entry.scope}] " if entry.scope else ""
            item_lbl = QLabel(f"    • {scope_prefix}{entry.title}")
            item_lbl.setTextFormat(Qt.PlainText)
            item_lbl.setWordWrap(True)
            item_lbl.setObjectName("muted")
            layout.addWidget(item_lbl)

    # ── Public API (called by the service integration) ────────

    def set_downloading(self, downloading: bool) -> None:
        """Switch to download-progress mode or back to idle."""
        self._progress_bar.setVisible(downloading)
        self._progress_label.setVisible(downloading)
        self._update_btn.setEnabled(not downloading)
        self._skip_btn.setEnabled(not downloading)
        if downloading:
            self._update_btn.setText(_("Downloading..."))
            self._progress_bar.setValue(0)
        else:
            self._update_btn.setText(self._action_button_text())

    @Slot(int, int)
    def on_download_progress(self, received: int, total: int) -> None:
        if total > 0:
            pct = int(received * 100 / total)
            self._progress_bar.setValue(pct)
            mb_recv = received / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self._progress_label.setText(f"{mb_recv:.1f} / {mb_total:.1f} MB")
        else:
            self._progress_bar.setRange(0, 0)  # indeterminate
            mb_recv = received / (1024 * 1024)
            self._progress_label.setText(f"{mb_recv:.1f} MB")

    def set_download_finished(self, success: bool, message: str = "") -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        if success:
            self._update_btn.setText(_("Install Now"))
            self._update_btn.setEnabled(True)
            self._progress_label.setVisible(True)
            self._progress_label.setText(_("Download complete — ready to install."))
            self._progress_label.setStyleSheet("color: #4caf50;")
        else:
            self._update_btn.setEnabled(True)
            self._update_btn.setText(_("Retry") if self._allow_download else self._action_button_text())
            if message:
                self._progress_label.setVisible(True)
                self._progress_label.setText(message)
                self._progress_label.setStyleSheet("color: #f44336;")

    def set_up_to_date(self) -> None:
        """Re-purpose the dialog to show "you're already up to date"."""
        self.setWindowTitle(_("No Update Available"))
        # Hide action buttons except close
        self._update_btn.setVisible(False)
        self._skip_btn.setVisible(False)
        self._later_btn.setText(_("Close"))

    def set_notify_only(self) -> None:
        """Adapt the dialog for notify-only mode."""
        self._update_btn.setVisible(False)
        self._skip_btn.setVisible(False)
        self._later_btn.setText(_("Close"))

    def _action_button_text(self) -> str:
        if self._can_self_update:
            return _("Update Now")
        return _("Download")

    def _on_skip_clicked(self) -> None:
        self.skip_requested.emit(self._info.release.version)
        self.accept()
