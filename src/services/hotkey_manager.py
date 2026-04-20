# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import sys
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

try:
    from pynput import keyboard as _kb

    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


def _is_wayland() -> bool:
    """Return True when running under Wayland (Linux only)."""
    if sys.platform != "linux":
        return False
    import os

    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")


class HotkeyManager(QObject):
    """Cross-platform global hotkey manager backed by pynput.

    Supported platforms:
      - Windows  : pynput wraps Win32 RegisterHotKey
      - macOS    : pynput wraps CGEventTap (requires Accessibility permission)
      - Linux/X11: pynput wraps XGrabKey
      - Linux/Wayland: not supported by pynput; register() returns False and
                       logs a hint to use the --quick CLI flag instead.

    The listener runs in a daemon thread managed by pynput.  When the hotkey
    fires, ``triggered`` is emitted from that thread via a direct connection -
    Qt will marshal it to the main thread automatically because the signal is
    defined on a QObject that lives in the main thread.
    """

    triggered = Signal()
    registration_failed = Signal(str)  # emits a human-readable reason

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener: object | None = None  # pynput GlobalHotKeys instance
        self._hotkey: str = "<ctrl>+<shift>+h"
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_registered(self) -> bool:
        with self._lock:
            return self._listener is not None

    def register(self, hotkey: str = "<ctrl>+<shift>+h") -> bool:
        """Start listening for *hotkey*.  Returns True on success.

        Safe to call multiple times; re-registers if the hotkey string changed.
        """
        with self._lock:
            if self._listener is not None:
                if self._hotkey == hotkey:
                    return True
                self._stop_listener()

            if not _PYNPUT_AVAILABLE:
                reason = "pynput is not installed - run: pip install pynput"
                log.warning("Global hotkey unavailable: %s", reason)
                self.registration_failed.emit(reason)
                return False

            if _is_wayland():
                reason = (
                    "Wayland does not support global hotkeys via pynput. "
                    "Bind 'python -m src.main --quick' to a system shortcut instead."
                )
                log.warning("Global hotkey unavailable: %s", reason)
                self.registration_failed.emit(reason)
                return False

            try:
                listener = _kb.GlobalHotKeys({hotkey: self._on_hotkey})
                listener.daemon = True
                listener.start()
                self._listener = listener
                self._hotkey = hotkey
                log.debug("Global hotkey registered: %s", hotkey)
                return True
            except Exception as exc:
                reason = str(exc)
                log.warning("Failed to register global hotkey %s: %s", hotkey, reason)
                self.registration_failed.emit(reason)
                return False

    def unregister(self) -> None:
        """Stop the hotkey listener."""
        with self._lock:
            self._stop_listener()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _stop_listener(self) -> None:
        """Must be called with self._lock held."""
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
            log.debug("Global hotkey unregistered: %s", self._hotkey)

    def _on_hotkey(self) -> None:
        self.triggered.emit()
