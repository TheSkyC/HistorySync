# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import hmac
import logging
import os
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
            if sys.platform != "win32":
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

    Algorithm: SHAKE-256 keystream XOR + HMAC-SHA256 authentication tag.
    """
    if not text:
        return ""
    try:
        master_key = _get_or_create_master_key()
        text_bytes = text.encode("utf-8")
        salt = os.urandom(16)

        keystream = hashlib.shake_256(master_key + salt).digest(len(text_bytes))
        encrypted_bytes = bytes(a ^ b for a, b in zip(text_bytes, keystream, strict=False))
        signature = hmac.new(master_key, salt + encrypted_bytes, hashlib.sha256).digest()

        payload = salt + signature + encrypted_bytes
        return ENCRYPTION_PREFIX + base64.b64encode(payload).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return ""


def decrypt_text(text: str) -> str:
    """
    Decrypts ciphertext in "ENC:<base64>" format, returning the original plaintext.
    If the input is not in encrypted format (missing "ENC:" prefix), it is returned as-is (for migration compatibility).
    """
    if not text or not text.startswith(ENCRYPTION_PREFIX):
        return text
    try:
        master_key = _get_or_create_master_key()

        try:
            payload = base64.b64decode(text[len(ENCRYPTION_PREFIX) :])
        except Exception:
            return ""

        if len(payload) < 48:  # 16 (salt) + 32 (HMAC-SHA256)
            return ""

        salt = payload[:16]
        signature = payload[16:48]
        encrypted_bytes = payload[48:]

        expected_sig = hmac.new(master_key, salt + encrypted_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            logger.warning("Decryption signature mismatch — data may be tampered.")
            return ""

        keystream = hashlib.shake_256(master_key + salt).digest(len(encrypted_bytes))
        decrypted_bytes = bytes(a ^ b for a, b in zip(encrypted_bytes, keystream, strict=False))
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ""
