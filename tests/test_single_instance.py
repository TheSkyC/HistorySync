# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for the nonce-based IPC authentication helpers in single_instance.py."""

from __future__ import annotations

from unittest import mock

from src.utils.single_instance import (
    _NONCE_BYTES,
    ACTIVATE_MSG,
    ACTIVATE_QUICK_MSG,
    _get_token_file,
    _read_nonce,
)


class TestReadNonce:
    def test_returns_nonce_when_file_exists(self, tmp_path):
        nonce = bytes(range(_NONCE_BYTES))
        token_file = tmp_path / "ipc.token"
        token_file.write_bytes(nonce)
        with mock.patch("src.utils.single_instance._get_token_file", return_value=token_file):
            assert _read_nonce() == nonce

    def test_returns_empty_when_file_missing(self, tmp_path):
        token_file = tmp_path / "nonexistent.token"
        with mock.patch("src.utils.single_instance._get_token_file", return_value=token_file):
            assert _read_nonce() == b""

    def test_returns_empty_when_file_wrong_length(self, tmp_path):
        token_file = tmp_path / "ipc.token"
        token_file.write_bytes(b"short")
        with mock.patch("src.utils.single_instance._get_token_file", return_value=token_file):
            assert _read_nonce() == b""


class TestNonceConstants:
    def test_nonce_length(self):
        assert _NONCE_BYTES == 20

    def test_activate_msg_unchanged(self):
        assert ACTIVATE_MSG == b"ACTIVATE_HISTORYSYNC"

    def test_activate_quick_msg_unchanged(self):
        assert ACTIVATE_QUICK_MSG == b"ACTIVATE_QUICK"


class TestTokenFileLocation:
    def test_token_file_in_config_dir(self):
        from src.utils.path_helper import get_config_dir

        assert _get_token_file() == get_config_dir() / "ipc.token"
