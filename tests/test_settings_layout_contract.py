# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QSizePolicy

from src.views.settings.font_section import FontSection
from src.views.settings.keybinding_section import KeybindingSection
from src.views.settings.maintenance_section import MaintenanceSection
from src.views.settings.scheduler_section import SchedulerSection
from src.views.settings.security_section import SecuritySection
from src.views.settings.startup_section import StartupSection
from src.views.settings.webdav_section import WebDavSection


def _app() -> QApplication:
    app = QApplication.instance()
    return app or QApplication([])


def test_settings_labels_use_constrained_width_policy() -> None:
    _app()

    webdav = WebDavSection()
    startup = StartupSection()
    scheduler = SchedulerSection()
    security = SecuritySection()
    font = FontSection()
    keybinding = KeybindingSection()
    maintenance = MaintenanceSection()

    labels = [
        webdav._next_backup_lbl,
        webdav._status_lbl,
        webdav._hash_info_lbl,
        startup._status_lbl,
        scheduler._next_sync_lbl,
        security._status_label,
        security._desc_label,
        security._session_label,
        font._status_lbl,
        keybinding._summary_lbl,
        maintenance._log_lbl,
    ]

    for label in labels:
        assert label.wordWrap() is True
        assert label.minimumWidth() == 0
        assert label.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
