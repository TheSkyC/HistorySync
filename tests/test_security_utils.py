# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import logging
from unittest import mock

import pytest

pytest.importorskip("keyring", reason="keyring not installed")

from src.utils.security_utils import decrypt_text, encrypt_text


@pytest.fixture(autouse=True)
def _fixed_master_key(monkeypatch):
    """Patch _get_or_create_master_key with a fixed key for encrypt/decrypt tests."""
    fixed_key = bytes(range(32))
    monkeypatch.setattr(
        "src.utils.security_utils._get_or_create_master_key",
        lambda: fixed_key,
    )


class TestEncryptText:
    """Test encrypt_text function."""

    def test_empty_string_returns_empty(self):
        """Empty string returns empty string."""
        assert encrypt_text("") == ""

    def test_result_has_enc_prefix(self):
        """Result starts with ENC: prefix."""
        result = encrypt_text("hello")
        assert result.startswith("ENC:")

    def test_result_is_valid_base64(self):
        """Result after ENC: prefix is valid base64."""
        result = encrypt_text("hello")
        payload = result[4:]  # Strip "ENC:"
        try:
            base64.b64decode(payload)
        except Exception:
            pytest.fail("Result is not valid base64")

    def test_different_calls_produce_different_ciphertext(self):
        """Two encryptions of same plaintext produce different ciphertext (random salt)."""
        result1 = encrypt_text("hello")
        result2 = encrypt_text("hello")
        assert result1 != result2

    def test_encrypt_unicode(self):
        """Unicode text can be encrypted."""
        result = encrypt_text("日本語テスト")
        assert result.startswith("ENC:")


class TestDecryptText:
    """Test decrypt_text function."""

    def test_non_enc_string_returned_as_is(self):
        """String without ENC: prefix is returned as-is."""
        assert decrypt_text("plaintext") == "plaintext"

    def test_empty_string_returned_as_is(self):
        """Empty string is returned as-is."""
        assert decrypt_text("") == ""

    def test_enc_prefix_without_valid_base64_returns_empty(self):
        """ENC: prefix with invalid base64 returns empty string."""
        assert decrypt_text("ENC:!!!notbase64!!!") == ""

    def test_too_short_payload_returns_empty(self):
        """Payload shorter than 48 bytes returns empty string."""
        short_payload = base64.b64encode(b"short").decode()
        assert decrypt_text(f"ENC:{short_payload}") == ""

    def test_tampered_hmac_returns_empty(self):
        """Tampered HMAC signature returns empty string."""
        # Encrypt something
        encrypted = encrypt_text("hello")
        # Flip a bit in the ciphertext portion (after HMAC)
        payload = base64.b64decode(encrypted[4:])
        tampered = payload[:48] + bytes([payload[48] ^ 1]) + payload[49:]
        tampered_enc = "ENC:" + base64.b64encode(tampered).decode()
        assert decrypt_text(tampered_enc) == ""


class TestEncryptDecryptRoundtrip:
    """Test encrypt/decrypt roundtrip."""

    def test_roundtrip_ascii(self):
        """ASCII text roundtrips correctly."""
        plaintext = "hello world"
        encrypted = encrypt_text(plaintext)
        decrypted = decrypt_text(encrypted)
        assert decrypted == plaintext

    def test_roundtrip_unicode(self):
        """Unicode text roundtrips correctly."""
        plaintext = "日本語テスト"
        encrypted = encrypt_text(plaintext)
        decrypted = decrypt_text(encrypted)
        assert decrypted == plaintext

    def test_roundtrip_long_string(self):
        """Long string (8000 chars, within HKDF 8160-byte limit) roundtrips correctly."""
        plaintext = "x" * 8000
        encrypted = encrypt_text(plaintext)
        decrypted = decrypt_text(encrypted)
        assert decrypted == plaintext

    def test_roundtrip_special_chars(self):
        """Special characters roundtrip correctly."""
        plaintext = "!@#$%^&*()\n\t\r"
        encrypted = encrypt_text(plaintext)
        decrypted = decrypt_text(encrypted)
        assert decrypted == plaintext


class TestMasterKeyFallback:
    """Test _get_or_create_master_key fallback logic."""

    def test_reads_from_keyring(self, monkeypatch, tmp_path):
        """Key is read from keyring if available."""
        test_key = bytes(range(32))
        test_key_hex = test_key.hex()

        with (
            mock.patch("keyring.get_password", return_value=test_key_hex),
            mock.patch("src.utils.path_helper.get_config_dir", return_value=tmp_path),
        ):
            import importlib

            import src.utils.security_utils

            importlib.reload(src.utils.security_utils)
            from src.utils.security_utils import _get_or_create_master_key

            key = _get_or_create_master_key()
            assert key == test_key

    def test_keyring_fail_falls_back_to_file(self, monkeypatch, tmp_path):
        """Falls back to local file when keyring fails."""
        test_key = bytes(range(32))
        secret_file = tmp_path / "secret.key"
        secret_file.write_bytes(test_key)

        with (
            mock.patch("keyring.get_password", side_effect=Exception("Keyring unavailable")),
            mock.patch("keyring.set_password", side_effect=Exception("Keyring unavailable")),
            mock.patch("src.utils.path_helper.get_config_dir", return_value=tmp_path),
        ):
            import importlib

            import src.utils.security_utils

            importlib.reload(src.utils.security_utils)
            from src.utils.security_utils import _get_or_create_master_key

            key = _get_or_create_master_key()
            assert key == test_key

    def test_generates_new_key_when_nothing_exists(self, monkeypatch, tmp_path):
        """Generates new key when keyring and file don't exist."""
        with (
            mock.patch("keyring.get_password", return_value=None),
            mock.patch("keyring.set_password") as mock_set,
            mock.patch("src.utils.path_helper.get_config_dir", return_value=tmp_path),
        ):
            import importlib

            import src.utils.security_utils

            importlib.reload(src.utils.security_utils)
            from src.utils.security_utils import _get_or_create_master_key

            key = _get_or_create_master_key()
            assert len(key) == 32
            assert isinstance(key, bytes)
            assert mock_set.called

    def test_fallback_to_file_when_keyring_set_fails(self, monkeypatch, tmp_path, caplog):
        """Falls back to local file when keyring set fails."""
        with (
            mock.patch("keyring.get_password", return_value=None),
            mock.patch("keyring.set_password", side_effect=Exception("Keyring unavailable")),
            mock.patch("src.utils.path_helper.get_config_dir", return_value=tmp_path),
            caplog.at_level(logging.WARNING),
        ):
            import importlib

            import src.utils.security_utils

            importlib.reload(src.utils.security_utils)
            from src.utils.security_utils import _get_or_create_master_key

            key = _get_or_create_master_key()
            assert len(key) == 32
            assert any("SECURITY WARNING" in record.message for record in caplog.records)
            secret_file = tmp_path / "secret.key"
            assert secret_file.exists()
            assert secret_file.read_bytes() == key
