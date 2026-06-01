# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Network + source-selection helpers for the update system.

Keeping the HTTP and ordering logic Qt-free lets two very different callers
share it: the GUI's threaded :class:`~src.services.update_service.UpdateService`
and the headless ``hsync update`` CLI command (which must not drag in PySide6).
"""

from __future__ import annotations

import math
import time
from urllib.parse import quote

import requests

from src.services import update_debug
from src.services.update_models import (
    UpdateInfo,
    parse_dl_latest,
    parse_github_latest,
)
from src.utils.constants import (
    APP_VERSION,
    UPDATE_API_BASE_URL,
    UPDATE_GITHUB_LATEST_API,
    UPDATE_GITHUB_RELEASES_API,
    UPDATE_HTTP_CONNECT_TIMEOUT,
    UPDATE_HTTP_READ_TIMEOUT,
    UPDATE_MIRROR_OFF,
    UPDATE_MIRROR_ON,
    UPDATE_SOURCE_MEMORY_TTL_SEC,
)
from src.utils.install_context import InstallContext
from src.utils.logger import get_logger
from src.utils.version_utils import compare

log = get_logger("update.fetch")

SOURCE_DL = "dl"
SOURCE_GITHUB = "github"
TOKEN_MIRROR = "mirror"
TOKEN_DL = "dl"
TOKEN_GITHUB = "github"

_DEFAULT_TIMEOUT = (UPDATE_HTTP_CONNECT_TIMEOUT, UPDATE_HTTP_READ_TIMEOUT)

# Client-side minimum interval between GitHub API calls (seconds).  Unauthenticated
# requests share a 60/hour/IP quota; a 5-minute floor prevents a user who rapidly
# clicks "Check for Updates" from exhausting it inside a single session.
_GITHUB_MIN_INTERVAL_SEC = 300
_github_state: dict[str, float] = {"last_call_ts": 0.0}


class GitHubThrottleError(RuntimeError):
    """Raised when the client-side GitHub throttle suppresses a request."""

    def __init__(self, retry_after_sec: float):
        self.retry_after_sec = max(0.0, retry_after_sec)
        retry_after_display = max(1, math.ceil(self.retry_after_sec))
        super().__init__(f"GitHub API throttled; retry in {retry_after_display} s")


def reset_github_throttle() -> None:
    """Reset the GitHub API call throttle timer (intended for test use)."""
    _github_state["last_call_ts"] = 0.0


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": f"HistorySync/{APP_VERSION} (+https://github.com/TheSkyC/HistorySync)",
        "Accept": "application/json",
    }


def http_get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout=None,
    session: requests.Session | None = None,
) -> object:
    """GET *url* and return parsed JSON; raises on transport/HTTP/JSON error."""
    requester = session or requests
    resp = requester.get(
        url,
        params=params,
        headers=headers or default_headers(),
        timeout=timeout if timeout is not None else _DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ── Metadata fetch (dl primary, GitHub fallback) ──────────────────────────────


def _effective_api_base() -> str:
    """Return the dl API base URL, respecting the debug override if set."""
    override = update_debug.api_base_url()
    return override if override is not None else UPDATE_API_BASE_URL


def fetch_dl(
    context: InstallContext,
    channel: str,
    locale: str,
    current_version: str,
    headers: dict | None = None,
    session: requests.Session | None = None,
):
    params = {"channel": channel, "locale": locale, **context.query_params()}
    data = http_get_json(f"{_effective_api_base()}/latest", params=params, headers=headers, session=session)
    return parse_dl_latest(data, current_version)


def _normalize_channel(channel: str | None) -> str:
    value = (channel or "stable").strip().lower()
    return value if value in {"stable", "beta", "nightly"} else "stable"


def _github_release_channel(release: dict) -> str:
    if not bool(release.get("prerelease")):
        return "stable"
    tag = str(release.get("tag_name", "") or "").lower()
    if any(token in tag for token in ("nightly", "dev", "alpha")):
        return "nightly"
    return "beta"


def _github_release_allowed(release_channel: str, desired_channel: str) -> bool:
    if desired_channel == "stable":
        return release_channel == "stable"
    if desired_channel == "beta":
        return release_channel in {"stable", "beta"}
    return release_channel in {"stable", "beta", "nightly"}


def _select_github_release(payload: object, channel: str) -> dict | None:
    desired = _normalize_channel(channel)
    releases = payload if isinstance(payload, list) else [payload]
    best: dict | None = None
    best_channel = ""
    best_version = ""
    for release in releases:
        if not isinstance(release, dict) or bool(release.get("draft")):
            continue
        tag = str(release.get("tag_name", "") or "")
        if not tag:
            continue
        release_channel = _github_release_channel(release)
        if not _github_release_allowed(release_channel, desired):
            continue
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        if best is None:
            best = release
            best_channel = release_channel
            best_version = version
            continue
        cmp = compare(version, best_version)
        if cmp > 0 or (cmp == 0 and release_channel == desired and best_channel != desired):
            best = release
            best_channel = release_channel
            best_version = version
    return best


def fetch_github(
    context: InstallContext,
    channel: str,
    current_version: str,
    headers: dict | None = None,
    session: requests.Session | None = None,
):
    gh_headers = dict(headers or default_headers())
    gh_headers["Accept"] = "application/vnd.github+json"

    # Enforce a client-side floor between GitHub API calls to avoid exhausting
    # the unauthenticated rate limit (60 req/hour/IP) when the user clicks
    # "Check for Updates" repeatedly or when the dl API is unreachable.
    now = time.monotonic()
    elapsed = now - _github_state["last_call_ts"]
    if elapsed < _GITHUB_MIN_INTERVAL_SEC:
        remaining = _GITHUB_MIN_INTERVAL_SEC - elapsed
        log.info(
            "Skipping GitHub API call due to client-side throttle: %.1f s remaining (floor=%d s)",
            remaining,
            _GITHUB_MIN_INTERVAL_SEC,
        )
        raise GitHubThrottleError(remaining)
    _github_state["last_call_ts"] = now

    desired = _normalize_channel(channel)
    if desired == "stable":
        data = http_get_json(UPDATE_GITHUB_LATEST_API, headers=gh_headers, session=session)
    else:
        data = http_get_json(
            UPDATE_GITHUB_RELEASES_API,
            params={"per_page": 20},
            headers=gh_headers,
            session=session,
        )
    selected = _select_github_release(data, desired)
    if selected is None:
        return None
    return parse_github_latest(selected, context, current_version)


def fetch_latest(
    context: InstallContext,
    channel: str,
    locale: str,
    current_version: str,
    source_order: list[str],
    headers: dict | None = None,
    session: requests.Session | None = None,
) -> tuple[UpdateInfo | None, str, str]:
    """Try each metadata source in *source_order*; return (info, source, error).

    The first source that yields a parseable release wins.  ``info`` is ``None``
    only when *every* source failed, in which case ``error`` carries the last
    transport message.
    """
    last_err = ""
    for source in source_order:
        try:
            info = (
                fetch_dl(context, channel, locale, current_version, headers, session=session)
                if source == SOURCE_DL
                else fetch_github(context, channel, current_version, headers, session=session)
            )
            if info is not None:
                return info, source, ""
            last_err = f"{source}: empty/unrecognised response"
        except Exception as exc:  # network, HTTP, JSON — all non-fatal, try next
            last_err = f"{source}: {exc}"
            if isinstance(exc, GitHubThrottleError):
                log.info("Update metadata fetch via %s skipped: %s", source, exc)
            else:
                log.warning("Update metadata fetch via %s failed: %s", source, exc)
    return None, "", last_err


# ── Source ordering (learned + local-signal, never geo) ───────────────────────


def _remembered_source_ts(updater, attr_name: str) -> int:
    """Return the timestamp for a remembered source, falling back to legacy state."""
    ts = getattr(updater, attr_name, 0) or 0
    if ts:
        return int(ts)
    return int(getattr(updater, "last_good_source_ts", 0) or 0)


def _memory_fresh(updater, attr_name: str, now: int | None = None) -> bool:
    now = now if now is not None else int(time.time())
    ts = _remembered_source_ts(updater, attr_name)
    return ts > 0 and (now - ts) < UPDATE_SOURCE_MEMORY_TTL_SEC


def metadata_source_order(updater, now: int | None = None) -> list[str]:
    """Order metadata sources, preferring the last one that worked (if fresh)."""
    order = [SOURCE_DL, SOURCE_GITHUB]
    remembered = updater.last_good_metadata_source
    if remembered in order and _memory_fresh(updater, "last_good_metadata_source_ts", now):
        order = [remembered, *[s for s in order if s != remembered]]
    return order


def prefers_mirror(updater, current_lang: str | None) -> bool:
    """Whether to try mirror download sources first.

    ``on``/``off`` are explicit.  ``auto`` derives the answer from the local
    language only (Simplified Chinese -> mirror first), never from a network
    geo probe.
    """
    if updater.prefer_mirror == UPDATE_MIRROR_OFF:
        return False
    if updater.prefer_mirror == UPDATE_MIRROR_ON:
        return True
    lang = (current_lang or "").lower().replace("-", "_")
    return lang.startswith("zh_cn") or lang in ("zh", "zh_hans")


def download_token_order(updater, current_lang: str | None, now: int | None = None) -> list[str]:
    """Order download-source tokens (mirror/dl/github), learned + local-signal."""
    if prefers_mirror(updater, current_lang):
        base = [TOKEN_MIRROR, TOKEN_DL, TOKEN_GITHUB]
    else:
        base = [TOKEN_GITHUB, TOKEN_DL, TOKEN_MIRROR]
    remembered = updater.last_good_download_source
    if remembered in base and _memory_fresh(updater, "last_good_download_source_ts", now):
        base = [remembered, *[t for t in base if t != remembered]]
    return base


def build_download_candidates(info: UpdateInfo, token_order: list[str]) -> list[tuple[str, str]]:
    """Resolve *token_order* into a de-duplicated list of (token, url) pairs."""
    asset = info.asset
    if asset is None:
        return []
    version = info.release.version or info.release.tag
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(token: str, url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            candidates.append((token, url))

    for token in token_order:
        if token == TOKEN_MIRROR:
            for mirror in asset.url_mirrors:
                _add(TOKEN_MIRROR, mirror)
        elif token == TOKEN_DL:
            # The dl /downloads redirect only resolves assets the dl API knows
            # about — meaningless when the metadata came from the GitHub fallback.
            if info.source == SOURCE_DL and asset.asset_id and version:
                _add(TOKEN_DL, f"{_effective_api_base()}/downloads/{quote(str(version))}/{quote(str(asset.asset_id))}")
        elif token == TOKEN_GITHUB:
            _add(TOKEN_GITHUB, asset.url_direct or asset.url_download or asset.url_github)
    return candidates


def best_browser_url(info: UpdateInfo) -> str:
    """A single URL suitable for opening in the user's browser.

    Used by the notify-only path (package-manager installs, source checkouts) and
    as a fallback when there is no downloadable asset for this platform.
    """
    candidates = build_download_candidates(info, [TOKEN_GITHUB, TOKEN_DL, TOKEN_MIRROR])
    if candidates:
        return candidates[0][1]
    if info.asset is not None and info.asset.url_github:
        return info.asset.url_github
    return info.release.notes_url or ""
