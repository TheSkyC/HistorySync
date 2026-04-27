# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from src.models.app_config import SchedulerConfig
from src.services.scheduler import BackupWorker, Scheduler, SyncWorker


class _FakeExtractorManager:
    def __init__(self, results=None, raises: Exception | None = None):
        self.results = results if results is not None else {"chrome": 3}
        self.raises = raises
        self.calls = []

    def run_extraction(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.results


class _FakeWebDav:
    def __init__(self, configured=True, auto_backup=True, sync_result=None, sync_raises: Exception | None = None):
        self._configured = configured
        self.auto_backup_enabled = auto_backup
        self.sync_result = sync_result if sync_result is not None else SimpleNamespace(success=True, message="ok")
        self.sync_raises = sync_raises
        self.sync_calls = []

    def is_configured(self):
        return self._configured

    def sync(self, **kwargs):
        self.sync_calls.append(kwargs)
        if self.sync_raises is not None:
            raise self.sync_raises
        return self.sync_result


class _FakeThread:
    def __init__(self, running: bool):
        self._running = running

    def isRunning(self):
        return self._running


class TestSyncWorkerContract:
    def test_worker_emits_finished_and_optional_webdav_sync(self):
        em = _FakeExtractorManager(results={"chrome": 2})
        wdav = _FakeWebDav(configured=True, auto_backup=True)
        worker = SyncWorker(em, wdav, browser_types=["chrome"], force_full=True)

        finished = []
        progress = []
        errors = []
        worker.finished.connect(finished.append)
        worker.progress.connect(lambda bt, status, count: progress.append((bt, status, count)))
        worker.error.connect(errors.append)

        worker.run()

        assert finished == [{"chrome": 2}]
        assert errors == []
        assert len(em.calls) == 1
        assert em.calls[0]["browser_types"] == ["chrome"]
        assert em.calls[0]["force_full"] is True
        assert len(wdav.sync_calls) == 1

    def test_worker_skips_result_signals_when_cancelled_before_run(self):
        em = _FakeExtractorManager(results={"chrome": 1})
        worker = SyncWorker(em)
        worker.cancel()

        finished = []
        errors = []
        worker.finished.connect(finished.append)
        worker.error.connect(errors.append)

        worker.run()

        assert finished == []
        assert errors == []

    def test_worker_emits_error_on_unhandled_exception(self):
        em = _FakeExtractorManager(raises=RuntimeError("extract boom"))
        worker = SyncWorker(em)

        finished = []
        errors = []
        worker.finished.connect(finished.append)
        worker.error.connect(errors.append)

        worker.run()

        assert finished == []
        assert errors == ["extract boom"]


class TestBackupWorkerContract:
    def test_backup_worker_emits_finished_on_success(self):
        wdav = _FakeWebDav(sync_result=SimpleNamespace(success=True, message="uploaded"))
        worker = BackupWorker(wdav)

        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished == [(True, "uploaded")]

    def test_backup_worker_emits_failure_on_exception(self):
        wdav = _FakeWebDav(sync_raises=RuntimeError("network down"))
        worker = BackupWorker(wdav)

        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished == [(False, "network down")]

    def test_backup_worker_no_signal_when_cancelled(self):
        wdav = _FakeWebDav()
        worker = BackupWorker(wdav)
        worker.cancel()

        finished = []
        worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

        worker.run()

        assert finished == []


class TestSchedulerContract:
    def test_calc_first_interval_for_never_ran_waits_full_interval(self):
        s = Scheduler(extractor_manager=SimpleNamespace())
        assert s._calc_first_interval_ms(12_000, None) == 12_000

    def test_calc_first_interval_negative_when_overdue(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        monkeypatch.setattr("src.services.scheduler.time.time", lambda: 10_000.0)
        # last sync is 20 seconds ago, interval is 5 seconds -> overdue by 15s
        assert s._calc_first_interval_ms(5_000, 9_980) < 0

    def test_trigger_now_skips_when_running(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        s._running = True

        called = []
        monkeypatch.setattr(s, "_run_sync", lambda *a, **k: called.append(True))

        s.trigger_now()

        assert called == []

    def test_trigger_now_skips_when_thread_still_running(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        s._running = False
        s._worker_thread = _FakeThread(running=True)

        called = []
        monkeypatch.setattr(s, "_run_sync", lambda *a, **k: called.append(True))

        s.trigger_now()

        assert called == []

    def test_trigger_browser_invokes_single_browser_sync(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        s._running = False
        s._worker_thread = None

        calls = []
        monkeypatch.setattr(s, "_run_sync", lambda **kwargs: calls.append(kwargs))

        s.trigger_browser("firefox")

        assert calls == [{"browser_types": ["firefox"]}]

    def test_trigger_full_resync_sets_force_full(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        s._running = False
        s._worker_thread = None

        calls = []
        monkeypatch.setattr(s, "_run_sync", lambda **kwargs: calls.append(kwargs))

        s.trigger_full_resync(browser_types=["chrome"])

        assert calls == [{"browser_types": ["chrome"], "force_full": True}]

    def test_run_backup_is_guarded_when_webdav_not_configured(self):
        s = Scheduler(extractor_manager=SimpleNamespace(), webdav_service=_FakeWebDav(configured=False))

        started = []
        s.backup_started.connect(lambda: started.append(True))

        s._run_backup()

        assert started == []
        assert s._backup_running is False

    def test_configure_arms_timers_with_single_shot_leadins(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())

        sync_delays = []
        backup_delays = []
        monkeypatch.setattr(s, "_schedule_sync_lead_in", sync_delays.append)
        monkeypatch.setattr(s, "_schedule_backup_lead_in", backup_delays.append)

        cfg = SchedulerConfig(
            auto_sync_enabled=True,
            sync_interval_hours=1,
            auto_backup_enabled=True,
            auto_backup_interval_hours=2,
        )

        s.configure(cfg, last_sync_ts=0, last_backup_ts=0)

        # First run for both timers should schedule lead-ins with positive delays.
        assert len(sync_delays) == 1
        assert len(backup_delays) == 1
        assert sync_delays[0] > 0
        assert backup_delays[0] > 0

    def test_stop_cancels_lead_in_timers(self):
        s = Scheduler(extractor_manager=SimpleNamespace())

        cfg = SchedulerConfig(
            auto_sync_enabled=True,
            sync_interval_hours=1,
            auto_backup_enabled=True,
            auto_backup_interval_hours=2,
        )
        s.configure(cfg, last_sync_ts=0, last_backup_ts=0)

        s.stop()

        assert s._sync_lead_timer.isActive() is False
        assert s._backup_lead_timer.isActive() is False

    def test_stale_sync_lead_in_callback_is_ignored_after_disable(self, monkeypatch):
        s = Scheduler(extractor_manager=SimpleNamespace())
        s._sync_auto_enabled = False

        calls = []
        monkeypatch.setattr(s, "_on_sync_timer", lambda: calls.append("sync"))

        s._start_repeating_sync_timer()

        assert calls == []
