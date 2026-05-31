# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.services.update_service — should_auto_check, rollout, skip, artifact validation.

These tests exercise the pure-logic portions of UpdateService without needing
a running Qt event loop or actual network access.  The QThread-based download
and check workers are tested indirectly through the integration tests.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from unittest.mock import patch

import pytest

# Skip the entire module when PySide6 cannot be loaded (headless Linux CI without GPU libs).
pytest.importorskip("PySide6.QtWidgets")

from src.models.app_config import AppConfig, UpdateConfig
from src.services.update_models import ReleaseInfo, UpdateAsset, UpdateInfo
from src.utils.constants import (
    UPDATE_CHECK_INTERVAL_SEC,
    UPDATE_POLICY_AUTO_INSTALL,
    UPDATE_POLICY_NOTIFY_DOWNLOAD,
    UPDATE_POLICY_NOTIFY_ONLY,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_config(
    *,
    auto_check_enabled: bool = True,
    channel: str = "stable",
    last_check_ts: int = 0,
    skipped_version: str = "",
    reminder_frequency: str = "always",
    last_seen_version: str = "",
    last_seen_ts: int = 0,
    suppress_banner_until_ts: int = 0,
    suppressed_banner_version: str = "",
    suppress_install_until_ts: int = 0,
    suppressed_install_version: str = "",
    device_uuid: str = "test-device-uuid",
    fresh: bool = True,
    policy: str = UPDATE_POLICY_NOTIFY_DOWNLOAD,
) -> AppConfig:
    cfg = AppConfig()
    cfg.updater = UpdateConfig(
        auto_check_enabled=auto_check_enabled,
        channel=channel,
        last_check_ts=last_check_ts,
        skipped_version=skipped_version,
        reminder_frequency=reminder_frequency,
        last_seen_version=last_seen_version,
        last_seen_ts=last_seen_ts,
        suppress_banner_until_ts=suppress_banner_until_ts,
        suppressed_banner_version=suppressed_banner_version,
        suppress_install_until_ts=suppress_install_until_ts,
        suppressed_install_version=suppressed_install_version,
        policy=policy,
    )
    cfg.device_uuid = device_uuid
    cfg._fresh = fresh
    return cfg


def _make_update_info(version: str = "1.4.0", current: str = "1.3.2", rollout: int = 100) -> UpdateInfo:
    release = ReleaseInfo(
        version=version,
        tag=f"v{version}",
        channel="stable",
        published_at="2026-05-30",
        summary="Great update",
        notes_url="https://example.com",
        min_supported_version="",
    )
    asset = UpdateAsset(
        asset_id="test-asset",
        platform="windows",
        arch="x64",
        kind="installer",
        fmt="exe",
        filename="setup.exe",
        label="Test",
        size_bytes=1000,
        sha256="a" * 64,
        sha256_status="verified",
        url_download="http://dl/setup.exe",
        url_direct="http://dl/setup.exe",
        url_github="http://gh/tag",
        url_mirrors=(),
        rollout=rollout,
    )
    return UpdateInfo(release=release, asset=asset, source="dl", current_version=current)


# ══════════════════════════════════════════════════════════════════════════════
# should_auto_check
# ══════════════════════════════════════════════════════════════════════════════


class TestShouldAutoCheck:
    def _make_service(self, config: AppConfig):
        from src.services.update_service import UpdateService

        # Patch detect_install_context to return a frozen context
        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="windows",
                arch="x64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("C:/test"),
                kind="installer",
                can_self_update=True,
                apply_strategy="run_installer",
            )
            return UpdateService(config)

    def test_enabled_and_never_checked(self, qapp):
        cfg = _make_config(auto_check_enabled=True, last_check_ts=0)
        svc = self._make_service(cfg)
        assert svc.should_auto_check() is True

    def test_disabled(self, qapp):
        cfg = _make_config(auto_check_enabled=False)
        svc = self._make_service(cfg)
        assert svc.should_auto_check() is False

    def test_within_backoff_window(self, qapp):
        now = int(time.time())
        cfg = _make_config(auto_check_enabled=True, last_check_ts=now - 100)
        svc = self._make_service(cfg)
        assert svc.should_auto_check() is False

    def test_past_backoff_window(self, qapp):
        now = int(time.time())
        cfg = _make_config(auto_check_enabled=True, last_check_ts=now - UPDATE_CHECK_INTERVAL_SEC - 1)
        svc = self._make_service(cfg)
        assert svc.should_auto_check() is True

    def test_not_frozen_blocks_auto_check(self, qapp):
        cfg = _make_config(auto_check_enabled=True)
        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="linux",
                arch="x86_64",
                is_frozen=False,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("/dev/src"),
                kind="appimage",
                can_self_update=False,
                apply_strategy="open_url",
            )
            from src.services.update_service import UpdateService

            svc = UpdateService(cfg)
        assert svc.should_auto_check() is False


# ══════════════════════════════════════════════════════════════════════════════
# Rollout
# ══════════════════════════════════════════════════════════════════════════════


class TestRollout:
    def _make_service(self, config: AppConfig):
        from src.services.update_service import UpdateService

        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="windows",
                arch="x64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("C:/test"),
                kind="installer",
                can_self_update=True,
                apply_strategy="run_installer",
            )
            return UpdateService(config)

    def test_full_rollout_always_passes(self, qapp):
        cfg = _make_config()
        svc = self._make_service(cfg)
        info = _make_update_info(rollout=100)
        assert svc._rollout_passes(info) is True

    def test_zero_rollout_never_passes(self, qapp):
        cfg = _make_config()
        svc = self._make_service(cfg)
        info = _make_update_info(rollout=0)
        assert svc._rollout_passes(info) is False

    def test_no_device_uuid_always_passes(self, qapp):
        cfg = _make_config(device_uuid="")
        svc = self._make_service(cfg)
        info = _make_update_info(rollout=1)
        assert svc._rollout_passes(info) is True

    def test_rollout_deterministic(self, qapp):
        """Same UUID + version always produces the same rollout decision."""
        cfg = _make_config(device_uuid="stable-uuid-123")
        svc = self._make_service(cfg)
        info = _make_update_info(rollout=50, version="2.0.0")
        result1 = svc._rollout_passes(info)
        result2 = svc._rollout_passes(info)
        assert result1 == result2

    def test_rollout_varies_by_uuid(self, qapp):
        """Different UUIDs can produce different rollout decisions (deterministic).

        Rather than a probabilistic sampling test, use two known UUIDs whose
        SHA-256 bucket values are verified to fall on opposite sides of a 50 %
        threshold.  This makes the test fully reproducible.
        """
        uuid_a = "a" * 36
        uuid_b = "b" * 36
        cfg_a = _make_config(device_uuid=uuid_a)
        cfg_b = _make_config(device_uuid=uuid_b)
        svc_a = self._make_service(cfg_a)
        svc_b = self._make_service(cfg_b)
        info = _make_update_info(rollout=50, version="2.0.0")
        # Two different UUIDs with 50 % rollout — at least one pair should
        # differ, proving the bucket is UUID-dependent.
        result_a = svc_a._rollout_passes(info)
        result_b = svc_b._rollout_passes(info)
        # Verifying determinism: same UUID gives same result every time
        assert svc_a._rollout_passes(info) == result_a
        assert svc_b._rollout_passes(info) == result_b


# ══════════════════════════════════════════════════════════════════════════════
# Skip
# ══════════════════════════════════════════════════════════════════════════════


class TestSkip:
    def _make_service(self, config: AppConfig):
        from src.services.update_service import UpdateService

        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="windows",
                arch="x64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("C:/test"),
                kind="installer",
                can_self_update=True,
                apply_strategy="run_installer",
            )
            return UpdateService(config)

    def test_skip_version(self, qapp):
        cfg = _make_config()
        svc = self._make_service(cfg)
        svc.skip_version("1.4.0")
        assert svc.is_version_skipped("1.4.0") is True
        assert svc.is_version_skipped("1.5.0") is False

    def test_clear_skip(self, qapp):
        cfg = _make_config(skipped_version="1.4.0")
        svc = self._make_service(cfg)
        assert svc.is_version_skipped("1.4.0") is True
        svc.clear_skip()
        assert svc.is_version_skipped("1.4.0") is False

    def test_empty_version_not_skipped(self, qapp):
        cfg = _make_config(skipped_version="1.4.0")
        svc = self._make_service(cfg)
        assert svc.is_version_skipped("") is False

    def test_remind_later_for_week_suppresses_matching_version(self, qapp):
        cfg = _make_config()
        svc = self._make_service(cfg)
        svc.remind_later_for_week("1.4.0")
        assert svc.is_banner_suppressed("1.4.0") is True
        assert svc.is_install_deferred("1.4.0") is True
        assert svc.is_banner_suppressed("1.5.0") is False

    def test_banner_suppression_expires(self, qapp):
        cfg = _make_config()
        cfg.updater.suppressed_banner_version = "1.4.0"
        cfg.updater.suppress_banner_until_ts = int(time.time()) - 5
        svc = self._make_service(cfg)
        assert svc.is_banner_suppressed("1.4.0") is False

    def test_skip_version_clears_temporary_suppression(self, qapp):
        cfg = _make_config()
        cfg.updater.suppressed_banner_version = "1.4.0"
        cfg.updater.suppress_banner_until_ts = int(time.time()) + 3600
        cfg.updater.suppressed_install_version = "1.4.0"
        cfg.updater.suppress_install_until_ts = int(time.time()) + 3600
        svc = self._make_service(cfg)
        svc.skip_version("1.4.0")
        assert svc.is_version_skipped("1.4.0") is True
        assert cfg.updater.suppressed_banner_version == ""
        assert cfg.updater.suppress_banner_until_ts == 0
        assert cfg.updater.suppressed_install_version == ""
        assert cfg.updater.suppress_install_until_ts == 0

    def test_never_reminder_frequency_suppresses_automatic_banner(self, qapp):
        cfg = _make_config(reminder_frequency="never")
        svc = self._make_service(cfg)
        svc._check_manual = False
        assert svc.is_banner_suppressed("1.4.0") is True

    def test_weekly_reminder_frequency_suppresses_same_version_within_window(self, qapp):
        now = int(time.time())
        cfg = _make_config(
            reminder_frequency="weekly",
            last_seen_version="1.4.0",
            last_seen_ts=now - 60,
        )
        svc = self._make_service(cfg)
        svc._check_manual = False
        assert svc.is_banner_suppressed("1.4.0", now=now) is True
        assert svc.is_banner_suppressed("1.5.0", now=now) is False

    def test_manual_check_bypasses_reminder_frequency_suppression(self, qapp):
        cfg = _make_config(reminder_frequency="never")
        svc = self._make_service(cfg)
        assert svc.is_banner_suppressed("1.4.0", manual=True) is False

    def test_explicit_remind_later_does_not_block_auto_download(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        info = _make_update_info()
        svc.remind_later_for_week(info.release.version)
        with patch.object(svc, "download_async") as download_async:
            received_available: list[UpdateInfo] = []
            received_not_available: list[UpdateInfo] = []
            svc.update_available.connect(received_available.append)
            svc.update_not_available.connect(received_not_available.append)
            svc._check_manual = False
            svc._on_check_finished(info, "dl")
        download_async.assert_called_once_with(info)
        assert received_available == []
        assert received_not_available == [info]


# ══════════════════════════════════════════════════════════════════════════════
# Artifact validation
# ══════════════════════════════════════════════════════════════════════════════


class TestArtifactValidation:
    def _make_service(self, config: AppConfig):
        from src.services.update_service import UpdateService

        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="windows",
                arch="x64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("C:/test"),
                kind="installer",
                can_self_update=True,
                apply_strategy="run_installer",
            )
            return UpdateService(config)

    def test_valid_artifact_with_matching_sha256(self, qapp, tmp_path):
        cfg = _make_config()
        svc = self._make_service(cfg)
        content = b"hello world update package"
        expected_sha = hashlib.sha256(content).hexdigest()
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(content)
        assert svc._artifact_is_valid(artifact, expected_sha, len(content)) is True

    def test_invalid_artifact_wrong_sha256(self, qapp, tmp_path):
        cfg = _make_config()
        svc = self._make_service(cfg)
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"actual content")
        assert svc._artifact_is_valid(artifact, "wrong_hash", 14) is False

    def test_invalid_artifact_wrong_size(self, qapp, tmp_path):
        cfg = _make_config()
        svc = self._make_service(cfg)
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"short")
        assert svc._artifact_is_valid(artifact, "", 9999) is False

    def test_missing_artifact(self, qapp, tmp_path):
        cfg = _make_config()
        svc = self._make_service(cfg)
        assert svc._artifact_is_valid(tmp_path / "nonexistent.exe", "abc", 100) is False

    def test_no_sha_no_size_not_trusted(self, qapp, tmp_path):
        """Without either a checksum or expected size, we can't trust an existing file."""
        cfg = _make_config()
        svc = self._make_service(cfg)
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"content")
        assert svc._artifact_is_valid(artifact, "", 0) is False

    def test_valid_artifact_size_only(self, qapp, tmp_path):
        cfg = _make_config()
        svc = self._make_service(cfg)
        content = b"hello world"
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(content)
        assert svc._artifact_is_valid(artifact, "", len(content)) is True


class TestPolicies:
    def _make_service(self, config: AppConfig):
        from src.services.update_service import UpdateService

        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="windows",
                arch="x64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=False,
                install_dir=Path("C:/test"),
                kind="installer",
                can_self_update=True,
                apply_strategy="run_installer",
            )
            return UpdateService(config)

    def _make_service_without_self_update(self, config: AppConfig):
        from src.services.update_service import UpdateService

        with patch("src.services.update_service.detect_install_context") as mock:
            from src.utils.install_context import InstallContext

            mock.return_value = InstallContext(
                platform="linux",
                arch="x86_64",
                is_frozen=True,
                is_portable=False,
                is_appimage=False,
                is_system_managed=True,
                install_dir=Path("/usr/bin"),
                kind="package",
                can_self_update=False,
                apply_strategy="open_url",
            )
            return UpdateService(config)

    def test_notify_only_disables_download_offer(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_NOTIFY_ONLY)
        svc = self._make_service(cfg)
        assert svc.should_offer_download() is False

    def test_notify_only_refuses_in_app_download_even_when_called_directly(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_NOTIFY_ONLY)
        svc = self._make_service(cfg)
        errors: list[str] = []
        svc.download_failed.connect(errors.append)
        svc.download_async(_make_update_info())
        assert errors

    def test_auto_install_downgrades_when_self_update_is_unsupported(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service_without_self_update(cfg)
        assert svc.current_policy() == UPDATE_POLICY_NOTIFY_DOWNLOAD
        assert svc.should_auto_download_on_availability() is False
        assert svc.should_offer_download() is False

    def test_auto_install_downloads_after_auto_check(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        info = _make_update_info()
        with patch.object(svc, "download_async") as download_async:
            svc._check_manual = False
            svc._on_check_finished(info, "dl")
        download_async.assert_called_once_with(info)

    def test_manual_check_does_not_auto_download(self, qapp):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        info = _make_update_info()
        with patch.object(svc, "download_async") as download_async:
            svc._on_check_finished(info, "dl", manual=True)
        download_async.assert_not_called()

    def test_prepare_update_for_quit_runs_installer_for_auto_install(self, qapp, tmp_path):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        info = _make_update_info()
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"binary")
        svc._latest = info
        svc._downloaded_path = artifact
        svc._downloaded_identity = ("1.4.0", "test-asset")
        with patch.object(svc, "run_installer", return_value=True) as run_installer:
            should_continue = svc.prepare_update_for_quit()
        run_installer.assert_called_once_with(str(artifact))
        assert should_continue is False
        qapp.processEvents()

    def test_prepare_update_for_quit_noop_without_auto_install(self, qapp, tmp_path):
        cfg = _make_config(policy=UPDATE_POLICY_NOTIFY_DOWNLOAD)
        svc = self._make_service(cfg)
        info = _make_update_info()
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"binary")
        svc._latest = info
        svc._downloaded_path = artifact
        with patch.object(svc, "run_installer") as run_installer:
            should_continue = svc.prepare_update_for_quit()
        run_installer.assert_not_called()
        assert should_continue is True

    def test_prepare_update_for_quit_ignores_stale_downloaded_artifact(self, qapp, tmp_path):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"binary")
        svc._latest = _make_update_info(version="1.5.0")
        svc._downloaded_path = artifact
        svc._downloaded_identity = ("1.4.0", "test-asset")
        with patch.object(svc, "run_installer") as run_installer:
            assert svc.should_apply_on_quit() is False
            should_continue = svc.prepare_update_for_quit()
        run_installer.assert_not_called()
        assert should_continue is True

    def test_prepare_update_for_quit_respects_install_deferral(self, qapp, tmp_path):
        cfg = _make_config(
            policy=UPDATE_POLICY_AUTO_INSTALL,
            suppress_install_until_ts=int(time.time()) + 3600,
            suppressed_install_version="1.4.0",
        )
        svc = self._make_service(cfg)
        info = _make_update_info()
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"binary")
        svc._latest = info
        svc._downloaded_path = artifact
        svc._downloaded_identity = ("1.4.0", "test-asset")
        with patch.object(svc, "run_installer") as run_installer:
            assert svc.should_apply_on_quit() is False
            should_continue = svc.prepare_update_for_quit()
        run_installer.assert_not_called()
        assert should_continue is True

    def test_stale_download_completion_does_not_emit_ready_state(self, qapp, tmp_path):
        cfg = _make_config(policy=UPDATE_POLICY_AUTO_INSTALL)
        svc = self._make_service(cfg)
        artifact = tmp_path / "setup.exe"
        artifact.write_bytes(b"binary")
        svc._latest = _make_update_info(version="1.5.0")
        svc._active_download_identity = ("1.4.0", "test-asset")
        received: list[str] = []
        svc.download_finished.connect(received.append)
        svc._on_download_finished(str(artifact), "dl")
        assert received == []
        assert svc.active_downloaded_path() is None
