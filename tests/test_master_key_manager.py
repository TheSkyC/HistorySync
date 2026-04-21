# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for MasterPasswordSession in master_key_manager.py."""

from __future__ import annotations

from unittest import mock

from src.utils.master_key_manager import SESSION_TIMEOUT_S, MasterPasswordSession


class TestMasterPasswordSession:
    def test_initially_locked(self):
        session = MasterPasswordSession()
        assert not session.is_unlocked

    def test_unlock_and_lock(self):
        session = MasterPasswordSession()
        session.unlock()
        assert session.is_unlocked
        session.lock()
        assert not session.is_unlocked

    def test_session_expires_after_timeout(self):
        """Session expires when wall-clock idle time exceeds SESSION_TIMEOUT_S."""
        session = MasterPasswordSession()
        # Unlock the session at t=0
        with mock.patch("time.time", return_value=0.0):
            session.unlock()
        # Check status before timeout (t = SESSION_TIMEOUT_S - 1)
        with mock.patch("time.time", return_value=float(SESSION_TIMEOUT_S - 1)):
            assert session.is_unlocked
        # Check status after timeout (t = SESSION_TIMEOUT_S + 1)
        with mock.patch("time.time", return_value=float(SESSION_TIMEOUT_S + 1)):
            assert not session.is_unlocked

    def test_touch_extends_session(self):
        """touch() resets the idle clock so the session survives longer."""
        session = MasterPasswordSession()
        # Unlock at t=0
        with mock.patch("time.time", return_value=0.0):
            session.unlock()
        # Touch at t = SESSION_TIMEOUT_S - 5 (just before expiry)
        with mock.patch("time.time", return_value=float(SESSION_TIMEOUT_S - 5)):
            session.touch()
        # Session should now be valid until t = 2*SESSION_TIMEOUT_S - 5
        # Check at t = SESSION_TIMEOUT_S + 10 (expired from original unlock,
        # but within the extended window from touch)
        with mock.patch("time.time", return_value=float(SESSION_TIMEOUT_S + 10)):
            assert session.is_unlocked

    def test_touch_no_effect_when_locked(self):
        """touch() on a locked session does nothing."""
        session = MasterPasswordSession()
        session.touch()  # must not raise
        assert not session.is_unlocked

    def test_observer_called_on_unlock(self):
        session = MasterPasswordSession()
        cb = mock.MagicMock()
        session.add_observer(cb)
        session.unlock()
        cb.assert_called_once()

    def test_observer_called_on_lock(self):
        session = MasterPasswordSession()
        cb = mock.MagicMock()
        session.add_observer(cb)
        session.unlock()
        cb.reset_mock()
        session.lock()
        cb.assert_called_once()

    def test_remove_observer(self):
        session = MasterPasswordSession()
        cb = mock.MagicMock()
        session.add_observer(cb)
        session.remove_observer(cb)
        session.unlock()
        cb.assert_not_called()
