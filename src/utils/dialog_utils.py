# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget


def exec_centered(dlg: QDialog, parent: QWidget | None = None) -> int:
    """Show a QDialog centered without the top-left flash on first open.

    Qt's adjustPosition() skips auto-centering when WA_Moved is set.
    We call adjustSize() to compute the correct size without showing the
    window, then move() to the target position (which sets WA_Moved=True),
    so exec() places the window directly at the right coordinates.
    """
    # Ensure the dialog is hidden before positioning to avoid any visual glitch.
    # Some Qt versions may briefly show the window at (0, 0) during geometry
    # calculation even before exec() is called.
    was_hidden = dlg.isHidden()
    if not was_hidden:
        dlg.hide()

    # Skip adjustSize() when the dialog already has an explicit size set via
    # resize() in __init__ (WA_Resized is True). Calling adjustSize() on dialogs
    # that contain a QScrollArea would expand the scroll area to its full content
    # height, making the window abnormally tall.
    if not dlg.testAttribute(Qt.WA_Resized):
        dlg.adjustSize()

    ref = parent or dlg.parentWidget()
    if ref and ref.isVisible():
        center = ref.mapToGlobal(ref.rect().center())
    else:
        screen = QApplication.primaryScreen()
        center = screen.availableGeometry().center()

    geo = dlg.frameGeometry()
    geo.moveCenter(center)
    dlg.move(geo.topLeft())

    return dlg.exec()
