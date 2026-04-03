# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

if sys.platform == "win32":
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _VK_H = 0x48
    _WM_HOTKEY = 0x0312
    _HOTKEY_ID = 0xBEEF  # arbitrary unique ID

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("message", ctypes.c_uint),
            ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_ssize_t),
            ("time", ctypes.c_ulong),
            ("pt", ctypes.c_long * 2),
        ]


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers Ctrl+Shift+H as a system-wide hotkey (Windows only).

    On other platforms register()/unregister() are no-ops and triggered
    is never emitted.  The caller should still install this as a native
    event filter on Windows so WM_HOTKEY messages are intercepted.
    """

    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._registered = False

    def register(self) -> bool:
        """Register the hotkey. Returns True on success."""
        if sys.platform != "win32" or self._registered:
            return False
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, _HOTKEY_ID, _MOD_CONTROL | _MOD_SHIFT, _VK_H))
        self._registered = ok
        return ok

    def unregister(self) -> None:
        """Unregister the hotkey."""
        if sys.platform != "win32" or not self._registered:
            return
        ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
        self._registered = False

    def nativeEventFilter(self, eventType: bytes, message: object) -> tuple[bool, int]:
        if sys.platform != "win32":
            return False, 0
        if eventType == b"windows_generic_MSG":
            # PySide6: message may be int or shiboken2.VoidPtr depending on version
            addr = message if isinstance(message, int) else message.__int__()
            msg = _MSG.from_address(addr)
            if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                self.triggered.emit()
                return True, 0
        return False, 0
