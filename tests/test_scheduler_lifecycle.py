# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Lifecycle and state-machine tests for ``src.services.scheduler.Scheduler``.

The existing :mod:`tests.test_scheduler_contract` covers the worker classes
plus a few configure/trigger contracts.  This module fills in the deeper
gaps:

* The ``_running`` / ``_backup_running`` flag transitions through every
  end-of-cycle slot — ``_on_sync_finished``, ``_on_sync_error``,
  ``_on_sync_thread_finished``, ``_on_backup_finished``,
  ``_on_backup_thread_finished``.
* Sender-aware slots that only react when the emitter matches the tracked
  thread, exercised via a real ``Signal``-bearing ``QObject`` so
  ``self.sender()`` resolves.
* ``set_auto_sync_enabled`` pause / resume — independence from the backup
  timer.
* All four ``configure()`` enable combinations (none / sync / backup / both)
  and the lead-in vs repeating-timer hand-off.
* Reconfigure stops old timers before re-arming.
* ``shutdown`` cancels in-flight workers and tolerates the no-thread case.
* Sync timer / backup timer guards against double-firing while a run is
  already in flight.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QObject, Signal

from src.models.app_config import SchedulerConfig
from src.services.scheduler import Scheduler

# ──────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────


class _FakeWebDav:
    """Minimal :class:`WebDavSyncService` double used for guard tests."""

    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.auto_backup_enabled = True

    def is_configured(self) -> bool:
        return self._configured


class _FakeQThread:
    """Stand-in for ``QThread`` that lets us toggle ``isRunning`` without
    actually starting an OS thread.

    ``cancel`` is invoked by ``shutdown`` and ``wait`` controls how the
    timeout branch behaves — together they let us exercise both the happy
    path and the force-quit path.
    """

    def __init__(self, *, running: bool = True, wait_returns: bool = True) -> None:
        self._running = running
        self._wait_returns = wait_returns
        self.wait_calls: list[int] = []
        self.quit_calls = 0

    def isRunning(self) -> bool:
        return self._running

    def wait(self, ms: int) -> bool:
        self.wait_calls.append(ms)
        # When wait returns False the scheduler treats it as a hung thread.
        return self._wait_returns

    def quit(self) -> None:
        self.quit_calls += 1
        # Mark not running after a quit so subsequent isRunning() checks pass.
        self._running = False


class _CancellableWorker:
    """A worker stub that records ``cancel()`` calls."""

    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _SignalEmitter(QObject):
    """Tiny ``QObject`` exposing a ``finished`` signal.

    Used so ``self.sender()`` resolves correctly inside slots that filter on
    sender identity (``_on_backup_thread_finished``).
    """

    finished = Signal()


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def em() -> SimpleNamespace:
    """Bare extractor manager double — Scheduler only stores the reference."""
    return SimpleNamespace()


@pytest.fixture()
def scheduler(qapp, em) -> Scheduler:
    return Scheduler(extractor_manager=em)


@pytest.fixture()
def scheduler_with_wdav(qapp, em) -> Scheduler:
    return Scheduler(extractor_manager=em, webdav_service=_FakeWebDav(configured=True))


def _basic_config(
    *,
    auto_sync: bool = False,
    sync_hours: int = 1,
    auto_backup: bool = False,
    backup_hours: int = 2,
) -> SchedulerConfig:
    return SchedulerConfig(
        auto_sync_enabled=auto_sync,
        sync_interval_hours=sync_hours,
        auto_backup_enabled=auto_backup,
        auto_backup_interval_hours=backup_hours,
    )


# ──────────────────────────────────────────────────────────────────────────
# Sync state machine
# ──────────────────────────────────────────────────────────────────────────


class TestSyncStateMachine:
    def test_run_sync_sets_running_and_emits_started(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Patch out QThread.start so we don't actually spin a thread.
        monkeypatch.setattr("src.services.scheduler.QThread.start", lambda self: None)
        events = []
        scheduler.sync_started.connect(lambda: events.append(True))

        scheduler._run_sync()

        assert scheduler._running is True
        assert scheduler.is_running is True
        assert events == [True]
        assert scheduler._worker_thread is not None
        assert scheduler._worker is not None

    def test_on_sync_finished_clears_running_and_updates_last_sync(
        self,
        scheduler: Scheduler,
    ) -> None:
        scheduler._running = True
        scheduler._last_sync = None

        emitted: list[dict[str, int]] = []
        scheduler.sync_finished.connect(lambda r: emitted.append(dict(r)))

        scheduler._on_sync_finished({"chrome": 5})

        assert scheduler._running is False
        assert scheduler._last_sync is not None
        assert scheduler._last_sync > 0
        assert scheduler.last_sync == scheduler._last_sync
        assert emitted == [{"chrome": 5}]

    def test_on_sync_error_clears_running_and_emits_error(
        self,
        scheduler: Scheduler,
    ) -> None:
        scheduler._running = True

        errors: list[str] = []
        scheduler.sync_error.connect(errors.append)

        scheduler._on_sync_error("network down")

        assert scheduler._running is False
        assert errors == ["network down"]

    def test_on_sync_thread_finished_resets_running_when_still_set(
        self,
        scheduler: Scheduler,
    ) -> None:
        # Simulate the corner case where _running is somehow still True
        # when the QThread reports finished — the scheduler must self-heal.
        fake = _FakeQThread()
        scheduler._worker_thread = fake  # type: ignore[assignment]
        scheduler._worker = SimpleNamespace()
        scheduler._running = True

        scheduler._on_sync_thread_finished(fake)  # type: ignore[arg-type]

        assert scheduler._running is False
        assert scheduler._worker_thread is None
        assert scheduler._worker is None

    def test_on_sync_thread_finished_ignores_other_thread(
        self,
        scheduler: Scheduler,
    ) -> None:
        tracked = _FakeQThread()
        other = _FakeQThread()
        scheduler._worker_thread = tracked  # type: ignore[assignment]
        scheduler._worker = SimpleNamespace()
        scheduler._running = True

        # Slot called with a *different* thread → must early-return without mutating state.
        scheduler._on_sync_thread_finished(other)  # type: ignore[arg-type]

        assert scheduler._running is True
        assert scheduler._worker_thread is tracked
        assert scheduler._worker is not None


# ──────────────────────────────────────────────────────────────────────────
# Backup state machine
# ──────────────────────────────────────────────────────────────────────────


class TestBackupStateMachine:
    def test_run_backup_sets_backup_running_and_emits_started(
        self,
        scheduler_with_wdav: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("src.services.scheduler.QThread.start", lambda self: None)
        events = []
        scheduler_with_wdav.backup_started.connect(lambda: events.append(True))

        scheduler_with_wdav._run_backup()

        assert scheduler_with_wdav._backup_running is True
        assert events == [True]

    def test_run_backup_no_op_when_no_webdav(
        self,
        scheduler: Scheduler,
    ) -> None:
        # No webdav_service configured at all.
        events = []
        scheduler.backup_started.connect(lambda: events.append(True))

        scheduler._run_backup()

        assert scheduler._backup_running is False
        assert events == []

    def test_run_backup_no_op_when_webdav_not_configured(
        self,
        qapp,
        em,
    ) -> None:
        s = Scheduler(extractor_manager=em, webdav_service=_FakeWebDav(configured=False))
        events = []
        s.backup_started.connect(lambda: events.append(True))

        s._run_backup()

        assert s._backup_running is False
        assert events == []

    def test_on_backup_finished_clears_running_and_emits(
        self,
        scheduler: Scheduler,
    ) -> None:
        scheduler._backup_running = True
        emitted: list[tuple[bool, str]] = []
        scheduler.backup_finished.connect(lambda ok, msg: emitted.append((ok, msg)))

        scheduler._on_backup_finished(True, "uploaded")

        assert scheduler._backup_running is False
        assert emitted == [(True, "uploaded")]

    def test_on_backup_thread_finished_resets_state_via_signal_emit(
        self,
        scheduler: Scheduler,
    ) -> None:
        emitter = _SignalEmitter()
        scheduler._backup_thread = emitter  # type: ignore[assignment]
        scheduler._backup_worker = SimpleNamespace()
        scheduler._backup_running = True

        # Connect through Qt so self.sender() inside the slot resolves to ``emitter``.
        emitter.finished.connect(scheduler._on_backup_thread_finished)
        emitter.finished.emit()

        assert scheduler._backup_running is False
        assert scheduler._backup_thread is None
        assert scheduler._backup_worker is None

    def test_on_backup_thread_finished_ignores_unrelated_emitter(
        self,
        scheduler: Scheduler,
    ) -> None:
        tracked = _SignalEmitter()
        unrelated = _SignalEmitter()
        scheduler._backup_thread = tracked  # type: ignore[assignment]
        scheduler._backup_worker = SimpleNamespace()
        scheduler._backup_running = True

        unrelated.finished.connect(scheduler._on_backup_thread_finished)
        unrelated.finished.emit()

        # Slot must early-return because sender() != _backup_thread.
        assert scheduler._backup_running is True
        assert scheduler._backup_thread is tracked
        assert scheduler._backup_worker is not None


# ──────────────────────────────────────────────────────────────────────────
# Trigger guards
# ──────────────────────────────────────────────────────────────────────────


class TestTriggerGuards:
    def test_trigger_backup_now_skipped_when_already_running(
        self,
        scheduler_with_wdav: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler_with_wdav, "_run_backup", lambda: called.append(True))

        scheduler_with_wdav._backup_running = True
        scheduler_with_wdav.trigger_backup_now()

        assert called == []

    def test_trigger_backup_now_skipped_when_thread_still_running(
        self,
        scheduler_with_wdav: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler_with_wdav, "_run_backup", lambda: called.append(True))
        scheduler_with_wdav._backup_running = False
        scheduler_with_wdav._backup_thread = _FakeQThread(running=True)  # type: ignore[assignment]

        scheduler_with_wdav.trigger_backup_now()

        assert called == []

    def test_trigger_backup_now_runs_when_idle(
        self,
        scheduler_with_wdav: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler_with_wdav, "_run_backup", lambda: called.append(True))
        scheduler_with_wdav._backup_running = False
        scheduler_with_wdav._backup_thread = None

        scheduler_with_wdav.trigger_backup_now()

        assert called == [True]


# ──────────────────────────────────────────────────────────────────────────
# Timer fire callbacks (_on_sync_timer / _on_backup_timer)
# ──────────────────────────────────────────────────────────────────────────


class TestTimerCallbacks:
    def test_on_sync_timer_runs_sync_when_idle(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ran = []
        monkeypatch.setattr(scheduler, "_run_sync", lambda *a, **k: ran.append(True))

        scheduler._running = False
        scheduler._on_sync_timer()

        assert ran == [True]

    def test_on_sync_timer_no_op_when_already_running(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ran = []
        monkeypatch.setattr(scheduler, "_run_sync", lambda *a, **k: ran.append(True))

        scheduler._running = True
        scheduler._on_sync_timer()

        assert ran == []

    def test_on_backup_timer_runs_backup_when_idle(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ran = []
        monkeypatch.setattr(scheduler, "_run_backup", lambda: ran.append(True))

        scheduler._backup_running = False
        scheduler._on_backup_timer()

        assert ran == [True]

    def test_on_backup_timer_no_op_when_already_running(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ran = []
        monkeypatch.setattr(scheduler, "_run_backup", lambda: ran.append(True))

        scheduler._backup_running = True
        scheduler._on_backup_timer()

        assert ran == []


# ──────────────────────────────────────────────────────────────────────────
# Auto-enable toggle
# ──────────────────────────────────────────────────────────────────────────


class TestSetAutoSyncEnabled:
    def test_pause_stops_sync_timer_and_lead_in(self, scheduler: Scheduler) -> None:
        cfg = _basic_config(auto_sync=True, sync_hours=1)
        scheduler.configure(cfg)
        assert scheduler._sync_lead_timer.isActive() is True

        scheduler.set_auto_sync_enabled(False)

        assert scheduler._sync_auto_enabled is False
        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._sync_timer.isActive() is False

    def test_resume_starts_repeating_timer_when_neither_active(self, scheduler: Scheduler) -> None:
        # Pre-condition: timer must have a non-zero interval so start() is meaningful.
        scheduler._sync_timer.setInterval(60_000)
        scheduler._sync_auto_enabled = False
        scheduler._sync_lead_timer.stop()
        scheduler._sync_timer.stop()

        scheduler.set_auto_sync_enabled(True)

        assert scheduler._sync_auto_enabled is True
        assert scheduler._sync_timer.isActive() is True

    def test_resume_does_not_double_start_when_lead_in_pending(
        self,
        scheduler: Scheduler,
    ) -> None:
        cfg = _basic_config(auto_sync=True, sync_hours=1)
        scheduler.configure(cfg)
        assert scheduler._sync_lead_timer.isActive() is True

        # Already enabled → resume must not stomp the lead-in or start the repeating
        # timer prematurely.
        scheduler.set_auto_sync_enabled(True)

        assert scheduler._sync_lead_timer.isActive() is True
        assert scheduler._sync_timer.isActive() is False

    def test_does_not_touch_backup_timer(self, scheduler: Scheduler) -> None:
        cfg = _basic_config(auto_sync=True, auto_backup=True)
        scheduler.configure(cfg)
        assert scheduler._backup_lead_timer.isActive() is True

        scheduler.set_auto_sync_enabled(False)

        assert scheduler._backup_auto_enabled is True
        assert scheduler._backup_lead_timer.isActive() is True


# ──────────────────────────────────────────────────────────────────────────
# Configure / reconfigure / start / stop
# ──────────────────────────────────────────────────────────────────────────


class TestConfigureCombinations:
    def test_neither_enabled_no_timers_armed(self, scheduler: Scheduler) -> None:
        scheduler.configure(_basic_config(auto_sync=False, auto_backup=False))

        assert scheduler._sync_auto_enabled is False
        assert scheduler._backup_auto_enabled is False
        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._backup_lead_timer.isActive() is False

    def test_only_sync_enabled(self, scheduler: Scheduler) -> None:
        scheduler.configure(_basic_config(auto_sync=True, auto_backup=False))

        assert scheduler._sync_auto_enabled is True
        assert scheduler._backup_auto_enabled is False
        assert scheduler._sync_lead_timer.isActive() is True
        assert scheduler._backup_lead_timer.isActive() is False

    def test_only_backup_enabled(self, scheduler: Scheduler) -> None:
        scheduler.configure(_basic_config(auto_sync=False, auto_backup=True))

        assert scheduler._sync_auto_enabled is False
        assert scheduler._backup_auto_enabled is True
        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._backup_lead_timer.isActive() is True

    def test_both_enabled(self, scheduler: Scheduler) -> None:
        scheduler.configure(_basic_config(auto_sync=True, auto_backup=True))

        assert scheduler._sync_auto_enabled is True
        assert scheduler._backup_auto_enabled is True
        assert scheduler._sync_lead_timer.isActive() is True
        assert scheduler._backup_lead_timer.isActive() is True

    def test_zero_interval_treated_as_disabled(self, scheduler: Scheduler) -> None:
        # An interval of 0 hours must NOT arm the timer even with auto_*_enabled=True.
        cfg = SchedulerConfig(
            auto_sync_enabled=True,
            sync_interval_hours=0,
            auto_backup_enabled=True,
            auto_backup_interval_hours=0,
        )
        scheduler.configure(cfg)

        assert scheduler._sync_auto_enabled is False
        assert scheduler._backup_auto_enabled is False
        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._backup_lead_timer.isActive() is False

    def test_overdue_last_sync_arms_zero_lead_in(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Previous sync 10 hours ago, interval is 1 hour → overdue.
        monkeypatch.setattr("src.services.scheduler.time.time", lambda: 100_000.0)
        scheduler.configure(_basic_config(auto_sync=True, sync_hours=1), last_sync_ts=100_000 - 36000)

        assert scheduler._sync_auto_enabled is True
        # Lead-in must be active but ready to fire (delay clamped to 0).
        assert scheduler._sync_lead_timer.isActive() is True

    def test_reconfigure_stops_old_timers_before_rearming(
        self,
        scheduler: Scheduler,
    ) -> None:
        scheduler.configure(_basic_config(auto_sync=True, auto_backup=True))
        assert scheduler._sync_lead_timer.isActive() is True
        assert scheduler._backup_lead_timer.isActive() is True

        # Reconfigure with everything off — both timers must end stopped.
        scheduler.configure(_basic_config(auto_sync=False, auto_backup=False))

        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._backup_lead_timer.isActive() is False
        assert scheduler._sync_timer.isActive() is False
        assert scheduler._backup_timer.isActive() is False


class TestStartStop:
    def test_start_delegates_to_configure(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[tuple[Any, int, int]] = []
        monkeypatch.setattr(
            scheduler,
            "configure",
            lambda cfg, last_sync_ts=0, last_backup_ts=0: seen.append((cfg, last_sync_ts, last_backup_ts)),
        )

        cfg = _basic_config(auto_sync=True)
        scheduler.start(cfg, last_sync_ts=11, last_backup_ts=22)

        assert len(seen) == 1
        assert seen[0] == (cfg, 11, 22)

    def test_stop_disables_auto_flags_and_stops_all_timers(
        self,
        scheduler: Scheduler,
    ) -> None:
        scheduler.configure(_basic_config(auto_sync=True, auto_backup=True))

        scheduler.stop()

        assert scheduler._sync_auto_enabled is False
        assert scheduler._backup_auto_enabled is False
        assert scheduler._sync_lead_timer.isActive() is False
        assert scheduler._sync_timer.isActive() is False
        assert scheduler._backup_lead_timer.isActive() is False
        assert scheduler._backup_timer.isActive() is False


# ──────────────────────────────────────────────────────────────────────────
# Repeating-timer hand-off (_start_repeating_*)
# ──────────────────────────────────────────────────────────────────────────


class TestStartRepeatingTimers:
    def test_sync_repeating_timer_arms_when_enabled(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler, "_on_sync_timer", lambda: called.append(True))
        scheduler._sync_auto_enabled = True
        # Set a non-zero interval so QTimer.start() arms a future fire.
        scheduler._sync_timer.setInterval(60_000)
        assert scheduler._sync_timer.isActive() is False

        scheduler._start_repeating_sync_timer()

        assert called == [True]
        assert scheduler._sync_timer.isActive() is True

    def test_sync_repeating_timer_skipped_when_disabled(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler, "_on_sync_timer", lambda: called.append(True))
        scheduler._sync_auto_enabled = False

        scheduler._start_repeating_sync_timer()

        assert called == []
        assert scheduler._sync_timer.isActive() is False

    def test_backup_repeating_timer_arms_when_enabled(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler, "_on_backup_timer", lambda: called.append(True))
        scheduler._backup_auto_enabled = True
        scheduler._backup_timer.setInterval(120_000)

        scheduler._start_repeating_backup_timer()

        assert called == [True]
        assert scheduler._backup_timer.isActive() is True

    def test_backup_repeating_timer_skipped_when_disabled(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called = []
        monkeypatch.setattr(scheduler, "_on_backup_timer", lambda: called.append(True))
        scheduler._backup_auto_enabled = False

        scheduler._start_repeating_backup_timer()

        assert called == []
        assert scheduler._backup_timer.isActive() is False

    def test_sync_repeating_timer_does_not_double_start_if_already_active(
        self,
        scheduler: Scheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(scheduler, "_on_sync_timer", lambda: None)
        scheduler._sync_auto_enabled = True
        scheduler._sync_timer.setInterval(60_000)
        scheduler._sync_timer.start()  # already armed
        already_active = scheduler._sync_timer.isActive()

        scheduler._start_repeating_sync_timer()

        # Still active, no double-start error.
        assert scheduler._sync_timer.isActive() == already_active is True


# ──────────────────────────────────────────────────────────────────────────
# Shutdown
# ──────────────────────────────────────────────────────────────────────────


class TestShutdown:
    def test_no_op_when_no_threads(self, scheduler: Scheduler) -> None:
        # No worker / backup threads attached — should run cleanly.
        scheduler.shutdown(timeout_ms=10)

        # And both auto flags must be disabled afterwards.
        assert scheduler._sync_auto_enabled is False
        assert scheduler._backup_auto_enabled is False

    def test_cancels_workers_and_waits_for_threads(
        self,
        scheduler: Scheduler,
    ) -> None:
        sync_worker = _CancellableWorker()
        backup_worker = _CancellableWorker()
        sync_thread = _FakeQThread(running=True, wait_returns=True)
        backup_thread = _FakeQThread(running=True, wait_returns=True)

        scheduler._worker = sync_worker
        scheduler._backup_worker = backup_worker
        scheduler._worker_thread = sync_thread  # type: ignore[assignment]
        scheduler._backup_thread = backup_thread  # type: ignore[assignment]

        scheduler.shutdown(timeout_ms=500)

        assert sync_worker.cancel_calls == 1
        assert backup_worker.cancel_calls == 1
        # ``wait()`` was called for both threads with the requested timeout first.
        assert 500 in sync_thread.wait_calls
        assert 500 in backup_thread.wait_calls
        # Happy path → no force-quit needed.
        assert sync_thread.quit_calls == 0
        assert backup_thread.quit_calls == 0

    def test_force_quits_after_timeout(self, scheduler: Scheduler) -> None:
        # Thread refuses to finish in time → wait() returns False.
        sync_thread = _FakeQThread(running=True, wait_returns=False)
        scheduler._worker = _CancellableWorker()
        scheduler._worker_thread = sync_thread  # type: ignore[assignment]

        scheduler.shutdown(timeout_ms=10)

        # Force-quit fired and a second wait was issued.
        assert sync_thread.quit_calls >= 1
        assert sync_thread.wait_calls == [10, 2000]

    def test_shutdown_skips_threads_that_are_not_running(
        self,
        scheduler: Scheduler,
    ) -> None:
        already_finished = _FakeQThread(running=False)
        scheduler._worker = _CancellableWorker()
        scheduler._worker_thread = already_finished  # type: ignore[assignment]

        scheduler.shutdown(timeout_ms=50)

        # cancel() must not be called for already-finished threads, and the
        # scheduler must not even try to wait on them.
        assert scheduler._worker.cancel_calls == 0
        assert already_finished.wait_calls == []


# ──────────────────────────────────────────────────────────────────────────
# is_running / last_sync properties
# ──────────────────────────────────────────────────────────────────────────


class TestSchedulerProperties:
    def test_is_running_reflects_internal_flag(self, scheduler: Scheduler) -> None:
        assert scheduler.is_running is False
        scheduler._running = True
        assert scheduler.is_running is True

    def test_last_sync_starts_none(self, scheduler: Scheduler) -> None:
        assert scheduler.last_sync is None

    def test_last_sync_set_after_finished(self, scheduler: Scheduler) -> None:
        scheduler._on_sync_finished({})
        assert scheduler.last_sync is not None
        assert scheduler.last_sync > 0
