# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.history_record import AnnotationRecord
from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class AnnotationDialog(QDialog):
    """Dialog for adding / editing a user note on a history record."""

    def __init__(self, url: str, title: str, existing: AnnotationRecord | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Add Note") if (existing is None or not existing.note) else _("Edit Note"))
        self.setWindowIcon(get_icon("edit-2"))
        self.setMinimumWidth(480)
        self.setMinimumHeight(260)
        self._url = url
        self._build_ui(title, existing)

    def _build_ui(self, title: str, existing: AnnotationRecord | None):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Page info
        info = QWidget()
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("edit-2").pixmap(16, 16))
        info_layout.addWidget(icon_lbl)
        title_lbl = QLabel(f"<b>{title}</b>")
        title_lbl.setWordWrap(True)
        title_lbl.setMaximumWidth(420)
        info_layout.addWidget(title_lbl, 1)
        layout.addWidget(info)

        url_lbl = QLabel(self._url)
        url_lbl.setObjectName("muted")
        url_lbl.setWordWrap(True)
        url_lbl.setMaximumWidth(440)
        layout.addWidget(url_lbl)

        layout.addWidget(QLabel(_("Your note:")))

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(_("Write anything you want to remember about this page…"))
        if existing and existing.note:
            self._editor.setPlainText(existing.note)
        layout.addWidget(self._editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._editor.setFocus()

    def get_note(self) -> str:
        return self._editor.toPlainText()
