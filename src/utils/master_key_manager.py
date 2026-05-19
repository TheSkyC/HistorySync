# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import threading
import time

from src.utils.logger import get_logger

log = get_logger("utils.master_key_manager")

SESSION_TIMEOUT_S = 1800
PBKDF2_ITERATIONS = 600_000


class MasterPasswordSession:
    """Singleton session object that tracks whether the user has authenticated."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unlocked: bool = False
        self._last_activity: float = 0.0
        self._observers: list = []

    def add_observer(self, cb) -> None:
        if cb not in self._observers:
            self._observers.append(cb)

    def remove_observer(self, cb) -> None:
        try:
            self._observers.remove(cb)
        except ValueError:
            pass

    def _notify(self) -> None:
        for cb in list(self._observers):
            try:
                cb()
            except Exception:
                pass

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def is_unlocked(self) -> bool:
        with self._lock:
            # Use time.time() (wall-clock) so that system sleep/hibernate is
            # counted toward the idle timeout. time.monotonic() freezes during
            # sleep, which would allow the session to persist indefinitely while
            # the device is locked/sleeping.
            if self._unlocked and (time.time() - self._last_activity) > SESSION_TIMEOUT_S:
                self._unlocked = False
                log.info("Master password session expired (idle timeout)")
            return self._unlocked

    def unlock(self) -> None:
        with self._lock:
            self._unlocked = True
            self._last_activity = time.time()
        log.info("Master password session unlocked")
        self._notify()

    def lock(self) -> None:
        with self._lock:
            self._unlocked = False
        log.info("Master password session locked")
        self._notify()

    def touch(self) -> None:
        """Extend the session on any protected activity."""
        with self._lock:
            if self._unlocked:
                self._last_activity = time.time()


_state: dict[str, MasterPasswordSession | None] = {"session": None}


def get_session() -> MasterPasswordSession:
    if _state["session"] is None:
        _state["session"] = MasterPasswordSession()
    return _state["session"]  # type: ignore[return-value]


# ── Password hashing helpers ──────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a PBKDF2-HMAC-SHA256 hash of *password*.

    Format: ``PBKDF2:<iterations>:<salt_hex>:<dk_hex>``
    The iteration count is embedded so future bumps remain backward-compatible.
    """
    if not password:
        return ""
    import os

    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"PBKDF2:{PBKDF2_ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True if *password* matches *stored_hash*.

    Handles three formats for backward compatibility:
    - ``PBKDF2:<iterations>:<salt_hex>:<dk_hex>``  (current)
    - ``PBKDF2:<salt_hex>:<dk_hex>``               (legacy, assumed 200 000 iterations)
    - Any other prefix (e.g. old bcrypt hashes)    (returns False)
    """
    if not password or not stored_hash:
        return False
    try:
        if stored_hash.startswith("PBKDF2:"):
            parts = stored_hash.split(":")
            if len(parts) == 4:
                # Current format: PBKDF2:<iterations>:<salt_hex>:<dk_hex>
                _, iterations_str, salt_hex, dk_hex = parts
                iterations = int(iterations_str)
            elif len(parts) == 3:
                # Legacy format: PBKDF2:<salt_hex>:<dk_hex> (200 000 iterations)
                _, salt_hex, dk_hex = parts
                iterations = 200_000
            else:
                return False
            salt = bytes.fromhex(salt_hex)
            dk_expected = bytes.fromhex(dk_hex)
            dk_actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(dk_actual, dk_expected)
    except Exception as exc:
        log.warning("Password verification error: %s", exc)
    return False
