# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.utils.i18n_core import (  # noqa: F401
    N_,
    LanguageManager,
    _,
    lang_manager,
)

# ── Qt Signal bridge ──────────────────────────────────────────────────────────


class _QtLanguageSignalBridge(QObject):
    language_changed = Signal()


_bridge = _QtLanguageSignalBridge()
lang_manager.language_changed = _bridge.language_changed  # type: ignore[assignment]
