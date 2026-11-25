# Copyright (c) 2026, HistorySync contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.services.backup_archive import export_zip, import_zip
from src.services.github_backup import github_backup
from src.utils.i18n import _


class _BackupJob(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.error = ""

    def run(self):
        try:
            self.operation()
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


class BackupDialog(QDialog):
    merged = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._job = None
        self.setWindowTitle(_("Portable backups"))
        layout = QVBoxLayout(self)
        self._local = QGroupBox(_("Local ZIP"))
        row = QHBoxLayout(self._local)
        for text, operation in ((_("Export ZIP…"), self._export), (_("Import and merge ZIP…"), self._import)):
            button = QPushButton(text)
            button.clicked.connect(operation)
            row.addWidget(button)
        layout.addWidget(self._local)

        self._github = QGroupBox(_("Private GitHub repository"))
        form = QFormLayout(self._github)
        self._repo = QLineEdit()
        self._repo.setPlaceholderText("owner/repository")
        form.addRow(_("Repository"), self._repo)
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Access token"), self._token)
        hint = QLabel(_("Use a token with Contents access to this repository. Uploads update HistorySync/history.zip."))
        hint.setWordWrap(True)
        form.addRow(hint)
        row = QHBoxLayout()
        for text, restore in ((_("Upload backup"), False), (_("Download and merge"), True)):
            button = QPushButton(text)
            button.clicked.connect(partial(self._remote, restore))
            row.addWidget(button)
        form.addRow(row)
        layout.addWidget(self._github)
        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._close.rejected.connect(self.reject)
        layout.addWidget(self._close)

    def _export(self):
        name, _filter = QFileDialog.getSaveFileName(self, _("Export ZIP"), "history.zip", "ZIP (*.zip)")
        if name:
            self._start(partial(export_zip, self._db, Path(name)), _("ZIP exported."))

    def _import(self):
        name, _filter = QFileDialog.getOpenFileName(self, _("Import and merge ZIP"), "", "ZIP (*.zip)")
        if name:
            self._start(partial(import_zip, self._db, Path(name)), _("Backup merged."), merging=True)

    def _remote(self, restore):
        self._start(
            partial(github_backup, self._db, self._repo.text().strip(), self._token.text(), restore=restore),
            _("Backup merged.") if restore else _("Backup uploaded."),
            merging=restore,
        )

    def _start(self, operation, success_message, *, merging=False):
        self._success_message = success_message
        self._merging = merging
        self._job = _BackupJob(operation, self)
        self._job.finished.connect(self._finished)
        self._set_busy(True)
        self._status.setText(_("Working…"))
        self._job.start()

    def _finished(self):
        self._status.setText(self._job.error or self._success_message)
        if self._merging and not self._job.error:
            self.merged.emit()
        self._job.deleteLater()
        self._job = None
        self._set_busy(False)

    def _set_busy(self, busy):
        for widget in (self._local, self._github, self._close):
            widget.setEnabled(not busy)

    def reject(self):
        if self._job is None:
            super().reject()
