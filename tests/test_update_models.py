# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.services.update_models — dl API and GitHub response parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.update_models import (
    UpdateInfo,
    api_locale,
    parse_dl_latest,
    parse_github_latest,
    select_github_asset,
)
from src.utils.install_context import (
    KIND_APPIMAGE,
    KIND_DISK_IMAGE,
    KIND_INSTALLER,
    PLATFORM_LINUX,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    InstallContext,
)


def _make_ctx(plat=PLATFORM_WINDOWS, arch="x64", kind=KIND_INSTALLER) -> InstallContext:
    return InstallContext(
        platform=plat,
        arch=arch,
        is_frozen=True,
        is_portable=False,
        is_appimage=False,
        is_system_managed=False,
        install_dir=Path("/tmp"),
        kind=kind,
        can_self_update=True,
        apply_strategy="run_installer",
    )


# ══════════════════════════════════════════════════════════════════════════════
# api_locale
# ══════════════════════════════════════════════════════════════════════════════


class TestApiLocale:
    def test_known_mapping(self):
        assert api_locale("zh_CN") == "zh-CN"
        assert api_locale("ja_JP") == "ja"
        assert api_locale("en_US") == "en"

    def test_unknown_language_returns_base(self):
        assert api_locale("pt_BR") == "pt"

    def test_empty_returns_en(self):
        assert api_locale("") == "en"
        assert api_locale(None) == "en"


# ══════════════════════════════════════════════════════════════════════════════
# parse_dl_latest
# ══════════════════════════════════════════════════════════════════════════════


class TestParseDlLatest:
    """Parsing the dl API GET /latest response."""

    @pytest.fixture
    def full_response(self) -> dict:
        return {
            "release": {
                "version": "1.4.0",
                "tag": "v1.4.0",
                "channel": "stable",
                "status": "latest",
                "publishedAt": "2026-05-30T10:00:00Z",
                "minSupportedVersion": "1.1.0",
                "summary": "A great release",
                "notesUrl": "https://github.com/TheSkyC/HistorySync/releases/tag/v1.4.0",
                "changelog": [
                    {"type": "feature", "scope": "ui", "title": "New dashboard"},
                    {"type": "fix", "scope": "db", "title": "Fix FTS triggers"},
                ],
            },
            "asset": {
                "id": "windows-x64-setup",
                "platform": "windows",
                "arch": "x64",
                "kind": "installer",
                "format": "exe",
                "filename": "HistorySync-v1.4.0-windows-x64-setup.exe",
                "label": "Windows x64 Installer",
                "sizeBytes": 42000000,
                "hashes": [
                    {"algorithm": "sha256", "value": "abcdef1234567890", "status": "verified"},
                ],
                "urls": {
                    "download": "https://github.com/download/setup.exe",
                    "direct": "https://github.com/download/setup.exe",
                    "github": "https://github.com/releases/tag/v1.4.0",
                    "mirrors": ["https://mirror.example.com/setup.exe"],
                },
                "updater": {"preferred": True, "rollout": 80},
            },
        }

    def test_parses_full_response(self, full_response):
        info = parse_dl_latest(full_response, "1.3.2")
        assert info is not None
        assert info.release.version == "1.4.0"
        assert info.release.channel == "stable"
        assert info.release.min_supported_version == "1.1.0"
        assert len(info.release.changelog) == 2
        assert info.release.changelog[0].entry_type == "feature"
        assert info.release.changelog[0].title == "New dashboard"
        assert info.source == "dl"
        assert info.current_version == "1.3.2"

    def test_parses_asset(self, full_response):
        info = parse_dl_latest(full_response, "1.3.2")
        assert info.asset is not None
        assert info.asset.asset_id == "windows-x64-setup"
        assert info.asset.filename == "HistorySync-v1.4.0-windows-x64-setup.exe"
        assert info.asset.size_bytes == 42000000
        assert info.asset.sha256 == "abcdef1234567890"
        assert info.asset.sha256_status == "verified"
        assert info.asset.has_verified_sha256 is True
        assert info.asset.rollout == 80
        assert info.asset.url_mirrors == ("https://mirror.example.com/setup.exe",)

    def test_asset_null_is_allowed(self, full_response):
        """dl API §10.1: asset can be null."""
        full_response["asset"] = None
        info = parse_dl_latest(full_response, "1.3.2")
        assert info is not None
        assert info.asset is None

    def test_missing_release_returns_none(self):
        assert parse_dl_latest({}, "1.3.2") is None
        assert parse_dl_latest({"release": None}, "1.3.2") is None

    def test_release_without_version_returns_none(self):
        assert parse_dl_latest({"release": {"tag": "v1.0.0"}}, "1.3.2") is None

    def test_non_dict_input_returns_none(self):
        assert parse_dl_latest(None, "1.3.2") is None
        assert parse_dl_latest([], "1.3.2") is None

    def test_pending_hash_not_verified(self, full_response):
        full_response["asset"]["hashes"][0]["status"] = "pending"
        info = parse_dl_latest(full_response, "1.3.2")
        assert info.asset.has_verified_sha256 is False

    def test_missing_hashes(self, full_response):
        full_response["asset"]["hashes"] = []
        info = parse_dl_latest(full_response, "1.3.2")
        assert info.asset.sha256 == ""
        assert info.asset.has_verified_sha256 is False


class TestUpdateInfo:
    """UpdateInfo properties."""

    def _make_info(self, latest_version: str, current: str, min_supported: str = "", rollout: int = 100):
        from src.services.update_models import ReleaseInfo, UpdateAsset

        release = ReleaseInfo(
            version=latest_version,
            tag=f"v{latest_version}",
            channel="stable",
            published_at="",
            summary="",
            notes_url="",
            min_supported_version=min_supported,
        )
        asset = UpdateAsset(
            asset_id="test",
            platform="windows",
            arch="x64",
            kind="installer",
            fmt="exe",
            filename="test.exe",
            label="",
            size_bytes=100,
            sha256="abc",
            sha256_status="verified",
            url_download="http://dl",
            url_direct="http://dl",
            url_github="http://gh",
            rollout=rollout,
        )
        return UpdateInfo(release=release, asset=asset, source="dl", current_version=current)

    def test_is_update_available_true(self):
        info = self._make_info("1.4.0", "1.3.2")
        assert info.is_update_available is True

    def test_is_update_available_false_same(self):
        info = self._make_info("1.3.2", "1.3.2")
        assert info.is_update_available is False

    def test_requires_full_install_true(self):
        info = self._make_info("1.4.0", "1.0.0", min_supported="1.1.0")
        assert info.requires_full_install is True

    def test_requires_full_install_false(self):
        info = self._make_info("1.4.0", "1.2.0", min_supported="1.1.0")
        assert info.requires_full_install is False

    def test_requires_full_install_no_min(self):
        info = self._make_info("1.4.0", "1.0.0", min_supported="")
        assert info.requires_full_install is False

    def test_rollout_from_asset(self):
        info = self._make_info("1.4.0", "1.3.2", rollout=50)
        assert info.rollout == 50

    def test_rollout_without_asset(self):
        from src.services.update_models import ReleaseInfo

        release = ReleaseInfo(
            version="1.4.0",
            tag="v1.4.0",
            channel="stable",
            published_at="",
            summary="",
            notes_url="",
            min_supported_version="",
        )
        info = UpdateInfo(release=release, asset=None, source="dl", current_version="1.3.2")
        assert info.rollout == 100


# ══════════════════════════════════════════════════════════════════════════════
# GitHub releases parsing
# ══════════════════════════════════════════════════════════════════════════════


class TestSelectGithubAsset:
    """select_github_asset: heuristic filename matching."""

    def test_matches_windows_installer(self):
        assets = [
            {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://a", "size": 40000000},
            {"name": "HistorySync-v1.4.0-linux-x86_64.AppImage", "browser_download_url": "http://b", "size": 50000000},
        ]
        ctx = _make_ctx(PLATFORM_WINDOWS, "x64", KIND_INSTALLER)
        result = select_github_asset(assets, ctx)
        assert result is not None
        assert "windows" in result["name"]

    def test_matches_linux_appimage(self):
        assets = [
            {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://a", "size": 40000000},
            {"name": "HistorySync-v1.4.0-linux-x86_64.AppImage", "browser_download_url": "http://b", "size": 50000000},
        ]
        ctx = _make_ctx(PLATFORM_LINUX, "x86_64", KIND_APPIMAGE)
        result = select_github_asset(assets, ctx)
        assert result is not None
        assert "AppImage" in result["name"]

    def test_matches_macos_dmg(self):
        assets = [
            {"name": "HistorySync-v1.4.0-macos-arm64.dmg", "browser_download_url": "http://a", "size": 60000000},
            {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://b", "size": 40000000},
        ]
        ctx = _make_ctx(PLATFORM_MACOS, "arm64", KIND_DISK_IMAGE)
        result = select_github_asset(assets, ctx)
        assert result is not None
        assert "macos" in result["name"]

    def test_prefers_arch_match(self):
        assets = [
            {
                "name": "HistorySync-v1.4.0-windows-arm64-setup.exe",
                "browser_download_url": "http://a",
                "size": 40000000,
            },
            {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://b", "size": 40000000},
        ]
        ctx = _make_ctx(PLATFORM_WINDOWS, "x64", KIND_INSTALLER)
        result = select_github_asset(assets, ctx)
        assert "x64" in result["name"]

    def test_linux_arch_aliases_match_amd64_assets(self):
        assets = [
            {"name": "historysync_1.4.0_arm64.deb", "browser_download_url": "http://a", "size": 1},
            {"name": "historysync_1.4.0_amd64.deb", "browser_download_url": "http://b", "size": 1},
        ]
        ctx = _make_ctx(PLATFORM_LINUX, "x86_64", "package")
        result = select_github_asset(assets, ctx)
        assert result is not None
        assert "amd64" in result["name"]

    def test_empty_assets_returns_none(self):
        ctx = _make_ctx()
        assert select_github_asset([], ctx) is None
        assert select_github_asset(None, ctx) is None

    def test_no_platform_match_returns_none(self):
        assets = [{"name": "HistorySync-v1.4.0-linux-x86_64.AppImage", "browser_download_url": "http://a"}]
        ctx = _make_ctx(PLATFORM_WINDOWS, "x64", KIND_INSTALLER)
        assert select_github_asset(assets, ctx) is None


class TestParseGithubLatest:
    """parse_github_latest: adapt GitHub releases/latest payload."""

    def test_basic_parse(self):
        data = {
            "tag_name": "v1.4.0",
            "prerelease": False,
            "published_at": "2026-05-30T10:00:00Z",
            "html_url": "https://github.com/TheSkyC/HistorySync/releases/tag/v1.4.0",
            "body": "Release notes here",
            "assets": [
                {
                    "name": "HistorySync-v1.4.0-windows-x64-setup.exe",
                    "browser_download_url": "http://dl",
                    "size": 42000000,
                },
            ],
        }
        ctx = _make_ctx()
        info = parse_github_latest(data, ctx, "1.3.2")
        assert info is not None
        assert info.release.version == "1.4.0"
        assert info.release.channel == "stable"
        assert info.source == "github"
        assert info.asset is not None
        assert info.asset.size_bytes == 42000000

    def test_prerelease_sets_beta_channel(self):
        data = {"tag_name": "v1.5.0-beta.1", "prerelease": True, "assets": []}
        ctx = _make_ctx()
        info = parse_github_latest(data, ctx, "1.3.2")
        assert info.release.channel == "beta"

    def test_no_tag_returns_none(self):
        assert parse_github_latest({}, _make_ctx(), "1.3.2") is None
        assert parse_github_latest({"tag_name": ""}, _make_ctx(), "1.3.2") is None

    def test_non_dict_returns_none(self):
        assert parse_github_latest(None, _make_ctx(), "1.3.2") is None

    def test_no_matching_asset_gives_none_asset(self):
        data = {
            "tag_name": "v1.4.0",
            "assets": [{"name": "unrelated.txt", "browser_download_url": "http://x"}],
        }
        ctx = _make_ctx()
        info = parse_github_latest(data, ctx, "1.3.2")
        assert info is not None
        assert info.asset is None
