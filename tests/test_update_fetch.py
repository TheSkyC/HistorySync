# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for src.services.update_fetch — source ordering, mirror preference, candidate building."""

from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services import update_fetch
from src.services.update_fetch import (
    SOURCE_DL,
    SOURCE_GITHUB,
    TOKEN_DL,
    TOKEN_GITHUB,
    TOKEN_MIRROR,
    build_download_candidates,
    download_token_order,
    metadata_source_order,
    prefers_mirror,
)
from src.services.update_models import ReleaseInfo, UpdateAsset, UpdateInfo
from src.utils.constants import UPDATE_SOURCE_MEMORY_TTL_SEC
from src.utils.install_context import InstallContext


def _make_updater(
    prefer_mirror: str = "auto",
    last_good_metadata_source: str = "",
    last_good_download_source: str = "",
    last_good_metadata_source_ts: int = 0,
    last_good_download_source_ts: int = 0,
    last_good_source_ts: int = 0,
):
    return SimpleNamespace(
        prefer_mirror=prefer_mirror,
        last_good_metadata_source=last_good_metadata_source,
        last_good_download_source=last_good_download_source,
        last_good_metadata_source_ts=last_good_metadata_source_ts,
        last_good_download_source_ts=last_good_download_source_ts,
        last_good_source_ts=last_good_source_ts,
    )


def _make_ctx() -> InstallContext:
    return InstallContext(
        platform="windows",
        arch="x64",
        is_frozen=True,
        is_portable=False,
        is_appimage=False,
        is_system_managed=False,
        install_dir=Path("/tmp"),
        kind="installer",
        can_self_update=True,
        apply_strategy="run_installer",
    )


def _set_monotonic_clock(monkeypatch: pytest.MonkeyPatch, *values: float) -> None:
    iterator = iter(values)
    monkeypatch.setattr(update_fetch.time, "monotonic", lambda: next(iterator))


def _allow_github_call(monkeypatch: pytest.MonkeyPatch, now: float = 1_000.0) -> None:
    monkeypatch.setitem(update_fetch._github_state, "last_call_ts", 0.0)
    _set_monotonic_clock(monkeypatch, now)


# ══════════════════════════════════════════════════════════════════════════════
# metadata_source_order
# ══════════════════════════════════════════════════════════════════════════════


class TestMetadataSourceOrder:
    def test_default_order_is_dl_first(self):
        updater = _make_updater()
        assert metadata_source_order(updater) == [SOURCE_DL, SOURCE_GITHUB]

    def test_remembered_github_fresh(self):
        now = int(time.time())
        updater = _make_updater(last_good_metadata_source="github", last_good_metadata_source_ts=now - 100)
        assert metadata_source_order(updater, now=now) == [SOURCE_GITHUB, SOURCE_DL]

    def test_remembered_github_expired(self):
        now = int(time.time())
        updater = _make_updater(
            last_good_metadata_source="github",
            last_good_metadata_source_ts=now - UPDATE_SOURCE_MEMORY_TTL_SEC - 1,
        )
        assert metadata_source_order(updater, now=now) == [SOURCE_DL, SOURCE_GITHUB]

    def test_remembered_dl_fresh(self):
        now = int(time.time())
        updater = _make_updater(last_good_metadata_source="dl", last_good_metadata_source_ts=now - 60)
        assert metadata_source_order(updater, now=now) == [SOURCE_DL, SOURCE_GITHUB]

    def test_unknown_remembered_source_ignored(self):
        now = int(time.time())
        updater = _make_updater(last_good_metadata_source="unknown", last_good_metadata_source_ts=now)
        assert metadata_source_order(updater, now=now) == [SOURCE_DL, SOURCE_GITHUB]

    def test_legacy_shared_timestamp_still_works_for_metadata(self):
        now = int(time.time())
        updater = _make_updater(last_good_metadata_source="github", last_good_source_ts=now - 100)
        assert metadata_source_order(updater, now=now) == [SOURCE_GITHUB, SOURCE_DL]


# ══════════════════════════════════════════════════════════════════════════════
# prefers_mirror
# ══════════════════════════════════════════════════════════════════════════════


class TestPrefersMirror:
    def test_off_always_false(self):
        updater = _make_updater(prefer_mirror="off")
        assert prefers_mirror(updater, "zh_CN") is False

    def test_on_always_true(self):
        updater = _make_updater(prefer_mirror="on")
        assert prefers_mirror(updater, "en_US") is True

    def test_auto_zh_cn_true(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, "zh_CN") is True

    def test_auto_zh_hans_true(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, "zh_Hans") is True

    def test_auto_en_us_false(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, "en_US") is False

    def test_auto_ja_jp_false(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, "ja_JP") is False

    def test_auto_none_lang_false(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, None) is False

    def test_auto_empty_lang_false(self):
        updater = _make_updater(prefer_mirror="auto")
        assert prefers_mirror(updater, "") is False


# ══════════════════════════════════════════════════════════════════════════════
# download_token_order
# ══════════════════════════════════════════════════════════════════════════════


class TestDownloadTokenOrder:
    def test_default_non_cn_github_first(self):
        updater = _make_updater(prefer_mirror="auto")
        order = download_token_order(updater, "en_US")
        assert order[0] == TOKEN_GITHUB

    def test_zh_cn_mirror_first(self):
        updater = _make_updater(prefer_mirror="auto")
        order = download_token_order(updater, "zh_CN")
        assert order[0] == TOKEN_MIRROR

    def test_remembered_overrides_default(self):
        now = int(time.time())
        updater = _make_updater(
            prefer_mirror="auto",
            last_good_download_source="dl",
            last_good_download_source_ts=now - 60,
        )
        order = download_token_order(updater, "en_US", now=now)
        assert order[0] == TOKEN_DL

    def test_remembered_expired_uses_default(self):
        now = int(time.time())
        updater = _make_updater(
            prefer_mirror="auto",
            last_good_download_source="dl",
            last_good_download_source_ts=now - UPDATE_SOURCE_MEMORY_TTL_SEC - 1,
        )
        order = download_token_order(updater, "en_US", now=now)
        assert order[0] == TOKEN_GITHUB

    def test_metadata_timestamp_does_not_keep_download_memory_fresh(self):
        now = int(time.time())
        updater = _make_updater(
            prefer_mirror="auto",
            last_good_download_source="dl",
            last_good_download_source_ts=now - UPDATE_SOURCE_MEMORY_TTL_SEC - 1,
            last_good_metadata_source_ts=now - 60,
        )
        order = download_token_order(updater, "en_US", now=now)
        assert order[0] == TOKEN_GITHUB


# ══════════════════════════════════════════════════════════════════════════════
# build_download_candidates
# ══════════════════════════════════════════════════════════════════════════════


def _make_update_info(
    *,
    url_download="https://github.com/dl/setup.exe",
    url_direct="https://github.com/dl/setup.exe",
    url_github="https://github.com/releases/tag/v1.4.0",
    url_mirrors=("https://mirror1.example.com/setup.exe",),
    asset_id="windows-x64-setup",
    version="1.4.0",
    source="dl",
) -> UpdateInfo:
    release = ReleaseInfo(
        version=version,
        tag=f"v{version}",
        channel="stable",
        published_at="",
        summary="",
        notes_url="",
        min_supported_version="",
    )
    asset = UpdateAsset(
        asset_id=asset_id,
        platform="windows",
        arch="x64",
        kind="installer",
        fmt="exe",
        filename="setup.exe",
        label="",
        size_bytes=100,
        sha256="abc",
        sha256_status="verified",
        url_download=url_download,
        url_direct=url_direct,
        url_github=url_github,
        url_mirrors=tuple(url_mirrors),
        rollout=100,
    )
    return UpdateInfo(release=release, asset=asset, source=source, current_version="1.3.2")


class TestFetchGithub:
    def test_stable_channel_uses_latest_endpoint(self, monkeypatch: pytest.MonkeyPatch):
        _allow_github_call(monkeypatch)
        payload = {
            "tag_name": "v1.4.0",
            "prerelease": False,
            "assets": [
                {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://dl", "size": 1}
            ],
        }
        with patch("src.services.update_fetch.http_get_json", return_value=payload) as http_get_json:
            info = update_fetch.fetch_github(_make_ctx(), "stable", "1.3.2")
        assert info is not None
        assert info.release.version == "1.4.0"
        assert http_get_json.call_args.args[0].endswith("/releases/latest")

    def test_beta_channel_prefers_prerelease_from_releases_list(self, monkeypatch: pytest.MonkeyPatch):
        _allow_github_call(monkeypatch)
        payload = [
            {"tag_name": "v1.5.0", "prerelease": False, "assets": []},
            {
                "tag_name": "v1.6.0-beta.1",
                "prerelease": True,
                "assets": [
                    {
                        "name": "HistorySync-v1.6.0-beta.1-windows-x64-setup.exe",
                        "browser_download_url": "http://dl",
                        "size": 1,
                    }
                ],
            },
        ]
        with patch("src.services.update_fetch.http_get_json", return_value=payload) as http_get_json:
            info = update_fetch.fetch_github(_make_ctx(), "beta", "1.3.2")
        assert info is not None
        assert info.release.version == "1.6.0-beta.1"
        assert http_get_json.call_args.args[0].endswith("/releases")
        assert http_get_json.call_args.kwargs["params"] == {"per_page": 20}

    def test_beta_channel_falls_back_to_newer_stable_when_no_beta_exists(self, monkeypatch: pytest.MonkeyPatch):
        _allow_github_call(monkeypatch)
        payload = [
            {"tag_name": "v1.7.0", "prerelease": False, "assets": []},
            {"tag_name": "v1.6.0-beta.1", "prerelease": True, "assets": []},
        ]
        with patch("src.services.update_fetch.http_get_json", return_value=payload):
            info = update_fetch.fetch_github(_make_ctx(), "beta", "1.3.2")
        assert info is not None
        assert info.release.version == "1.7.0"

    def test_nightly_channel_accepts_dev_tags(self, monkeypatch: pytest.MonkeyPatch):
        _allow_github_call(monkeypatch)
        payload = [
            {"tag_name": "v1.8.0-beta.2", "prerelease": True, "assets": []},
            {"tag_name": "v1.8.0-dev.5", "prerelease": True, "assets": []},
        ]
        with patch("src.services.update_fetch.http_get_json", return_value=payload):
            info = update_fetch.fetch_github(_make_ctx(), "nightly", "1.3.2")
        assert info is not None
        assert info.release.version == "1.8.0-dev.5"

    def test_second_call_raises_throttle_without_sleeping(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(update_fetch._github_state, "last_call_ts", 0.0)
        _set_monotonic_clock(monkeypatch, 1_000.0, 1_000.0)
        payload = {
            "tag_name": "v1.4.0",
            "prerelease": False,
            "assets": [
                {"name": "HistorySync-v1.4.0-windows-x64-setup.exe", "browser_download_url": "http://dl", "size": 1}
            ],
        }
        with (
            patch("src.services.update_fetch.http_get_json", return_value=payload),
            patch("src.services.update_fetch.time.sleep", side_effect=AssertionError("sleep should not be called")),
        ):
            first = update_fetch.fetch_github(_make_ctx(), "stable", "1.3.2")
            assert first is not None
            with pytest.raises(update_fetch.GitHubThrottleError, match="retry in"):
                update_fetch.fetch_github(_make_ctx(), "stable", "1.3.2")

    def test_fetch_latest_falls_back_to_dl_when_github_is_throttled(self):
        expected = _make_update_info(source="dl")
        with (
            patch("src.services.update_fetch.fetch_github", side_effect=update_fetch.GitHubThrottleError(120)),
            patch("src.services.update_fetch.fetch_dl", return_value=expected),
        ):
            info, source, error = update_fetch.fetch_latest(
                _make_ctx(),
                "stable",
                "en_US",
                "1.3.2",
                [SOURCE_GITHUB, SOURCE_DL],
            )
        assert info == expected
        assert source == SOURCE_DL
        assert error == ""

    def test_fetch_latest_returns_throttle_error_when_no_fallback_succeeds(self):
        with patch("src.services.update_fetch.fetch_github", side_effect=update_fetch.GitHubThrottleError(42)):
            info, source, error = update_fetch.fetch_latest(
                _make_ctx(),
                "stable",
                "en_US",
                "1.3.2",
                [SOURCE_GITHUB],
            )
        assert info is None
        assert source == ""
        assert "retry in 42 s" in error


class TestBuildDownloadCandidates:
    def test_github_first_order(self):
        info = _make_update_info()
        candidates = build_download_candidates(info, [TOKEN_GITHUB, TOKEN_DL, TOKEN_MIRROR])
        tokens = [t for t, _ in candidates]
        assert tokens[0] == TOKEN_GITHUB

    def test_mirror_first_order(self):
        info = _make_update_info()
        candidates = build_download_candidates(info, [TOKEN_MIRROR, TOKEN_DL, TOKEN_GITHUB])
        tokens = [t for t, _ in candidates]
        assert tokens[0] == TOKEN_MIRROR

    def test_dl_redirect_url_included_for_dl_source(self):
        info = _make_update_info(source="dl")
        candidates = build_download_candidates(info, [TOKEN_DL, TOKEN_GITHUB, TOKEN_MIRROR])
        urls = [url for _, url in candidates]
        assert any("/downloads/" in u for u in urls)

    def test_dl_redirect_excluded_for_github_source(self):
        info = _make_update_info(source="github")
        candidates = build_download_candidates(info, [TOKEN_DL, TOKEN_GITHUB, TOKEN_MIRROR])
        urls = [url for _, url in candidates]
        assert not any("/downloads/" in u for u in urls)

    def test_deduplicates_urls(self):
        info = _make_update_info(
            url_download="https://same.url/file",
            url_direct="https://same.url/file",
            url_mirrors=("https://same.url/file",),
        )
        candidates = build_download_candidates(info, [TOKEN_GITHUB, TOKEN_MIRROR, TOKEN_DL])
        urls = [url for _, url in candidates]
        assert len(urls) == len(set(urls))

    def test_no_asset_returns_empty(self):
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
        assert build_download_candidates(info, [TOKEN_GITHUB]) == []

    def test_empty_mirrors_skipped(self):
        info = _make_update_info(url_mirrors=())
        candidates = build_download_candidates(info, [TOKEN_MIRROR, TOKEN_GITHUB])
        tokens = [t for t, _ in candidates]
        assert TOKEN_MIRROR not in tokens
