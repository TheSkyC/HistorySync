# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from src.utils.i18n import _


def fmt_countdown(delta: int) -> str | None:
    """Format a countdown *delta* in seconds to a human-friendly string.

    Returns ``None`` when the delta is <= 0 (caller should show "due soon").

    Examples::

        fmt_countdown(3725)  -> "1h 2m"
        fmt_countdown(45)    -> "45s"
        fmt_countdown(-1)    -> None
    """
    if delta <= 0:
        return None
    if delta < 60:
        return _("{s}s").format(s=delta)
    if delta < 3600:
        m, s = divmod(delta, 60)
        return _("{m}m {s}s").format(m=m, s=s)
    if delta < 86400:
        h, rem = divmod(delta, 3600)
        m = rem // 60
        return _("{h}h {m}m").format(h=h, m=m)
    d, rem = divmod(delta, 86400)
    h = rem // 3600
    return _("{d}d {h}h").format(d=d, h=h)


def compute_next_sync_ts(cfg, last_sync_ts: int | None) -> int | None:
    """Return the Unix timestamp of the next scheduled sync, or None."""
    if last_sync_ts and cfg.scheduler.auto_sync_enabled:
        return last_sync_ts + cfg.scheduler.sync_interval_hours * 3600
    return None


def compute_next_backup_ts(cfg) -> int | None:
    import time as _time

    if not (cfg.scheduler.auto_backup_enabled and cfg.webdav.enabled):
        return None
    last_backup = cfg.last_backup_ts if cfg.last_backup_ts > 0 else int(_time.time())
    return last_backup + cfg.scheduler.auto_backup_interval_hours * 3600
