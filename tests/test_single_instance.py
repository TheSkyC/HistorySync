# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for the nonce-based IPC authentication helpers in single_instance.py."""

from __future__ import annotations

from pathlib import Path
import tempfile
from unittest import mock

from src.utils.single_instance import (
    _NONCE_BYTES,
    _TOKEN_FILE,
    ACTIVATE_MSG,
    ACTIVATE_QUICK_MSG,
    _read_nonce,
)


class TestReadNonce:
    def test_returns_nonce_when_file_exists(self, tmp_path):
        nonce = bytes(range(_NONCE_BYTES))
        token_file = tmp_path / "hs_ipc.token"
        token_file.write_bytes(nonce)
        with mock.patch("src.utils.single_instance._TOKEN_FILE", token_file):
            assert _read_nonce() == nonce

    def test_returns_empty_when_file_missing(self, tmp_path):
        token_file = tmp_path / "nonexistent.token"
        with mock.patch("src.utils.single_instance._TOKEN_FILE", token_file):
            assert _read_nonce() == b""

    def test_returns_empty_when_file_wrong_length(self, tmp_path):
        token_file = tmp_path / "hs_ipc.token"
        token_file.write_bytes(b"short")
        with mock.patch("src.utils.single_instance._TOKEN_FILE", token_file):
            assert _read_nonce() == b""


class TestNonceConstants:
    def test_nonce_length(self):
        assert _NONCE_BYTES == 20

    def test_activate_msg_unchanged(self):
        assert ACTIVATE_MSG == b"ACTIVATE_HISTORYSYNC"

    def test_activate_quick_msg_unchanged(self):
        assert ACTIVATE_QUICK_MSG == b"ACTIVATE_QUICK"


class TestTokenFileLocation:
    def test_token_file_in_tempdir(self):
        assert _TOKEN_FILE.parent == Path(tempfile.gettempdir())
        assert _TOKEN_FILE.name == "hs_ipc.token"
