# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import hmac
import logging
import os
from pathlib import Path
import platform
import sys

import keyring
import keyring.errors

from src.utils.constants import ENCRYPTION_PREFIX, KEYRING_SERVICE, KEYRING_USER, SECRET_FILENAME
from src.utils.path_helper import get_config_dir

logger = logging.getLogger(__name__)

_COLOR_WARN = "\033[93m"
_COLOR_RESET = "\033[0m"


def _init_keyring_backend() -> None:
    """Locks a platform-specific backend to speed up startup, falling back to auto-scan on failure."""
    try:
        system = platform.system()
        if system == "Windows":
            from keyring.backends.Windows import WinVaultKeyring

            keyring.set_keyring(WinVaultKeyring())
        elif system == "Darwin":
            from keyring.backends.macOS import Keyring

            keyring.set_keyring(Keyring())
    except Exception as e:
        logger.debug(f"Explicit keyring init failed, falling back to auto-scan: {e}")


_init_keyring_backend()

_HKDF_INFO = b"historysync-enc\x00"

_PAD_BLOCK = 64  # pad plaintext to multiples of this size to hide true length


def _pad(data: bytes) -> bytes:
    n = _PAD_BLOCK - (len(data) % _PAD_BLOCK)
    return data + bytes([n] * n)


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty payload")
    n = data[-1]
    if n < 1 or n > _PAD_BLOCK or data[-n:] != bytes([n] * n):
        raise ValueError("invalid padding")
    return data[:-n]


def _hkdf_expand(prk: bytes, length: int) -> bytes:
    """HKDF-Expand (RFC 5869) using HMAC-SHA256. Max output: 255 * 32 = 8160 bytes."""
    if length > 255 * 32:
        raise ValueError(f"HKDF-Expand: requested length {length} exceeds maximum 8160 bytes")
    output = b""
    t = b""
    counter = 1
    while len(output) < length:
        t = hmac.new(prk, t + _HKDF_INFO + bytes([counter]), hashlib.sha256).digest()
        output += t
        counter += 1
    return output[:length]


def _derive_keystream(master_key: bytes, salt: bytes, length: int) -> bytes:
    """Derive a keystream via HKDF-SHA256 (Extract + Expand)."""
    prk = hmac.new(salt, master_key, hashlib.sha256).digest()  # HKDF-Extract
    return _hkdf_expand(prk, length)  # HKDF-Expand


def _set_win32_owner_only(path: Path) -> None:
    """Restrict file access to the current user only (Windows ACL equivalent of chmod 0o600)."""
    try:
        import win32api
        import win32security

        sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        dacl = win32security.ACL()
        user_sid = win32security.GetTokenInformation(
            win32security.OpenProcessToken(win32api.GetCurrentProcess(), 0x0008),
            win32security.TokenUser,
        )[0]
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, 0x1F01FF, user_sid)  # GENERIC_ALL
        sd.SetSecurityDescriptorDacl(True, dacl, False)
        win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, sd)
    except ImportError:
        logger.debug("pywin32 not available; skipping ACL restriction for %s", path)
    except Exception as e:
        logger.warning("Failed to set ACL on %s: %s", path, e)


def _get_or_create_master_key() -> bytes:
    """
    Gets or creates the master key.

    Priority strategy:
    1. Read from system Keyring (Windows Credential Manager / macOS Keychain / libsecret).
    2. Fallback to local secret.key file if Keyring is unavailable.
    3. Generate a new random key if neither exists.
    4. Write back prioritizing Keyring; if it fails, write to local file (and log a security warning).
    """
    # 1. Attempt to read from Keyring
    try:
        key_hex = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if key_hex:
            return bytes.fromhex(key_hex)
    except Exception as e:
        logger.warning(f"Keyring lookup failed (will try local file): {e}")

    # 2. Fallback: attempt to read local file
    key_path = get_config_dir() / SECRET_FILENAME
    key: bytes | None = None

    if key_path.exists():
        try:
            with key_path.open("rb") as f:
                data = f.read()
                if len(data) == 32:
                    key = data
                    logger.info("Loaded master key from local file (fallback).")
        except Exception as e:
            logger.error(f"Failed to read local key file: {e}")

    # 3. Generate new key
    if not key:
        logger.info("Generating new master key.")
        key = os.urandom(32)

    # 4. Write back: prioritize Keyring, fallback to file
    saved_to_keyring = False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.hex())
        saved_to_keyring = True
        logger.info("Master key saved to system Keyring.")
    except Exception as e:
        logger.error(f"Failed to save key to Keyring: {e}")

    if not saved_to_keyring:
        try:
            with key_path.open("wb") as f:
                f.write(key)
            if sys.platform == "win32":
                _set_win32_owner_only(key_path)
            else:
                key_path.chmod(0o600)
            logger.warning(
                f"{_COLOR_WARN}[SECURITY WARNING] Master key saved to UNENCRYPTED local file "
                f"(Keyring unavailable): {key_path}{_COLOR_RESET}"
            )
        except Exception as e:
            raise OSError(
                f"Critical Security Error: Could not save master key to Keyring OR local file.\n"
                f"Path: {key_path}\nError: {e}"
            ) from e

    return key


def encrypt_text(text: str) -> str:
    """
    Encrypts a plaintext string, returning ciphertext in "ENC:<base64>" format.
    Empty strings are returned as-is (unencrypted).

    Algorithm: HKDF-SHA256 keystream XOR + HMAC-SHA256 authentication tag.
    Payload format: [0x01 version][16B salt][32B HMAC-SHA256][N bytes ciphertext]
    """
    if not text:
        return ""
    try:
        master_key = _get_or_create_master_key()
        text_bytes = _pad(text.encode("utf-8"))
        salt = os.urandom(16)

        keystream = _derive_keystream(master_key, salt, len(text_bytes))
        encrypted_bytes = bytes(a ^ b for a, b in zip(text_bytes, keystream, strict=False))
        signature = hmac.new(master_key, salt + encrypted_bytes, hashlib.sha256).digest()

        payload = b"\x01" + salt + signature + encrypted_bytes
        return ENCRYPTION_PREFIX + base64.b64encode(payload).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return ""


def _try_decrypt_hkdf(payload: bytes, master_key: bytes) -> str | None:
    """Attempt decryption using HKDF keystream (v1 format)."""
    if len(payload) < 49:  # 1 + 16 + 32
        return None
    salt = payload[1:17]
    signature = payload[17:49]
    encrypted_bytes = payload[49:]
    expected = hmac.new(master_key, salt + encrypted_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    keystream = _derive_keystream(master_key, salt, len(encrypted_bytes))
    plain = bytes(a ^ b for a, b in zip(encrypted_bytes, keystream, strict=False))
    try:
        return _unpad(plain).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _try_decrypt_legacy(payload: bytes, master_key: bytes) -> str | None:
    """Attempt decryption using legacy SHAKE-256 keystream (v0 format)."""
    if len(payload) < 48:  # 16 + 32
        return None
    salt = payload[:16]
    signature = payload[16:48]
    encrypted_bytes = payload[48:]
    expected = hmac.new(master_key, salt + encrypted_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    keystream = hashlib.shake_256(master_key + salt).digest(len(encrypted_bytes))
    return bytes(a ^ b for a, b in zip(encrypted_bytes, keystream, strict=False)).decode("utf-8")


def decrypt_text(text: str) -> str:
    """
    Decrypts ciphertext in "ENC:<base64>" format, returning the original plaintext.
    If the input is not in encrypted format (missing "ENC:" prefix), it is returned as-is (for migration compatibility).

    Supports both v1 (HKDF) and legacy v0 (SHAKE-256) payloads.
    When payload[0] == 0x01 but HMAC fails, falls back to legacy path to handle
    the 1/256 chance that an old random salt starts with 0x01.
    """
    if not text or not text.startswith(ENCRYPTION_PREFIX):
        return text
    try:
        master_key = _get_or_create_master_key()

        try:
            payload = base64.b64decode(text[len(ENCRYPTION_PREFIX) :])
        except Exception:
            return ""

        if len(payload) < 1:
            return ""

        if payload[0] == 0x01:
            result = _try_decrypt_hkdf(payload, master_key)
            if result is None:
                # 1/256 collision: old random salt happened to start with 0x01
                result = _try_decrypt_legacy(payload, master_key)
            if result is None:
                logger.warning("Decryption signature mismatch — data may be tampered.")
            return result or ""
        result = _try_decrypt_legacy(payload, master_key)
        if result is None:
            logger.warning("Decryption signature mismatch — data may be tampered.")
        return result or ""
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ""
