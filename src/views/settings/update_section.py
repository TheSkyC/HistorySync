# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Settings card for online-update preferences.

The main section shows only the essentials: current version, a "Check for
Updates" button, and a status label.  All other preferences (auto-check,
policy, mirror, channel) live in a sub-dialog opened via "Preferences…".
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.services.update_debug import effective_current_version
from src.utils.constants import (
    UPDATE_CHANNELS,
    UPDATE_MIRROR_MODES,
    UPDATE_POLICIES,
    UPDATE_POLICY_AUTO_INSTALL,
    UPDATE_POLICY_NOTIFY_DOWNLOAD,
    UPDATE_POLICY_NOTIFY_ONLY,
)
from src.utils.dialog_utils import exec_centered
from src.utils.i18n import N_, _
from src.utils.icon_helper import get_icon
from src.utils.styled_combobox import StyledComboBox
from src.views.settings._label_utils import constrain_label_width

# Display labels for update policies.
_POLICY_LABELS: dict[str, str] = {
    UPDATE_POLICY_NOTIFY_ONLY: N_("Notify only"),
    UPDATE_POLICY_NOTIFY_DOWNLOAD: N_("Download and prompt to install"),
    UPDATE_POLICY_AUTO_INSTALL: N_("Auto-install on quit"),
}

_MIRROR_LABELS: dict[str, str] = {
    "auto": N_("Auto"),
    "on": N_("Always prefer mirror"),
    "off": N_("Always use direct source"),
}

_CHANNEL_LABELS: dict[str, str] = {
    "stable": N_("Stable"),
    "beta": N_("Beta"),
    "nightly": N_("Nightly"),
}

_REMINDER_LABELS: dict[str, str] = {
    "always": N_("Every time"),
    "weekly": N_("At most once per week"),
    "never": N_("Never show automatic banners"),
}


# ── Preferences dialog ────────────────────────────────────────────────────────


class UpdatePreferencesDialog(QDialog):
    """Sub-dialog for update preferences and reminder behavior."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._can_self_update = True
        self._reset_skip_requested = False
        self.setWindowTitle(_("Update Preferences"))
        self.setMinimumWidth(440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Auto-check toggle ─────────────────────────────────
        self._auto_check_cb = QCheckBox(_("Automatically check for updates"))
        layout.addWidget(self._auto_check_cb)

        # ── Update policy ─────────────────────────────────────
        policy_row = QHBoxLayout()
        policy_lbl = QLabel(_("When an update is available:"))
        policy_lbl.setObjectName("muted")
        self._policy_combo = StyledComboBox()
        self._policy_combo.setMinimumWidth(260)
        self._populate_policy_combo()
        policy_row.addWidget(policy_lbl)
        policy_row.addWidget(self._policy_combo)
        policy_row.addStretch()
        layout.addLayout(policy_row)

        # ── Mirror preference ─────────────────────────────────
        mirror_row = QHBoxLayout()
        mirror_lbl = QLabel(_("Download source:"))
        mirror_lbl.setObjectName("muted")
        self._mirror_combo = StyledComboBox()
        self._mirror_combo.setMinimumWidth(240)
        for key in UPDATE_MIRROR_MODES:
            self._mirror_combo.addItem(_(_MIRROR_LABELS[key]), key)
        mirror_row.addWidget(mirror_lbl)
        mirror_row.addWidget(self._mirror_combo)
        mirror_row.addStretch()
        layout.addLayout(mirror_row)

        # ── Channel ───────────────────────────────────────────
        ch_row = QHBoxLayout()
        ch_lbl = QLabel(_("Update channel:"))
        ch_lbl.setObjectName("muted")
        self._channel_combo = StyledComboBox()
        self._channel_combo.setMinimumWidth(240)
        for key in UPDATE_CHANNELS:
            self._channel_combo.addItem(_(_CHANNEL_LABELS[key]), key)
        ch_row.addWidget(ch_lbl)
        ch_row.addWidget(self._channel_combo)
        ch_row.addStretch()
        layout.addLayout(ch_row)

        # ── Button box ────────────────────────────────────────
        reminder_row = QHBoxLayout()
        reminder_lbl = QLabel(_("Automatic banner reminders:"))
        reminder_lbl.setObjectName("muted")
        self._reminder_combo = StyledComboBox()
        self._reminder_combo.setMinimumWidth(260)
        for key in ("always", "weekly", "never"):
            self._reminder_combo.addItem(_(_REMINDER_LABELS[key]), key)
        reminder_row.addWidget(reminder_lbl)
        reminder_row.addWidget(self._reminder_combo)
        reminder_row.addStretch()
        layout.addLayout(reminder_row)

        self._reset_skip_btn = QPushButton(_("Remind me again for skipped versions"))
        self._reset_skip_btn.setMinimumHeight(30)
        self._reset_skip_btn.clicked.connect(self._reset_skip_version)
        layout.addWidget(self._reset_skip_btn, 0, Qt.AlignLeft)

        layout.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # ── Public API ────────────────────────────────────────────

    def load(self, updater) -> None:
        self._auto_check_cb.setChecked(updater.auto_check_enabled)
        self._set_combo_data(
            self._policy_combo,
            updater.policy,
            UPDATE_POLICY_NOTIFY_DOWNLOAD,
        )
        self._set_combo_data(self._mirror_combo, updater.prefer_mirror, "auto")
        self._set_combo_data(self._channel_combo, updater.channel, "stable")
        self._set_combo_data(self._reminder_combo, getattr(updater, "reminder_frequency", "always"), "always")
        self._reset_skip_requested = False
        skipped_version = getattr(updater, "skipped_version", "")
        self._reset_skip_btn.setEnabled(bool(skipped_version))
        self._reset_skip_btn.setText(_("Remind me again for skipped versions"))

    def get_auto_check_enabled(self) -> bool:
        return self._auto_check_cb.isChecked()

    def get_channel(self) -> str:
        return self._channel_combo.currentData() or "stable"

    def get_policy(self) -> str:
        return self._policy_combo.currentData() or UPDATE_POLICY_NOTIFY_DOWNLOAD

    def get_prefer_mirror(self) -> str:
        return self._mirror_combo.currentData() or "auto"

    def get_reminder_frequency(self) -> str:
        return self._reminder_combo.currentData() or "always"

    def should_reset_skip_version(self) -> bool:
        return self._reset_skip_requested

    def set_can_self_update(self, can: bool) -> None:
        """Keep all policies visible but disable auto-install when unavailable."""
        self._can_self_update = can
        self._populate_policy_combo(preferred_policy=self.get_policy())

    def _reset_skip_version(self) -> None:
        self._reset_skip_requested = True
        self._reset_skip_btn.setEnabled(False)
        self._reset_skip_btn.setText(_("Skipped-version reminder will be restored"))

    def _populate_policy_combo(self, preferred_policy: str | None = None) -> None:
        policy = preferred_policy or self._policy_combo.currentData()
        self._policy_combo.clear()
        for key in UPDATE_POLICIES:
            self._policy_combo.addItem(_(_POLICY_LABELS[key]), key)
        auto_install_index = self._policy_combo.findData(UPDATE_POLICY_AUTO_INSTALL)
        if auto_install_index >= 0:
            self._policy_combo.setItemEnabled(auto_install_index, self._can_self_update)
        if policy == UPDATE_POLICY_AUTO_INSTALL and not self._can_self_update:
            policy = UPDATE_POLICY_NOTIFY_DOWNLOAD
        self._set_combo_data(self._policy_combo, policy, UPDATE_POLICY_NOTIFY_DOWNLOAD)

    @staticmethod
    def _set_combo_data(combo: StyledComboBox, value, fallback) -> None:
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findData(fallback)
        if idx >= 0:
            combo.setCurrentIndex(idx)


# ── Main section (compact card) ───────────────────────────────────────────────


class UpdateSection(QWidget):
    """Compact settings card for the Settings page.

    Shows current version, a "Check for Updates" button, and a
    "Preferences…" button that opens the detailed preferences dialog.

    Exposes:
        load(cfg)                       - populate from AppConfig
        get_auto_check_enabled() -> bool
        get_channel() -> str
        get_policy() -> str
        get_prefer_mirror() -> str
        check_now_requested signal      - "Check for updates" clicked
    """

    check_now_requested = Signal()
    preferences_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_check_enabled = True
        self._channel = "stable"
        self._policy = UPDATE_POLICY_NOTIFY_DOWNLOAD
        self._prefer_mirror = "auto"
        self._reminder_frequency = "always"
        self._skipped_version = ""
        self._reset_skip_requested = False
        self._can_self_update = True

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 0, 20, 0)

        # ── Top row: version + preferences button ─────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        ver_lbl = QLabel(_("Current version: {version}").format(version=effective_current_version()))
        ver_lbl.setObjectName("muted")
        top_row.addWidget(ver_lbl)
        top_row.addStretch()

        self._prefs_btn = QPushButton(_("Preferences\u2026"))
        self._prefs_btn.setMinimumHeight(30)
        self._prefs_btn.setMinimumWidth(120)
        self._prefs_btn.clicked.connect(self._open_preferences)
        top_row.addWidget(self._prefs_btn)

        layout.addLayout(top_row)

        # ── Action row: check button + status ─────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._check_btn = QPushButton(_("Check for Updates"))
        self._check_btn.setIcon(get_icon("refresh-ccw", 14))
        self._check_btn.setMinimumHeight(32)
        self._check_btn.clicked.connect(self.check_now_requested)
        action_row.addWidget(self._check_btn)

        self._status_lbl = constrain_label_width(QLabel(""))
        self._status_lbl.setObjectName("muted")
        action_row.addWidget(self._status_lbl, 1)
        action_row.addStretch()

        layout.addLayout(action_row)

    # ── Public API ────────────────────────────────────────────

    def load(self, cfg) -> None:
        updater = cfg.updater
        self._auto_check_enabled = updater.auto_check_enabled
        self._policy = updater.policy or UPDATE_POLICY_NOTIFY_DOWNLOAD
        self._prefer_mirror = updater.prefer_mirror or "auto"
        self._channel = updater.channel or "stable"
        self._reminder_frequency = getattr(updater, "reminder_frequency", "always") or "always"
        self._skipped_version = getattr(updater, "skipped_version", "") or ""
        self._reset_skip_requested = False
        self._update_last_check_label(updater.last_check_ts)

    def get_auto_check_enabled(self) -> bool:
        return self._auto_check_enabled

    def get_channel(self) -> str:
        return self._channel

    def get_policy(self) -> str:
        return self._policy

    def get_prefer_mirror(self) -> str:
        return self._prefer_mirror

    def get_reminder_frequency(self) -> str:
        return self._reminder_frequency

    def should_reset_skip_version(self) -> bool:
        return self._reset_skip_requested

    def set_checking(self, checking: bool) -> None:
        self._check_btn.setEnabled(not checking)
        if checking:
            self._check_btn.setText(_("Checking..."))
            self._status_lbl.setText("")
        else:
            self._check_btn.setText(_("Check for Updates"))

    def set_status(self, text: str, level: str = "") -> None:
        color_map = {"success": "#4caf50", "warning": "#ff9800", "error": "#f44336"}
        self._status_lbl.setText(text)
        color = color_map.get(level, "")
        new_ss = f"color: {color};" if color else ""
        if self._status_lbl.styleSheet() != new_ss:
            self._status_lbl.setStyleSheet(new_ss)

    def set_can_self_update(self, can: bool) -> None:
        self._can_self_update = can

    # ── Internal ──────────────────────────────────────────────

    def _open_preferences(self) -> bool:
        dlg = UpdatePreferencesDialog(parent=self)

        # Populate dialog from current state
        class _FakeUpdater:
            pass

        updater = _FakeUpdater()
        updater.auto_check_enabled = self._auto_check_enabled
        updater.policy = self._policy
        updater.prefer_mirror = self._prefer_mirror
        updater.channel = self._channel
        updater.reminder_frequency = self._reminder_frequency
        updater.skipped_version = self._skipped_version
        dlg.load(updater)
        dlg.set_can_self_update(self._can_self_update)

        if exec_centered(dlg, self) == QDialog.Accepted:
            self._auto_check_enabled = dlg.get_auto_check_enabled()
            self._channel = dlg.get_channel()
            self._policy = dlg.get_policy()
            self._prefer_mirror = dlg.get_prefer_mirror()
            self._reminder_frequency = dlg.get_reminder_frequency()
            self._reset_skip_requested = dlg.should_reset_skip_version()
            if self._reset_skip_requested:
                self._skipped_version = ""
            self.preferences_changed.emit()
            return True
        return False

    def open_preferences(self) -> bool:
        """Open the detailed update-preferences dialog programmatically."""
        return self._open_preferences()

    def _update_last_check_label(self, ts: int) -> None:
        if not ts:
            self._status_lbl.setText(_("Never checked"))
            return
        elapsed = int(time.time()) - ts
        if elapsed < 60:
            text = _("Last checked: just now")
        elif elapsed < 3600:
            text = _("Last checked: {n} min ago").format(n=elapsed // 60)
        elif elapsed < 86400:
            text = _("Last checked: {n} hours ago").format(n=elapsed // 3600)
        else:
            text = _("Last checked: {n} days ago").format(n=elapsed // 86400)
        self._status_lbl.setText(text)
