# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import tracemalloc

logger = logging.getLogger("HistorySync.memory_tracer")

_state: dict = {"baseline": None}


def start(nframe: int = 25) -> None:
    """Start tracemalloc and record a baseline snapshot."""
    tracemalloc.start(nframe)
    _state["baseline"] = tracemalloc.take_snapshot()
    current, peak = tracemalloc.get_traced_memory()
    logger.info(
        "tracemalloc started (nframe=%d) — baseline: current=%.1f MB, peak=%.1f MB", nframe, current / 1e6, peak / 1e6
    )


def dump_snapshot(top_n: int = 20, compare_to_baseline: bool = True) -> None:
    """Log the top memory consumers to the app logger."""
    if not tracemalloc.is_tracing():
        logger.warning("dump_snapshot called but tracemalloc is not running")
        return

    snap = tracemalloc.take_snapshot()
    current, peak = tracemalloc.get_traced_memory()

    if compare_to_baseline and _state["baseline"] is not None:
        stats = snap.compare_to(_state["baseline"], "lineno")
        label = "diff vs baseline"
    else:
        stats = snap.statistics("lineno")
        label = "absolute"

    logger.info(
        "=== Memory snapshot (%s) | current=%.1f MB peak=%.1f MB | top %d ===",
        label,
        current / 1e6,
        peak / 1e6,
        top_n,
    )
    for i, stat in enumerate(stats[:top_n], 1):
        logger.info("  [%2d] %s", i, stat)


def schedule_periodic_dump(interval_s: int = 60) -> None:
    """
    Set up a QTimer to call dump_snapshot() every *interval_s* seconds.
    Must be called after QApplication is created.
    """
    try:
        from PySide6.QtCore import QTimer
    except ImportError:
        logger.warning("PySide6 not available — periodic memory dump disabled")
        return

    timer = QTimer()
    timer.setInterval(interval_s * 1000)
    timer.timeout.connect(dump_snapshot)
    timer.start()
    # Keep a module-level reference so the timer is not garbage-collected.
    _periodic_timer.append(timer)
    logger.info("Periodic memory dump scheduled every %d s", interval_s)


# Holds the QTimer reference to prevent GC.
_periodic_timer: list = []
