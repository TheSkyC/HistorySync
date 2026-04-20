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
            if self._unlocked and (time.monotonic() - self._last_activity) > SESSION_TIMEOUT_S:
                self._unlocked = False
                log.info("Master password session expired (idle timeout)")
            return self._unlocked

    def unlock(self) -> None:
        with self._lock:
            self._unlocked = True
            self._last_activity = time.monotonic()
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
                self._last_activity = time.monotonic()


_state: dict[str, MasterPasswordSession | None] = {"session": None}


def get_session() -> MasterPasswordSession:
    if _state["session"] is None:
        _state["session"] = MasterPasswordSession()
    return _state["session"]  # type: ignore[return-value]


# ── Password hashing helpers ──────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*.  Falls back to SHA-256+salt if
    bcrypt is unavailable so the feature still works without the optional dep."""
    if not password:
        return ""
    try:
        import bcrypt  # type: ignore

        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except ImportError:
        pass
    # Fallback: PBKDF2-HMAC-SHA256 with a random salt (hex-encoded)
    import os

    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "PBKDF2:" + salt.hex() + ":" + dk.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True if *password* matches *stored_hash*."""
    if not password or not stored_hash:
        return False
    try:
        if stored_hash.startswith("PBKDF2:"):
            _, salt_hex, dk_hex = stored_hash.split(":", 2)
            salt = bytes.fromhex(salt_hex)
            dk_expected = bytes.fromhex(dk_hex)
            dk_actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
            return hmac.compare_digest(dk_actual, dk_expected)
        # bcrypt path
        import bcrypt  # type: ignore

        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception as exc:
        log.warning("Password verification error: %s", exc)
        return False
