# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class ImportSection(QWidget):
    """Import history database card.

    Signals:
        import_requested()  - user clicked the import button
    """

    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        desc = QLabel(
            _(
                "Import browser history from a standalone database file — for example, "
                "a manually backed-up Chrome History file, a Firefox places.sqlite, "
                "a Safari History.db, or an older HistorySync backup."
            )
        )
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        import_btn = QPushButton(_("Import History File..."))
        import_btn.setIcon(get_icon("upload"))
        import_btn.setStyleSheet(
            "QPushButton { background-color: #5b9cf6; color: white; font-weight: bold; "
            "border-radius: 5px; padding: 6px 18px; } "
            "QPushButton:hover { background-color: #4a8be0; }"
        )
        import_btn.clicked.connect(self.import_requested)
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
