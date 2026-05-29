# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import platform
import sys
import threading

logger = logging.getLogger(__name__)


# ── Public key constants ─────────────────────────────────────────────────────

#: Keyring slot for the WebDAV server password.
WEBDAV_PASSWORD_KEY = "webdav.password"


# ── Internals ────────────────────────────────────────────────────────────────

# Service name in the OS keyring.  Matches APP_NAME from constants but is
# inlined here to avoid a circular import: ``constants`` is loaded extremely
# early during interpreter startup.
_KEYRING_SERVICE = "HistorySync"

#: Filename for the file-fallback JSON map under ``get_config_dir()``.
_FILE_FALLBACK_FILENAME = "secrets.json"

#: Env var: when truthy, the file fallback is disabled (no on-disk plaintext).
_NO_FILE_FALLBACK_ENV = "HISTORYSYNC_NO_FILE_SECRETS"


def _set_win32_owner_only(path: Path) -> None:
    """Restrict file access to the current user (Windows ACL ≈ ``chmod 0o600``).

    Best-effort: silently logs and continues when pywin32 is missing.
    """
    try:
        import win32api
        import win32security
    except ImportError:
        logger.debug("pywin32 not available; skipping ACL restriction for %s", path)
        return
    try:
        sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        dacl = win32security.ACL()
        user_sid = win32security.GetTokenInformation(
            win32security.OpenProcessToken(win32api.GetCurrentProcess(), 0x0008),
            win32security.TokenUser,
        )[0]
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, 0x1F01FF, user_sid)  # GENERIC_ALL
        sd.SetSecurityDescriptorDacl(True, dacl, False)
        win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, sd)
    except Exception as exc:
        logger.warning("Failed to set ACL on %s: %s", path, exc)


def _restrict_permissions(path: Path) -> None:
    """Best-effort: make a regular file readable only by its owner."""
    try:
        if sys.platform == "win32":
            _set_win32_owner_only(path)
        else:
            path.chmod(0o600)
    except Exception as exc:
        logger.warning("Could not restrict permissions on %s: %s", path, exc)


def _file_fallback_disabled() -> bool:
    return os.environ.get(_NO_FILE_FALLBACK_ENV, "").strip() not in ("", "0", "false", "False")


def _likely_has_dbus_session() -> bool:
    """Linux-only heuristic: is a freedesktop session bus reachable?

    The keyring chainer is happy to pick the SecretService backend even on
    machines without a running session bus (CI, SSH, container).  In that
    case the backend hangs on first use waiting for a non-existent D-Bus
    daemon.  Pre-checking ``DBUS_SESSION_BUS_ADDRESS`` lets us short-circuit
    cleanly to the file fallback before any prompt UI can spawn.

    Returns ``True`` on Windows / macOS unconditionally — those backends have
    their own probing.
    """
    if sys.platform != "linux":
        return True
    return bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))


class SecretStore:
    """Thread-safe lazy-keyring + restricted-file-fallback secret store.

    A single process-wide instance is exposed via :func:`get_secret_store`.
    Tests may construct fresh instances directly to reset the probe cache.
    """

    SERVICE: str = _KEYRING_SERVICE

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._kr = None
        self._kr_probed = False
        self._kr_available = False

    # ── Backend probe ──────────────────────────────────────────

    def _probe_keyring(self):
        """Lazy keyring import + backend availability check.

        Returns the keyring module if a real backend is usable, else ``None``.
        Result is cached on the instance.
        """
        with self._lock:
            if self._kr_probed:
                return self._kr if self._kr_available else None
            self._kr_probed = True

            # Linux short-circuit: no D-Bus session → SecretService unusable.
            if sys.platform == "linux" and not _likely_has_dbus_session():
                logger.info("SecretStore: no D-Bus session detected; using file fallback")
                return None

            try:
                import keyring as _kr
                from keyring.backends import fail as _fail
            except Exception as exc:
                logger.info("SecretStore: keyring import failed (%s); using file fallback", exc)
                return None

            # Pin platform-specific backend on Windows / macOS for predictability;
            # on Linux let keyring auto-detect SecretService / KWallet.
            try:
                system = platform.system()
                if system == "Windows":
                    from keyring.backends.Windows import WinVaultKeyring

                    _kr.set_keyring(WinVaultKeyring())
                elif system == "Darwin":
                    from keyring.backends.macOS import Keyring as _MacKeyring

                    _kr.set_keyring(_MacKeyring())
            except Exception as exc:
                logger.debug("SecretStore: backend pinning failed (%s); falling back to auto-detect", exc)

            # Reject the explicit "no backend" sentinel.
            try:
                backend = _kr.get_keyring()
            except Exception as exc:
                logger.info("SecretStore: backend probe failed (%s); using file fallback", exc)
                return None

            if isinstance(backend, _fail.Keyring):
                logger.info("SecretStore: only fail.Keyring available; using file fallback")
                return None

            self._kr = _kr
            self._kr_available = True
            return _kr

    def is_available(self) -> bool:
        """True if a real OS keyring backend will be used by ``set`` / ``get``.

        Cheap after the first call (cached).  Does not perform a get/set, so
        invoking it during startup is safe — it never prompts the user.
        """
        return self._probe_keyring() is not None

    # ── Public API ────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        """Return the secret value for ``key``, or ``None`` if not set.

        Tries the keyring first, then the file fallback (so a value written
        while keyring was unavailable is still readable after keyring comes
        online — until a new ``set`` migrates it).
        """
        kr = self._probe_keyring()
        if kr is not None:
            try:
                value = kr.get_password(self.SERVICE, key)
                if value:
                    return value
            except Exception as exc:
                logger.warning("SecretStore.get(%s) keyring error: %s", key, exc)
                # Fall through to file fallback
        return self._file_get(key)

    def set(self, key: str, value: str) -> None:
        """Persist ``value`` under ``key``.

        On keyring success any stale file-fallback entry for the same key is
        deleted, so secrets are not duplicated across stores.
        """
        if not key:
            raise ValueError("SecretStore.set: key must be non-empty")
        kr = self._probe_keyring()
        if kr is not None:
            try:
                kr.set_password(self.SERVICE, key, value)
            except Exception as exc:
                logger.warning("SecretStore.set(%s) keyring error: %s; falling back to file", key, exc)
            else:
                # Best-effort: remove now-stale file copy.
                self._file_delete(key)
                return
        self._file_set(key, value)

    def delete(self, key: str) -> None:
        """Remove ``key`` from both keyring and file fallback.

        Errors are logged but never raised — deleting a non-existent key is
        a no-op so the caller can use this idempotently.
        """
        kr = self._probe_keyring()
        if kr is not None:
            try:
                kr.delete_password(self.SERVICE, key)
            except Exception as exc:
                # PasswordDeleteError when not present — not interesting.
                logger.debug("SecretStore.delete(%s) keyring: %s", key, exc)
        self._file_delete(key)

    def has(self, key: str) -> bool:
        """Return whether ``key`` is currently stored.

        Implementation note: the keyring API has no cheap exists() primitive,
        so this performs a full ``get`` and discards the value.
        """
        return self.get(key) is not None

    # ── File fallback ─────────────────────────────────────────

    def _fallback_path(self) -> Path | None:
        """Resolve the secrets.json path, or ``None`` if file fallback is off."""
        if _file_fallback_disabled():
            return None
        from src.utils.path_helper import get_config_dir

        return get_config_dir() / _FILE_FALLBACK_FILENAME

    def _file_load(self) -> dict[str, str]:
        path = self._fallback_path()
        if path is None or not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("SecretStore: could not read fallback file %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _file_save(self, data: dict[str, str]) -> None:
        path = self._fallback_path()
        if path is None:
            logger.warning("SecretStore: file fallback disabled; secret will not persist")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # fsync may fail on some FUSE filesystems — non-fatal.
                    pass
            _restrict_permissions(tmp)
            tmp.replace(path)
            _restrict_permissions(path)
            logger.warning(
                "SecretStore: secret persisted to local file (keyring unavailable): %s",
                path,
            )
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _file_get(self, key: str) -> str | None:
        with self._lock:
            data = self._file_load()
        value = data.get(key)
        return value if value else None

    def _file_set(self, key: str, value: str) -> None:
        with self._lock:
            data = self._file_load()
            data[key] = value
            self._file_save(data)

    def _file_delete(self, key: str) -> None:
        with self._lock:
            data = self._file_load()
            if key not in data:
                return
            del data[key]
            if data:
                self._file_save(data)
                return
            path = self._fallback_path()
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug("Could not unlink empty %s: %s", path, exc)


# ── Module singleton ─────────────────────────────────────────────────────────

# Construction is free — no keyring access happens here.
_DEFAULT_STORE = SecretStore()


def get_secret_store() -> SecretStore:
    """Return the process-wide :class:`SecretStore` instance."""
    return _DEFAULT_STORE


# ── Legacy ciphertext migration ──────────────────────────────────────────────


def migrate_legacy_ciphertext(key: str, ciphertext: str) -> str | None:
    """Decrypt a legacy ``ENC:`` payload and store the plaintext under ``key``.

    Used to migrate secrets that older versions wrote into ``config.json`` as
    HKDF-encrypted blobs (see ``security_utils.encrypt_text``).

    Returns the plaintext on success — even when persisting it to the secret
    store fails — so the active operation can proceed.  The caller is expected
    to preserve the original ciphertext in its config until a subsequent
    ``get_secret_store().has(key)`` confirms a successful migration.

    Returns ``None`` only when ``ciphertext`` is empty, so the caller can
    distinguish "nothing to migrate" from "tried and failed".

    Propagates ``DecryptionError`` (or any other exception from ``decrypt_text``)
    upward so the caller can distinguish:

    - **transient** failures (keyring locked, OSError) — keep the ciphertext
      and retry on the next launch
    - **permanent** failures (HMAC mismatch, corrupt payload) — give up and
      ask the user to re-enter the secret

    Today both surface as ``DecryptionError``; future versions may refine the
    distinction.  Callers should treat any exception conservatively (preserve
    the ciphertext, set a UI hint).
    """
    if not ciphertext:
        return None
    from src.utils.security_utils import decrypt_text  # may raise DecryptionError

    plaintext = decrypt_text(ciphertext)
    if not plaintext:
        return None
    try:
        get_secret_store().set(key, plaintext)
    except Exception as exc:
        logger.warning("Legacy migration: could not persist %s to secret store: %s", key, exc)
        # Plaintext is still returned so the caller can use it for this session.
    return plaintext
