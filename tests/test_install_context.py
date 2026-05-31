# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.utils.install_context — platform detection, arch normalization, kind/strategy."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from src.utils.install_context import (
    APPLY_OPEN_FILE,
    APPLY_OPEN_URL,
    APPLY_REVEAL,
    APPLY_RUN_INSTALLER,
    KIND_APPIMAGE,
    KIND_ARCHIVE,
    KIND_DISK_IMAGE,
    KIND_INSTALLER,
    KIND_PACKAGE,
    KIND_PORTABLE,
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    InstallContext,
    _is_system_managed,
    _normalize_arch,
    _resolve_kind,
    _resolve_strategy,
)


class TestNormalizeArch:
    """_normalize_arch: maps platform.machine() to dl API arch tokens."""

    @pytest.mark.parametrize(
        "machine,expected",
        [
            ("AMD64", "x64"),
            ("x86_64", "x64"),
            ("x64", "x64"),
            ("arm64", "arm64"),
            ("aarch64", "arm64"),
            ("x86", "x86"),
            ("i686", "x86"),
            ("", "x64"),
        ],
    )
    def test_windows_arch(self, machine, expected):
        assert _normalize_arch(machine, PLATFORM_WINDOWS) == expected

    @pytest.mark.parametrize(
        "machine,expected",
        [
            ("arm64", "arm64"),
            ("aarch64", "arm64"),
            ("x86_64", "x64"),
            ("", "arm64"),
        ],
    )
    def test_macos_arch(self, machine, expected):
        assert _normalize_arch(machine, PLATFORM_MACOS) == expected

    @pytest.mark.parametrize(
        "machine,expected",
        [
            ("x86_64", "x86_64"),
            ("amd64", "x86_64"),
            ("aarch64", "arm64"),
            ("arm64", "arm64"),
            ("", "x86_64"),
        ],
    )
    def test_linux_arch(self, machine, expected):
        assert _normalize_arch(machine, PLATFORM_LINUX) == expected


class TestIsSystemManaged:
    """_is_system_managed: detect package-manager-owned directories."""

    @pytest.mark.skipif(sys.platform != "linux", reason="POSIX system paths only meaningful on Linux")
    @pytest.mark.parametrize(
        "path,expected",
        [
            (Path("/usr/lib/historysync"), True),
            (Path("/usr/bin"), True),
            (Path("/opt/historysync"), True),
            (Path("/snap/historysync/current"), True),
            (Path("/home/user/HistorySync"), False),
            (Path("/tmp/test"), False),
            (Path("/var/lib/flatpak/app/historysync"), True),
        ],
    )
    def test_various_paths(self, path, expected):
        assert _is_system_managed(path) == expected


class TestResolveKind:
    """_resolve_kind: maps platform + flags to the correct asset kind."""

    def test_windows_installer(self):
        assert (
            _resolve_kind(PLATFORM_WINDOWS, is_portable=False, is_appimage=False, is_system_managed=False)
            == KIND_INSTALLER
        )

    def test_windows_portable(self):
        assert (
            _resolve_kind(PLATFORM_WINDOWS, is_portable=True, is_appimage=False, is_system_managed=False)
            == KIND_PORTABLE
        )

    def test_macos_always_disk_image(self):
        assert (
            _resolve_kind(PLATFORM_MACOS, is_portable=False, is_appimage=False, is_system_managed=False)
            == KIND_DISK_IMAGE
        )

    def test_linux_appimage(self):
        assert (
            _resolve_kind(PLATFORM_LINUX, is_portable=False, is_appimage=True, is_system_managed=False) == KIND_APPIMAGE
        )

    def test_linux_system_managed_is_package(self):
        assert (
            _resolve_kind(PLATFORM_LINUX, is_portable=False, is_appimage=False, is_system_managed=True) == KIND_PACKAGE
        )

    def test_linux_portable(self):
        assert (
            _resolve_kind(PLATFORM_LINUX, is_portable=True, is_appimage=False, is_system_managed=False) == KIND_PORTABLE
        )

    def test_linux_default_is_appimage(self):
        assert (
            _resolve_kind(PLATFORM_LINUX, is_portable=False, is_appimage=False, is_system_managed=False)
            == KIND_APPIMAGE
        )

    def test_unknown_platform(self):
        assert _resolve_kind("unknown", is_portable=False, is_appimage=False, is_system_managed=False) == KIND_ARCHIVE


class TestResolveStrategy:
    """_resolve_strategy: maps kind + environment to (can_self_update, strategy)."""

    def test_source_checkout_always_open_url(self):
        can, strategy = _resolve_strategy(
            PLATFORM_WINDOWS, KIND_INSTALLER, is_frozen=False, is_system_managed=False, install_writable=True
        )
        assert can is False
        assert strategy == APPLY_OPEN_URL

    def test_system_managed_always_open_url(self):
        can, strategy = _resolve_strategy(
            PLATFORM_LINUX, KIND_PACKAGE, is_frozen=True, is_system_managed=True, install_writable=False
        )
        assert can is False
        assert strategy == APPLY_OPEN_URL

    def test_non_writable_always_open_url(self):
        can, strategy = _resolve_strategy(
            PLATFORM_LINUX, KIND_APPIMAGE, is_frozen=True, is_system_managed=False, install_writable=False
        )
        assert can is False
        assert strategy == APPLY_OPEN_URL

    def test_windows_installer_runs_installer(self):
        can, strategy = _resolve_strategy(
            PLATFORM_WINDOWS, KIND_INSTALLER, is_frozen=True, is_system_managed=False, install_writable=True
        )
        assert can is True
        assert strategy == APPLY_RUN_INSTALLER

    def test_macos_disk_image_opens_file(self):
        can, strategy = _resolve_strategy(
            PLATFORM_MACOS, KIND_DISK_IMAGE, is_frozen=True, is_system_managed=False, install_writable=True
        )
        assert can is True
        assert strategy == APPLY_OPEN_FILE

    def test_portable_reveals(self):
        can, strategy = _resolve_strategy(
            PLATFORM_WINDOWS, KIND_PORTABLE, is_frozen=True, is_system_managed=False, install_writable=True
        )
        assert can is True
        assert strategy == APPLY_REVEAL

    def test_appimage_reveals(self):
        can, strategy = _resolve_strategy(
            PLATFORM_LINUX, KIND_APPIMAGE, is_frozen=True, is_system_managed=False, install_writable=True
        )
        assert can is True
        assert strategy == APPLY_REVEAL


class TestInstallContext:
    """InstallContext: dataclass helpers."""

    def test_query_params(self):
        ctx = InstallContext(
            platform=PLATFORM_WINDOWS,
            arch="x64",
            is_frozen=True,
            is_portable=False,
            is_appimage=False,
            is_system_managed=False,
            install_dir=Path("C:/Program Files/HistorySync"),
            kind=KIND_INSTALLER,
            can_self_update=True,
            apply_strategy=APPLY_RUN_INSTALLER,
        )
        assert ctx.query_params() == {"platform": "windows", "arch": "x64", "kind": "installer"}

    def test_auto_update_supported_when_frozen(self):
        ctx = InstallContext(
            platform=PLATFORM_LINUX,
            arch="x86_64",
            is_frozen=True,
            is_portable=False,
            is_appimage=True,
            is_system_managed=False,
            install_dir=Path("/tmp/app"),
            kind=KIND_APPIMAGE,
            can_self_update=True,
            apply_strategy=APPLY_REVEAL,
        )
        assert ctx.auto_update_supported is True

    def test_auto_update_not_supported_when_not_frozen(self):
        ctx = InstallContext(
            platform=PLATFORM_LINUX,
            arch="x86_64",
            is_frozen=False,
            is_portable=False,
            is_appimage=False,
            is_system_managed=False,
            install_dir=Path("/home/dev/repo"),
            kind=KIND_APPIMAGE,
            can_self_update=False,
            apply_strategy=APPLY_OPEN_URL,
        )
        assert ctx.auto_update_supported is False

    def test_describe_contains_all_fields(self):
        ctx = InstallContext(
            platform=PLATFORM_MACOS,
            arch="arm64",
            is_frozen=True,
            is_portable=False,
            is_appimage=False,
            is_system_managed=False,
            install_dir=Path("/Applications/HistorySync.app"),
            kind=KIND_DISK_IMAGE,
            can_self_update=True,
            apply_strategy=APPLY_OPEN_FILE,
        )
        desc = ctx.describe()
        assert "macos" in desc
        assert "arm64" in desc
        assert "disk-image" in desc
