# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Pure data models and parsing for the online-update system.

This module is intentionally free of Qt and network imports so the parsing
logic — the part most likely to break when the dl API evolves — can be unit
tested in isolation.  It understands two response shapes:

* the dl API ``GET /latest`` payload (rich: release + server-selected asset +
  localized changelog), and
* the GitHub ``releases/latest`` payload, used as a fallback when the dl API is
  unreachable (filenames are matched heuristically to the running platform).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.install_context import (
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
)
from src.utils.version_utils import compare, is_newer

# Maps the app's internal language codes to dl API locale tokens.  Unmapped
# languages fall back to their base tag; the server then resolves to English.
_API_LOCALE_MAP = {
    "en_US": "en",
    "zh_CN": "zh-CN",
    "zh_TW": "zh-TW",
    "ja_JP": "ja",
    "ko_KR": "ko",
    "fr_FR": "fr",
    "de_DE": "de",
    "es_ES": "es",
}


def api_locale(lang_code: str | None) -> str:
    """Translate an app language code (e.g. ``zh_CN``) to a dl API locale."""
    if not lang_code:
        return "en"
    if lang_code in _API_LOCALE_MAP:
        return _API_LOCALE_MAP[lang_code]
    base = lang_code.replace("-", "_").split("_")[0].lower()
    return base or "en"


@dataclass(frozen=True)
class ChangelogEntry:
    entry_type: str  # feature | fix | improvement | performance | security | ...
    scope: str
    title: str


@dataclass(frozen=True)
class UpdateAsset:
    """A single downloadable artifact for one platform/arch/kind."""

    asset_id: str
    platform: str
    arch: str
    kind: str
    fmt: str
    filename: str
    label: str
    size_bytes: int | None
    sha256: str  # hex digest, or "" when not provided
    sha256_status: str  # verified | pending | unavailable | ""
    url_download: str
    url_direct: str
    url_github: str
    url_mirrors: tuple[str, ...] = ()
    rollout: int = 100

    @property
    def has_verified_sha256(self) -> bool:
        return bool(self.sha256) and self.sha256_status == "verified"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    channel: str
    published_at: str
    summary: str
    notes_url: str
    min_supported_version: str
    changelog: tuple[ChangelogEntry, ...] = ()


@dataclass(frozen=True)
class UpdateInfo:
    """The result of a successful update check."""

    release: ReleaseInfo
    asset: UpdateAsset | None
    source: str  # "dl" | "github"
    current_version: str = field(default="")

    @property
    def is_update_available(self) -> bool:
        return is_newer(self.release.version, self.current_version)

    @property
    def requires_full_install(self) -> bool:
        """True when the running version predates ``minSupportedVersion``.

        Such an upgrade cannot use any (future) delta path and must go through a
        full installer/package download.
        """
        if not self.release.min_supported_version:
            return False
        return compare(self.current_version, self.release.min_supported_version) < 0

    @property
    def rollout(self) -> int:
        return self.asset.rollout if self.asset is not None else 100


# ── dl API parsing ─────────────────────────────────────────────────────────────


def _parse_changelog(items: list) -> tuple[ChangelogEntry, ...]:
    entries: list[ChangelogEntry] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        entries.append(
            ChangelogEntry(
                entry_type=str(raw.get("type", "") or ""),
                scope=str(raw.get("scope", "") or ""),
                title=str(raw.get("title", "") or ""),
            )
        )
    return tuple(entries)


def _parse_asset(raw: dict | None) -> UpdateAsset | None:
    if not isinstance(raw, dict):
        return None
    sha256 = ""
    sha256_status = ""
    for h in raw.get("hashes", []) or []:
        if isinstance(h, dict) and h.get("algorithm") == "sha256":
            sha256 = str(h.get("value") or "")
            sha256_status = str(h.get("status") or "")
            break
    urls = raw.get("urls", {}) or {}
    mirrors = tuple(str(m) for m in (urls.get("mirrors", []) or []) if m)
    updater = raw.get("updater", {}) or {}
    try:
        rollout = int(updater.get("rollout", 100))
    except (TypeError, ValueError):
        rollout = 100
    size = raw.get("sizeBytes")
    if size is not None:
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = None
    return UpdateAsset(
        asset_id=str(raw.get("id", "") or ""),
        platform=str(raw.get("platform", "") or ""),
        arch=str(raw.get("arch", "") or ""),
        kind=str(raw.get("kind", "") or ""),
        fmt=str(raw.get("format", "") or ""),
        filename=str(raw.get("filename", "") or ""),
        label=str(raw.get("label", "") or ""),
        size_bytes=size,
        sha256=sha256,
        sha256_status=sha256_status,
        url_download=str(urls.get("download", "") or ""),
        url_direct=str(urls.get("direct", "") or ""),
        url_github=str(urls.get("github", "") or ""),
        url_mirrors=mirrors,
        rollout=rollout,
    )


def _parse_release(raw: dict) -> ReleaseInfo:
    return ReleaseInfo(
        version=str(raw.get("version", "") or ""),
        tag=str(raw.get("tag", "") or ""),
        channel=str(raw.get("channel", "") or ""),
        published_at=str(raw.get("publishedAt", "") or ""),
        summary=str(raw.get("summary", "") or ""),
        notes_url=str(raw.get("notesUrl", "") or ""),
        min_supported_version=str(raw.get("minSupportedVersion", "") or ""),
        changelog=_parse_changelog(raw.get("changelog", [])),
    )


def parse_dl_latest(data: dict, current_version: str) -> UpdateInfo | None:
    """Parse a dl API ``GET /latest`` response into an :class:`UpdateInfo`.

    Returns ``None`` if the payload has no usable ``release`` object.  The
    top-level ``asset`` (server-selected for the requested platform/arch/kind)
    is preferred; it may legitimately be ``null`` (see dl API §10.1).
    """
    if not isinstance(data, dict):
        return None
    release_raw = data.get("release")
    if not isinstance(release_raw, dict) or not release_raw.get("version"):
        return None
    release = _parse_release(release_raw)
    asset = _parse_asset(data.get("asset"))
    return UpdateInfo(release=release, asset=asset, source="dl", current_version=current_version)


# ── GitHub releases parsing (fallback) ─────────────────────────────────────────

# Filename tokens that identify each asset kind, by precedence within a kind.
_GITHUB_KIND_TOKENS: dict[str, tuple[str, ...]] = {
    KIND_INSTALLER: ("setup", "installer", ".exe"),
    KIND_PORTABLE: ("portable", ".zip"),
    KIND_APPIMAGE: (".appimage",),
    KIND_PACKAGE: (".deb",),
    KIND_ARCHIVE: (".tar.gz", ".tgz"),
    KIND_DISK_IMAGE: (".dmg",),
}


def _github_arch_tokens(ctx: InstallContext) -> tuple[str, ...]:
    arch = (ctx.arch or "").lower()
    if not arch:
        return ()
    if arch in ("x64", "x86_64", "amd64"):
        return ("x64", "x86_64", "amd64")
    if arch in ("arm64", "aarch64"):
        return ("arm64", "aarch64")
    if arch in ("x86", "i386", "i686"):
        return ("x86", "i386", "i686")
    return (arch,)


def _github_platform_score(name: str, plat: str) -> int:
    if plat == PLATFORM_WINDOWS and ("windows" in name or name.endswith((".exe", ".zip"))):
        return 2
    if plat == PLATFORM_MACOS and (name.endswith(".dmg") or "macos" in name or "darwin" in name):
        return 2
    if plat == PLATFORM_LINUX and (name.endswith((".appimage", ".deb", ".tar.gz", ".tgz")) or "linux" in name):
        return 2
    return 0


def select_github_asset(assets: list, ctx: InstallContext) -> dict | None:
    """Pick the GitHub release asset that best matches the install context."""
    best: dict | None = None
    best_score = 0
    arch_tokens = _github_arch_tokens(ctx)
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "") or "").lower()
        if not name:
            continue
        score = _github_platform_score(name, ctx.platform)
        if score == 0:
            continue
        if any(token in name for token in arch_tokens):
            score += 1
        for token in _GITHUB_KIND_TOKENS.get(ctx.kind, ()):  # kind affinity
            if token in name:
                score += 3
                break
        if score > best_score:
            best_score = score
            best = asset
    return best


def parse_github_latest(data: dict, ctx: InstallContext, current_version: str) -> UpdateInfo | None:
    """Adapt a GitHub ``releases/latest`` payload into an :class:`UpdateInfo`."""
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name", "") or "")
    if not tag:
        return None
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    is_prerelease = bool(data.get("prerelease"))
    release = ReleaseInfo(
        version=version,
        tag=tag,
        channel="beta" if is_prerelease else "stable",
        published_at=str(data.get("published_at", "") or ""),
        summary=str(data.get("body", "") or "").strip(),
        notes_url=str(data.get("html_url", "") or ""),
        min_supported_version="",
        changelog=(),
    )
    gh_asset = select_github_asset(data.get("assets", []), ctx)
    asset: UpdateAsset | None = None
    if gh_asset is not None:
        url = str(gh_asset.get("browser_download_url", "") or "")
        size = gh_asset.get("size")
        try:
            size = int(size) if size is not None else None
        except (TypeError, ValueError):
            size = None
        asset = UpdateAsset(
            asset_id=str(gh_asset.get("id", "") or ""),
            platform=ctx.platform,
            arch=ctx.arch,
            kind=ctx.kind,
            fmt="",
            filename=str(gh_asset.get("name", "") or ""),
            label=str(gh_asset.get("name", "") or ""),
            size_bytes=size,
            sha256="",
            sha256_status="unavailable",
            url_download=url,
            url_direct=url,
            url_github=str(data.get("html_url", "") or ""),
            url_mirrors=(),
            rollout=100,
        )
    return UpdateInfo(release=release, asset=asset, source="github", current_version=current_version)
