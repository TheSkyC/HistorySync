# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon


class CustomPathsSection(QWidget):
    """Custom browser paths card.

    Signals:
        add_path_requested(browser_type: str, path: str)
        remove_path_requested(browser_type: str)

    Exposes:
        refresh_paths(paths: dict[str, str])
    """

    add_path_requested = Signal(str, str)  # (browser_type, path)
    remove_path_requested = Signal(str)  # browser_type

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        desc = QLabel(
            _(
                "If you use portable or non-standard browser installations, "
                "manually specify the History database path here."
            )
        )
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText(_("Identifier (e.g. chrome_portable)"))
        self._type_input.setFixedWidth(180)

        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText(_("History database file path..."))

        browse_btn = QPushButton(_("Browse..."))
        browse_btn.setIcon(get_icon("folder-open"))
        browse_btn.clicked.connect(self._browse)

        add_btn = QPushButton(_("Add"))
        add_btn.setIcon(get_icon("plus"))
        add_btn.clicked.connect(self._on_add_clicked)

        path_row.addWidget(self._type_input)
        path_row.addWidget(self._path_input, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(add_btn)
        layout.addLayout(path_row)

        self._paths_container = QVBoxLayout()
        self._paths_container.setSpacing(6)
        layout.addLayout(self._paths_container)

    # ── Public API ────────────────────────────────────────────

    def refresh_paths(self, paths: dict[str, str]):
        while self._paths_container.count():
            item = self._paths_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for bt, path in paths.items():
            row = QHBoxLayout()
            lbl = QLabel(f"<b>{bt}</b>　{path}")
            lbl.setObjectName("muted")
            lbl.setWordWrap(True)
            del_btn = QPushButton(_("Delete"))
            del_btn.setObjectName("danger_btn")
            del_btn.setIcon(get_icon("trash"))
            del_btn.clicked.connect(lambda _, k=bt: self.remove_path_requested.emit(k))
            row.addWidget(lbl, 1)
            row.addWidget(del_btn)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self._paths_container.addWidget(wrapper)

    # ── Internal ──────────────────────────────────────────────

    def _browse(self):
        path, __ = QFileDialog.getOpenFileName(
            self,
            _("Select History Database File"),
            str(Path.home()),
            _("SQLite Database (History *.sqlite *.db);;All Files (*)"),
        )
        if path:
            self._path_input.setText(path)

    def _on_add_clicked(self):
        bt = self._type_input.text().strip()
        path = self._path_input.text().strip()
        if bt and path:
            self.add_path_requested.emit(bt, path)
            self._type_input.clear()
            self._path_input.clear()
