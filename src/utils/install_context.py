# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Runtime detection of *how* HistorySync was installed.

Knowing the operating system is not enough for a self-update flow: the same OS
can host several distribution forms with very different update mechanics.  A
Windows machine may run the Inno Setup installer build or the portable ZIP; a
Linux box may run an AppImage (single writable file), a ``.deb`` (root-owned,
managed by ``apt``), or a generic tarball.  Each form maps to a different dl API
asset ``kind`` and a different "how do I actually apply the update" strategy.

:class:`InstallContext` centralises that detection so the rest of the update
system can ask three questions:

1. Which asset should I request?           -> :attr:`InstallContext.kind`
2. Can I update myself at all?              -> :attr:`InstallContext.can_self_update`
3. How do I apply a downloaded artifact?    -> :attr:`InstallContext.apply_strategy`

The detection deliberately mirrors the portable/\u200bfrozen logic already used in
``src/main.py`` so a build that is *treated* as portable at startup is also
*updated* as portable.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import sys

# ── Platform identifiers (match dl API ``platform`` values) ────────────────────
PLATFORM_WINDOWS = "windows"
PLATFORM_MACOS = "macos"
PLATFORM_LINUX = "linux"
PLATFORM_UNKNOWN = "unknown"

# ── Asset kinds (match dl API ``kind`` values) ─────────────────────────────────
KIND_INSTALLER = "installer"
KIND_PORTABLE = "portable"
KIND_PACKAGE = "package"
KIND_ARCHIVE = "archive"
KIND_APPIMAGE = "appimage"
KIND_DISK_IMAGE = "disk-image"

# ── Apply strategies (how the UI lands a downloaded artifact) ──────────────────
#: Launch the downloaded installer executable, then quit so it can take over.
APPLY_RUN_INSTALLER = "run_installer"
#: Hand the file to the OS (e.g. open a .dmg so the user can drag the app).
APPLY_OPEN_FILE = "open_file"
#: Download + verify, then reveal the file in the OS file manager with guidance.
APPLY_REVEAL = "reveal"
#: Cannot land in-app — open the release/download page in the browser instead.
APPLY_OPEN_URL = "open_url"

#: Marker file (next to the executable) that forces portable layout.  Identical
#: to the marker honoured by ``src/main.py`` at startup.
PORTABLE_MARKER = ".portable"

# Directories that indicate a system-managed (package-manager-owned) install on
# Linux/macOS where self-replacement is neither possible nor desirable.
_SYSTEM_PREFIXES = ("/usr", "/opt", "/bin", "/sbin", "/snap", "/var/lib/flatpak", "/app")


def _normalize_arch(machine: str, plat: str) -> str:
    """Map ``platform.machine()`` to the arch token the dl API expects.

    The dl API is not internally consistent (Windows assets use ``x64`` while
    Linux assets use ``x86_64``), so normalisation is platform-aware.
    """
    m = (machine or "").lower()
    is_x86_64 = m in ("amd64", "x86_64", "x64", "em64t")
    is_arm64 = m in ("arm64", "aarch64", "armv8b", "armv8l")

    if plat == PLATFORM_WINDOWS:
        if is_x86_64:
            return "x64"
        if is_arm64:
            return "arm64"
        if m in ("x86", "i386", "i686"):
            return "x86"
        return m or "x64"

    if plat == PLATFORM_MACOS:
        if is_arm64:
            return "arm64"
        if is_x86_64:
            return "x64"
        return m or "arm64"

    # Linux and unknown: prefer the kernel's own naming.
    if is_x86_64:
        return "x86_64"
    if is_arm64:
        return "arm64"
    return m or "x86_64"


def _detect_platform() -> str:
    if sys.platform.startswith("win"):
        return PLATFORM_WINDOWS
    if sys.platform == "darwin":
        return PLATFORM_MACOS
    if sys.platform.startswith("linux"):
        return PLATFORM_LINUX
    return PLATFORM_UNKNOWN


def _repo_root() -> Path:
    """Return the repository root by walking up from this file until a known
    marker file (``pyproject.toml`` or ``.git``) is found, falling back to a
    fixed-depth walk if neither marker is present."""
    current = Path(__file__).resolve().parent
    # Walk up to 8 levels — enough for any reasonable nesting under the repo root.
    for _ in range(8):
        if (current / "pyproject.toml").exists() or (current / ".git").exists():
            return current
        current = current.parent
    # Absolute last resort: assume standard src/utils/ layout (this path must
    # be updated if the file is moved to a different nesting depth).
    return Path(__file__).resolve().parents[2]


def _install_dir(is_frozen: bool) -> Path:
    """Directory the running program lives in.

    For a frozen (PyInstaller) build this is the directory containing the
    executable; in a source checkout it is the repository root.  Mirrors the
    ``_exe_dir`` computation in ``src/main.py``.
    """
    if is_frozen:
        try:
            return Path(sys.executable).resolve().parent
        except (OSError, ValueError):
            return _repo_root()
    return _repo_root()


def _path_is_writable(path: Path) -> bool:
    """Best-effort writability probe for *path* (a directory)."""
    try:
        return os.access(path, os.W_OK)
    except OSError:
        return False


def _is_system_managed(install_dir: Path) -> bool:
    """True when *install_dir* sits under a package-manager-owned prefix."""
    try:
        resolved = install_dir.resolve()
    except (OSError, ValueError):
        resolved = install_dir
    text = resolved.as_posix()
    return any(text == prefix or text.startswith(prefix + "/") for prefix in _SYSTEM_PREFIXES)


@dataclass(frozen=True)
class InstallContext:
    """Immutable snapshot of the current installation form."""

    platform: str
    arch: str
    is_frozen: bool
    is_portable: bool
    is_appimage: bool
    is_system_managed: bool
    install_dir: Path
    kind: str
    can_self_update: bool
    apply_strategy: str

    # ── Derived helpers ───────────────────────────────────────

    @property
    def auto_update_supported(self) -> bool:
        """Whether *automatic* (unattended) update checks should run.

        Only frozen builds auto-check: running from a source checkout means a
        developer is at the keyboard, and surprise "update available" prompts
        during development are pure noise.  Manual "check now" is always
        allowed regardless of this flag.
        """
        return self.is_frozen

    def query_params(self) -> dict[str, str]:
        """The platform/arch/kind query parameters for ``GET /latest``."""
        return {"platform": self.platform, "arch": self.arch, "kind": self.kind}

    def describe(self) -> str:
        """Compact one-line description for logs."""
        return (
            f"platform={self.platform} arch={self.arch} kind={self.kind} "
            f"frozen={self.is_frozen} portable={self.is_portable} appimage={self.is_appimage} "
            f"system_managed={self.is_system_managed} self_update={self.can_self_update} "
            f"strategy={self.apply_strategy} dir={self.install_dir}"
        )


def _resolve_kind(
    plat: str,
    *,
    is_portable: bool,
    is_appimage: bool,
    is_system_managed: bool,
) -> str:
    if plat == PLATFORM_WINDOWS:
        return KIND_PORTABLE if is_portable else KIND_INSTALLER
    if plat == PLATFORM_MACOS:
        return KIND_DISK_IMAGE
    if plat == PLATFORM_LINUX:
        if is_appimage:
            return KIND_APPIMAGE
        if is_system_managed:
            return KIND_PACKAGE
        if is_portable:
            return KIND_PORTABLE
        return KIND_APPIMAGE
    return KIND_ARCHIVE


def _resolve_strategy(
    plat: str,
    kind: str,
    *,
    is_frozen: bool,
    is_system_managed: bool,
    install_writable: bool,
) -> tuple[bool, str]:
    """Return ``(can_self_update, apply_strategy)``.

    A source checkout (not frozen) and any package-manager-owned install fall
    back to "open the download/release page" — we must never write into a
    root-owned ``/usr`` tree or replace a developer's working copy.
    """
    if not is_frozen:
        return False, APPLY_OPEN_URL
    if is_system_managed or not install_writable:
        # e.g. a .deb installed under /usr — defer to apt / the website.
        return False, APPLY_OPEN_URL

    if kind == KIND_INSTALLER:
        # Run the signed installer; it handles replacement (and elevation).
        return True, APPLY_RUN_INSTALLER
    if kind == KIND_DISK_IMAGE:
        # Open the .dmg; the user drags the app over (Gatekeeper-friendly).
        return True, APPLY_OPEN_FILE
    if kind in (KIND_PORTABLE, KIND_APPIMAGE, KIND_ARCHIVE):
        # Download + verify, then reveal the artifact with replacement guidance.
        # Hot-swapping the *running* binary via a detached helper is a deliberate
        # future enhancement; revealing the verified file is safe today.
        return True, APPLY_REVEAL
    return False, APPLY_OPEN_URL


def detect_install_context() -> InstallContext:
    """Detect the current installation form.

    Pure function of the process environment; cheap enough to call on demand,
    though the update service caches one instance for its lifetime.
    """
    plat = _detect_platform()
    arch = _normalize_arch(platform.machine(), plat)
    is_frozen = hasattr(sys, "_MEIPASS")
    install_dir = _install_dir(is_frozen)
    is_appimage = bool(os.environ.get("APPIMAGE"))

    # Portable only makes sense for a frozen build shipped as a self-contained
    # folder/zip carrying the ``.portable`` marker beside the executable.
    is_portable = is_frozen and (install_dir / PORTABLE_MARKER).exists()

    is_system_managed = plat in (PLATFORM_LINUX, PLATFORM_MACOS) and is_frozen and _is_system_managed(install_dir)

    kind = _resolve_kind(
        plat,
        is_portable=is_portable,
        is_appimage=is_appimage,
        is_system_managed=is_system_managed,
    )
    install_writable = _path_is_writable(install_dir)
    can_self_update, apply_strategy = _resolve_strategy(
        plat,
        kind,
        is_frozen=is_frozen,
        is_system_managed=is_system_managed,
        install_writable=install_writable,
    )

    return InstallContext(
        platform=plat,
        arch=arch,
        is_frozen=is_frozen,
        is_portable=is_portable,
        is_appimage=is_appimage,
        is_system_managed=is_system_managed,
        install_dir=install_dir,
        kind=kind,
        can_self_update=can_self_update,
        apply_strategy=apply_strategy,
    )
