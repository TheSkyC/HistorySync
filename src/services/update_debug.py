# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Debug overrides for the online-update system, driven by environment variables.

This module provides a small, zero-magic set of overrides so developers can
exercise every branch of the update logic — auto-check gating, rollout, skipped
versions, repeated notifications, metadata fetching — without editing source
constants or hand-patching ``config.json``.

**Environment variables**

.. list-table::
   :header-rows: 1

   * - Variable
     - Purpose
     - Valid values
   * - ``HISTORYSYNC_UPDATE_CURRENT_VERSION``
     - Override the running version sent to the update API.  Set it lower than
       the current release to simulate an "update available" result.
     - A valid semver string, e.g. ``"1.0.0"``, ``"0.9.5-beta"``.
   * - ``HISTORYSYNC_UPDATE_API_BASE_URL``
     - Redirect dl metadata API calls to a local mock server (or staging).
     - A well-formed ``http://`` or ``https://`` URL.
   * - ``HISTORYSYNC_UPDATE_FORCE_AUTO``
     - Allow automatic background update checks in source-checkout mode
       (normally restricted to frozen builds).
     - ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (case-insensitive).
   * - ``HISTORYSYNC_UPDATE_IGNORE_GATES``
     - Ignore rollout percentage, skipped-version, and repeat-notification
       dedup so *every* check surfaces an update when one exists.
     - ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (case-insensitive).

All four overrides are **opt-in** — when the environment variable is absent or
empty the production codepath is unchanged.  Invalid values are logged as
warnings and treated as "not set", never raised.

**Typical debug session**::

    $env:HISTORYSYNC_UPDATE_CURRENT_VERSION="1.0.0"
    $env:HISTORYSYNC_UPDATE_FORCE_AUTO="1"
    $env:HISTORYSYNC_UPDATE_IGNORE_GATES="1"
    & ".venv/Scripts/python.exe" src/main.py
"""

from __future__ import annotations

from collections.abc import Callable
import os
import re

from src.utils.logger import get_logger

log = get_logger("update.debug")

# ── Sentinel ─────────────────────────────────────────────────────────────────

_UNSET: object = object()


# ── Cached values ────────────────────────────────────────────────────────────

_current_version_override: object = _UNSET
_api_base_url_override: object = _UNSET
_force_auto_override: object = _UNSET
_ignore_gates_override: object = _UNSET


# ── Helpers ──────────────────────────────────────────────────────────────────


def _is_truthy(value: str) -> bool:
    """Return True when *value* is a common truthy env-var string."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_env(name: str) -> str | None:
    """Read *name* from the environment, stripping surrounding whitespace.

    Returns ``None`` when the variable is absent or empty, matching the
    principle that an unset / blank override means "use production default".
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


# ── Validators ───────────────────────────────────────────────────────────────

# Loose semver-ish check: digit(s), optional .digit(s), optional .digit(s),
# optional pre-release suffix.  This is intentionally more permissive than
# ``Version.parse`` so that a typo (e.g. ``1.0``) still maps cleanly to a
# valid ``Version``.
_VERSION_LOOSE_RE = re.compile(r"^[vV]?\d+(?:\.\d+)?(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?$")


def _validate_version(value: str) -> str | None:
    """Return *value* if it looks like a version, or ``None`` with a warning."""
    if _VERSION_LOOSE_RE.match(value):
        return value
    log.warning(
        "HISTORYSYNC_UPDATE_CURRENT_VERSION=%r is not a valid semver string; ignored",
        value,
    )
    return None


_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _validate_url(value: str) -> str | None:
    """Return *value* if it looks like an HTTP(S) URL, or ``None`` with a warning."""
    if _URL_RE.match(value):
        # Strip trailing slashes so callers don't double up.
        return value.rstrip("/")
    log.warning(
        "HISTORYSYNC_UPDATE_API_BASE_URL=%r is not a valid HTTP(S) URL; ignored",
        value,
    )
    return None


# ── Public accessors ─────────────────────────────────────────────────────────


def current_version() -> str | None:
    """Return the debug current-version override, or ``None`` if not set."""
    global _current_version_override
    if _current_version_override is _UNSET:
        raw = _resolve_env_testable("HISTORYSYNC_UPDATE_CURRENT_VERSION")
        _current_version_override = _validate_version(raw) if raw is not None else None
        if _current_version_override is not None:
            log.info("Debug override: current_version = %r", _current_version_override)
    return _current_version_override  # type: ignore[return-value]


def api_base_url() -> str | None:
    """Return the debug api-base-url override, or ``None`` if not set."""
    global _api_base_url_override
    if _api_base_url_override is _UNSET:
        raw = _resolve_env_testable("HISTORYSYNC_UPDATE_API_BASE_URL")
        _api_base_url_override = _validate_url(raw) if raw is not None else None
        if _api_base_url_override is not None:
            log.info("Debug override: api_base_url = %r", _api_base_url_override)
    return _api_base_url_override  # type: ignore[return-value]


def force_auto() -> bool:
    """Return True when auto-check should run even in a source checkout."""
    global _force_auto_override
    if _force_auto_override is _UNSET:
        raw = _resolve_env_testable("HISTORYSYNC_UPDATE_FORCE_AUTO")
        _force_auto_override = _is_truthy(raw) if raw is not None else False
        if _force_auto_override:
            log.info("Debug override: force_auto = True (auto-check in source mode)")
    return _force_auto_override  # type: ignore[return-value]


def ignore_gates() -> bool:
    """Return True when rollout/skip/dedup gates should be bypassed."""
    global _ignore_gates_override
    if _ignore_gates_override is _UNSET:
        raw = _resolve_env_testable("HISTORYSYNC_UPDATE_IGNORE_GATES")
        _ignore_gates_override = _is_truthy(raw) if raw is not None else False
        if _ignore_gates_override:
            log.info("Debug override: ignore_gates = True (bypass rollout/skip/dedup)")
    return _ignore_gates_override  # type: ignore[return-value]


def any_active() -> bool:
    """Return True when *any* update debug override is active."""
    return current_version() is not None or api_base_url() is not None or force_auto() or ignore_gates()


def effective_current_version() -> str:
    """Return the effective current version for display/logging purposes.

    When ``HISTORYSYNC_UPDATE_CURRENT_VERSION`` is set, returns the debug
    override so the UI shows a consistent version string.  Otherwise falls
    back to :data:`src.utils.constants.APP_VERSION`.
    """
    debug = current_version()
    if debug is not None:
        return debug
    from src.utils.constants import APP_VERSION

    return APP_VERSION


# ── Test support ─────────────────────────────────────────────────────────────

# Hooks that tests can replace to inject values without touching the real
# environment.  They are called *instead of* ``_resolve_env`` when set.
_test_injectors: dict[str, Callable[[], str | None]] = {}


def _resolve_env_testable(name: str) -> str | None:
    """Resolve *name* allowing a test injector to take priority."""
    injector = _test_injectors.get(name)
    if injector is not None:
        return injector()
    return _resolve_env(name)


def reset_for_testing() -> None:
    """Clear all cached override values and test injectors.

    Call this in test ``setup_function`` / ``teardown_function`` fixtures
    so each test starts from a clean slate.
    """
    global _current_version_override, _api_base_url_override
    global _force_auto_override, _ignore_gates_override
    _current_version_override = _UNSET
    _api_base_url_override = _UNSET
    _force_auto_override = _UNSET
    _ignore_gates_override = _UNSET
    _test_injectors.clear()


def set_test_injector(name: str, fn: Callable[[], str | None]) -> None:
    """Register a test injector for *name* (e.g. ``"HISTORYSYNC_UPDATE_CURRENT_VERSION"``).

    The callable will be invoked every time the corresponding accessor needs to
    resolve the environment.  Pass ``None`` as *fn* to remove the injector.
    """
    if fn is None:
        _test_injectors.pop(name, None)
    else:
        _test_injectors[name] = fn
