# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget


def _clamp_dialog_frame(geo, center=None):
    if center is not None:
        geo.moveCenter(center)

    target_screen = QApplication.screenAt(geo.center())
    if target_screen is None:
        target_screen = QApplication.primaryScreen()
    if target_screen is None:
        return geo

    avail = target_screen.availableGeometry()
    geo.moveLeft(max(avail.left(), min(geo.left(), avail.right() - geo.width())))
    geo.moveTop(max(avail.top(), min(geo.top(), avail.bottom() - geo.height())))
    return geo


def exec_centered(dlg: QDialog, parent: QWidget | None = None) -> int:
    """Show a QDialog centered without the top-left flash on first open.

    Qt's adjustPosition() skips auto-centering when WA_Moved is set.
    We call adjustSize() to compute the correct size without showing the
    window, then move() to the target position (which sets WA_Moved=True),
    so exec() places the window directly at the right coordinates.

    The final position is clamped to the screen's available geometry so the
    dialog never overflows when the parent is near a display edge.
    """
    # Ensure the dialog is hidden before positioning to avoid any visual glitch.
    # Some Qt versions may briefly show the window at (0, 0) during geometry
    # calculation even before exec() is called.
    if not dlg.isHidden():
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

    # Force native window creation so frameGeometry() reflects the real
    # decorated frame size (title bar + borders).  Without this,
    # frameGeometry() returns the content rect for never-shown dialogs,
    # causing the clamping below to under-count decoration height.
    # winId() is safe to call even if the window is already native.
    dlg.winId()

    geo = _clamp_dialog_frame(dlg.frameGeometry(), center)
    dlg.move(geo.topLeft())

    # Some Qt styles/platform plugins adjust dialog position again during the
    # show/exec path. Re-clamp on the first event-loop tick using the final
    # decorated frame size to keep the dialog fully on-screen.
    def _reposition_after_show() -> None:
        current_geo = dlg.frameGeometry()
        final_geo = _clamp_dialog_frame(current_geo)
        if final_geo.topLeft() != current_geo.topLeft():
            dlg.move(final_geo.topLeft())

    QTimer.singleShot(0, _reposition_after_show)

    return dlg.exec()
