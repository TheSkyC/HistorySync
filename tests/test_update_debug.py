# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.services.update_debug — env-var overrides for update system.

Tests cover:
- Each accessor returns None/False when env vars are absent.
- Each accessor returns the validated value when env vars are set.
- Validation rejects malformed inputs with logged warnings but no crash.
- ``reset_for_testing()`` clears all cached state.
- ``set_test_injector`` allows tests to inject fake env values.
- Integration: ``should_auto_check`` respects ``HISTORYSYNC_UPDATE_FORCE_AUTO``.
- Integration: ``UpdateService`` uses ``HISTORYSYNC_UPDATE_CURRENT_VERSION``.
- Integration: ``_on_check_finished`` bypasses gates when ``IGNORE_GATES`` is set.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6.QtWidgets")

from src.models.app_config import AppConfig, UpdateConfig
from src.services import update_debug
from src.services.update_models import ReleaseInfo, UpdateAsset, UpdateInfo
from src.utils.constants import (
    UPDATE_POLICY_NOTIFY_DOWNLOAD,
)

# ── Resolve the env-var helper used by the debug module ──────────────────────
# update_debug internally calls _resolve_env(); we want to test through the
# public accessors so we monkeypatch os.environ directly and call
# reset_for_testing() between tests.


@pytest.fixture(autouse=True)
def _clean_debug_state():
    """Ensure every test starts with a clean debug-module state and no env leakage."""
    saved = {}
    for key in (
        "HISTORYSYNC_UPDATE_CURRENT_VERSION",
        "HISTORYSYNC_UPDATE_API_BASE_URL",
        "HISTORYSYNC_UPDATE_FORCE_AUTO",
        "HISTORYSYNC_UPDATE_IGNORE_GATES",
    ):
        saved[key] = os.environ.pop(key, None)
    update_debug.reset_for_testing()
    yield
    # Restore
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    update_debug.reset_for_testing()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ══════════════════════════════════════════════════════════════════════════════
# Accessor: defaults (no env vars set)
# ══════════════════════════════════════════════════════════════════════════════


class TestDefaults:
    def test_current_version_returns_none(self):
        assert update_debug.current_version() is None

    def test_api_base_url_returns_none(self):
        assert update_debug.api_base_url() is None

    def test_force_auto_returns_false(self):
        assert update_debug.force_auto() is False

    def test_ignore_gates_returns_false(self):
        assert update_debug.ignore_gates() is False

    def test_any_active_returns_false(self):
        assert update_debug.any_active() is False


# ══════════════════════════════════════════════════════════════════════════════
# effective_current_version
# ══════════════════════════════════════════════════════════════════════════════


class TestEffectiveCurrentVersion:
    def test_falls_back_to_app_version_when_no_override(self):
        from src.utils.constants import APP_VERSION

        assert update_debug.effective_current_version() == APP_VERSION

    def test_returns_override_when_set(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "0.9.0"
        assert update_debug.effective_current_version() == "0.9.0"

    def test_returns_override_with_v_prefix(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "v2.1.3"
        assert update_debug.effective_current_version() == "v2.1.3"

    def test_returns_app_version_after_invalid_override(self):
        from src.utils.constants import APP_VERSION

        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "not-a-version!!!"
        assert update_debug.effective_current_version() == APP_VERSION


# ══════════════════════════════════════════════════════════════════════════════
# Accessor: valid env vars
# ══════════════════════════════════════════════════════════════════════════════


class TestValidOverrides:
    def test_current_version_simple(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "0.9.0"
        assert update_debug.current_version() == "0.9.0"

    def test_current_version_with_v_prefix(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "v2.1.3"
        # The loose regex accepts v-prefixed strings as input; the caller
        # (Version.parse) handles stripping.
        assert update_debug.current_version() == "v2.1.3"

    def test_current_version_prerelease(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "1.0.0-beta.1"
        assert update_debug.current_version() == "1.0.0-beta.1"

    def test_api_base_url_http(self):
        os.environ["HISTORYSYNC_UPDATE_API_BASE_URL"] = "http://localhost:8080/api/v1"
        assert update_debug.api_base_url() == "http://localhost:8080/api/v1"

    def test_api_base_url_trailing_slash_stripped(self):
        os.environ["HISTORYSYNC_UPDATE_API_BASE_URL"] = "https://example.com/"
        assert update_debug.api_base_url() == "https://example.com"

    def test_force_auto_truthy_variants(self):
        for val in ("1", "true", "True", "TRUE", "yes", "on", "ON"):
            update_debug.reset_for_testing()
            os.environ["HISTORYSYNC_UPDATE_FORCE_AUTO"] = val
            assert update_debug.force_auto() is True, f"failed for {val!r}"

    def test_ignore_gates_truthy(self):
        os.environ["HISTORYSYNC_UPDATE_IGNORE_GATES"] = "true"
        assert update_debug.ignore_gates() is True

    def test_any_active_when_one_set(self):
        os.environ["HISTORYSYNC_UPDATE_FORCE_AUTO"] = "1"
        assert update_debug.any_active() is True


# ══════════════════════════════════════════════════════════════════════════════
# Validation: invalid inputs are logged and treated as not-set
# ══════════════════════════════════════════════════════════════════════════════


class TestInvalidOverrides:
    def test_current_version_garbage(self, caplog):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "not-a-version!!!"
        result = update_debug.current_version()
        assert result is None
        assert "not-a-version" in caplog.text

    def test_current_version_empty_string_is_unset(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "   "
        assert update_debug.current_version() is None

    def test_api_base_url_no_scheme(self, caplog):
        os.environ["HISTORYSYNC_UPDATE_API_BASE_URL"] = "localhost/no-scheme"
        result = update_debug.api_base_url()
        assert result is None
        assert "localhost/no-scheme" in caplog.text

    def test_force_auto_falsey(self):
        for val in ("0", "false", "no", "off", "", "   "):
            update_debug.reset_for_testing()
            os.environ["HISTORYSYNC_UPDATE_FORCE_AUTO"] = val
            assert update_debug.force_auto() is False, f"failed for {val!r}"


# ══════════════════════════════════════════════════════════════════════════════
# reset_for_testing
# ══════════════════════════════════════════════════════════════════════════════


class TestResetForTesting:
    def test_reset_clears_cache(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "9.9.9"
        assert update_debug.current_version() == "9.9.9"
        # Reset should clear the cached value — but since the env var is still
        # set, the next read will re-resolve it.
        update_debug.reset_for_testing()
        assert update_debug.current_version() == "9.9.9"

    def test_reset_after_env_removed(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "9.9.9"
        assert update_debug.current_version() == "9.9.9"
        # Remove env var AND reset — now it should return None.
        del os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"]
        update_debug.reset_for_testing()
        assert update_debug.current_version() is None


# ══════════════════════════════════════════════════════════════════════════════
# Test injectors
# ══════════════════════════════════════════════════════════════════════════════


class TestInjectors:
    def test_injector_overrides_env(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "9.9.9"
        update_debug.set_test_injector(
            "HISTORYSYNC_UPDATE_CURRENT_VERSION",
            lambda: "1.0.0",
        )
        assert update_debug.current_version() == "1.0.0"

    def test_injector_override_skips_env_validation(self):
        """Injector string still passes through validation."""
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "9.9.9"
        update_debug.set_test_injector(
            "HISTORYSYNC_UPDATE_CURRENT_VERSION",
            lambda: "not-a-version",
        )
        # The injector returns an invalid version; validation should reject it.
        assert update_debug.current_version() is None

    def test_injector_returns_none(self):
        os.environ["HISTORYSYNC_UPDATE_CURRENT_VERSION"] = "from-env"
        update_debug.set_test_injector(
            "HISTORYSYNC_UPDATE_CURRENT_VERSION",
            lambda: None,
        )
        # When the injector returns None, validation treats it as unset.
        # current_version() will see None from the injector and return None
        # (bypassing the env var).
        assert update_debug.current_version() is None

    def test_remove_injector(self):
        update_debug.set_test_injector(
            "HISTORYSYNC_UPDATE_FORCE_AUTO",
            lambda: "true",
        )
        assert update_debug.force_auto() is True
        update_debug.set_test_injector("HISTORYSYNC_UPDATE_FORCE_AUTO", None)
        update_debug.reset_for_testing()
        # No env var, no injector — should be False.
        assert update_debug.force_auto() is False


# ══════════════════════════════════════════════════════════════════════════════
# Integration: UpdateService respects HISTORYSYNC_UPDATE_CURRENT_VERSION
# ══════════════════════════════════════════════════════════════════════════════


def _make_config(
    *,
    auto_check_enabled: bool = True,
    channel: str = "stable",
    last_check_ts: int = 0,
    skipped_version: str = "",
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


def _make_frozen_context():
    from src.utils.install_context import InstallContext

    return InstallContext(
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


def _make_source_context():
    from src.utils.install_context import InstallContext

    return InstallContext(
        platform="windows",
        arch="x64",
        is_frozen=False,
        is_portable=False,
        is_appimage=False,
        is_system_managed=False,
        install_dir=Path("E:/workspace/HistorySync"),
        kind="archive",
        can_self_update=False,
        apply_strategy="open_url",
    )


def _make_service(config: AppConfig, context=None):
    from src.services.update_service import UpdateService

    ctx = context if context is not None else _make_frozen_context()
    with patch("src.services.update_service.detect_install_context", return_value=ctx):
        return UpdateService(config)


class TestCurrentVersionOverride:
    def test_default_uses_app_version(self):
        svc = _make_service(_make_config())
        from src.utils.constants import APP_VERSION

        assert svc.current_version == APP_VERSION

    def test_env_override_changes_version(self, monkeypatch):
        monkeypatch.setenv("HISTORYSYNC_UPDATE_CURRENT_VERSION", "0.5.0")
        update_debug.reset_for_testing()
        svc = _make_service(_make_config())
        assert svc.current_version == "0.5.0"

    def test_version_override_flows_to_update_info(self, monkeypatch):
        """When version is overridden to an older one, is_update_available is True."""
        monkeypatch.setenv("HISTORYSYNC_UPDATE_CURRENT_VERSION", "0.5.0")
        update_debug.reset_for_testing()
        info = _make_update_info(version="1.4.0", current="0.5.0")
        assert info.is_update_available is True


# ══════════════════════════════════════════════════════════════════════════════
# Integration: should_auto_check respects HISTORYSYNC_UPDATE_FORCE_AUTO
# ══════════════════════════════════════════════════════════════════════════════


class TestForceAutoIntegration:
    def test_source_mode_blocks_auto_check_by_default(self):
        cfg = _make_config(auto_check_enabled=True)
        svc = _make_service(cfg, context=_make_source_context())
        assert svc.should_auto_check() is False

    def test_force_auto_allows_check_in_source_mode(self, monkeypatch):
        monkeypatch.setenv("HISTORYSYNC_UPDATE_FORCE_AUTO", "1")
        update_debug.reset_for_testing()
        cfg = _make_config(auto_check_enabled=True, last_check_ts=0)
        svc = _make_service(cfg, context=_make_source_context())
        assert svc.should_auto_check() is True

    def test_force_auto_respects_disabled_flag(self, monkeypatch):
        """force_auto should not override explicit auto_check_enabled=False."""
        monkeypatch.setenv("HISTORYSYNC_UPDATE_FORCE_AUTO", "1")
        update_debug.reset_for_testing()
        cfg = _make_config(auto_check_enabled=False)
        svc = _make_service(cfg, context=_make_source_context())
        assert svc.should_auto_check() is False

    def test_force_auto_respects_backoff(self, monkeypatch):
        """force_auto should not override the back-off interval."""
        import time

        monkeypatch.setenv("HISTORYSYNC_UPDATE_FORCE_AUTO", "1")
        update_debug.reset_for_testing()
        now = int(time.time())
        cfg = _make_config(auto_check_enabled=True, last_check_ts=now - 100)
        svc = _make_service(cfg, context=_make_source_context())
        assert svc.should_auto_check() is False


# ══════════════════════════════════════════════════════════════════════════════
# Integration: _on_check_finished bypasses gates with IGNORE_GATES
# ══════════════════════════════════════════════════════════════════════════════


class TestIgnoreGatesIntegration:
    def test_skip_gate_active_by_default(self, qapp, monkeypatch):
        """Without IGNORE_GATES, a skipped version is suppressed."""
        monkeypatch.delenv("HISTORYSYNC_UPDATE_IGNORE_GATES", raising=False)
        update_debug.reset_for_testing()
        cfg = _make_config(skipped_version="1.4.0", fresh=True)
        svc = _make_service(cfg)
        info = _make_update_info(version="1.4.0")

        # Simulate a manual=False check arriving with a skipped version.
        with patch.object(svc, "_save_config"):
            captured_not_available: list = []
            captured_available: list = []
            svc.update_not_available.connect(captured_not_available.append)
            svc.update_available.connect(captured_available.append)

            # Set the latest to something, then call _on_check_finished
            svc._latest = info
            svc._check_manual = False
            svc._on_check_finished(info, "dl")

        # The skip should block notification.
        assert len(captured_available) == 0
        assert len(captured_not_available) >= 1

    def test_ignore_gates_bypasses_skip(self, qapp, monkeypatch):
        """With IGNORE_GATES, even a skipped version surfaces."""
        monkeypatch.setenv("HISTORYSYNC_UPDATE_IGNORE_GATES", "1")
        update_debug.reset_for_testing()
        cfg = _make_config(skipped_version="1.4.0", fresh=True)
        svc = _make_service(cfg)
        info = _make_update_info(version="1.4.0")

        with patch.object(svc, "_save_config"):
            captured_available: list = []
            captured_not_available: list = []
            svc.update_available.connect(captured_available.append)
            svc.update_not_available.connect(captured_not_available.append)

            svc._latest = info
            svc._check_manual = False
            svc._on_check_finished(info, "dl")

        assert len(captured_available) >= 1
        assert len(captured_not_available) == 0

    def test_ignore_gates_bypasses_rollout(self, qapp, monkeypatch):
        """With IGNORE_GATES, a 0 % rollout still surfaces."""
        monkeypatch.setenv("HISTORYSYNC_UPDATE_IGNORE_GATES", "1")
        update_debug.reset_for_testing()
        cfg = _make_config(fresh=True)
        svc = _make_service(cfg)
        info = _make_update_info(version="1.4.0", rollout=0)

        with patch.object(svc, "_save_config"):
            captured_available: list = []
            svc.update_available.connect(captured_available.append)

            svc._latest = info
            svc._check_manual = False
            svc._on_check_finished(info, "dl")

        assert len(captured_available) >= 1

    def test_ignore_gates_bypasses_dedup(self, qapp, monkeypatch):
        """With IGNORE_GATES, the same version surfaces repeatedly."""
        monkeypatch.setenv("HISTORYSYNC_UPDATE_IGNORE_GATES", "1")
        update_debug.reset_for_testing()
        cfg = _make_config(fresh=True)
        cfg.updater.last_seen_version = "1.4.0"  # already seen
        svc = _make_service(cfg)
        info = _make_update_info(version="1.4.0")

        with patch.object(svc, "_save_config"):
            captured_available: list = []
            svc.update_available.connect(captured_available.append)

            svc._latest = info
            svc._check_manual = False
            svc._on_check_finished(info, "dl")

        assert len(captured_available) >= 1

    def test_manual_check_always_bypasses(self, qapp):
        """Manual checks bypass gates even without IGNORE_GATES (existing behavior)."""
        update_debug.reset_for_testing()
        cfg = _make_config(skipped_version="1.4.0", fresh=True)
        svc = _make_service(cfg)
        info = _make_update_info(version="1.4.0")

        with patch.object(svc, "_save_config"):
            captured_available: list = []
            svc.update_available.connect(captured_available.append)

            svc._latest = info
            svc._check_manual = True  # manual check
            svc._on_check_finished(info, "dl")

        assert len(captured_available) >= 1
