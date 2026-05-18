# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path

from src.utils.constants import (
    CONFIG_BACKUP_FILENAME,
    CONFIG_FILENAME,
    DB_FILENAME,
    DEFAULT_AUTO_BACKUP_INTERVAL_HOURS,
    DEFAULT_GLOBAL_HOTKEY,
    DEFAULT_KEYBINDINGS,
    DEFAULT_SYNC_INTERVAL_HOURS,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    WEBDAV_DEFAULT_MAX_BACKUPS,
    WEBDAV_DEFAULT_REMOTE_PATH,
)


def _resolve_config_dir() -> Path:
    """Resolve config directory at runtime."""
    from src.utils.path_helper import get_config_dir

    return get_config_dir()


def _resolve_data_dir() -> Path:
    """Resolve application data directory at runtime."""
    from src.utils.path_helper import get_app_data_dir

    return get_app_data_dir()


# ── Session-end guard ────────────────────────────────────────────────────────
# Process-wide flag set when the OS is shutting down (Windows WM_QUERYENDSESSION
# / WM_ENDSESSION, Qt commitDataRequest, or the orderly tray-quit path).
#
# While set, AppConfig.save() short-circuits to a no-op.  The rationale: during
# the ~5s TerminateProcess window after WM_ENDSESSION, several closeEvent and
# queued worker-finished slots all try to persist config.json back-to-back.
# Each save's two-step "rotate primary -> .prev, then promote tmp -> primary"
# sequence is non-atomic; being TerminateProcess'd between the two steps leaves
# the primary file missing on disk, which surfaces on the next launch as
# "config wiped + first-run wizard re-fired".
#
# The on-disk config from the user's last interactive change is already a
# known-good state.  Skipping all writes during session-end trades a stale
# last_sync_ts (re-derived on next launch from the scheduler watermark anyway)
# for guaranteed config integrity.
#
# A mutable container is used so module-level state can be flipped without
# triggering ruff's PLW0603 (no `global` statement required).
_session_state: dict = {"ending": False}


def mark_session_ending() -> None:
    """Mark the process as in OS-shutdown teardown.

    Idempotent.  Once set, all subsequent ``AppConfig.save()`` calls become
    no-ops for the remaining lifetime of the process.
    """
    _session_state["ending"] = True


def is_session_ending() -> bool:
    """Return True if ``mark_session_ending()`` has been called."""
    return _session_state["ending"]


@dataclass
class WebDavConfig:
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    remote_path: str = WEBDAV_DEFAULT_REMOTE_PATH
    max_backups: int = WEBDAV_DEFAULT_MAX_BACKUPS
    verify_ssl: bool = True
    auto_backup: bool = True
    backup_favicons: bool = False


@dataclass
class SchedulerConfig:
    auto_sync_enabled: bool = True
    sync_interval_hours: int = DEFAULT_SYNC_INTERVAL_HOURS
    launch_on_startup: bool = False
    start_minimized: bool = False
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = DEFAULT_AUTO_BACKUP_INTERVAL_HOURS


@dataclass
class ExtractorConfig:
    custom_paths: dict = field(default_factory=dict)
    disabled_browsers: list = field(default_factory=list)
    learned_browsers: dict = field(default_factory=dict)  # Browsers discovered by smart scan
    # learned_browsers format:
    # {
    #   "detected_liebao": {
    #     "display_name": "Liebao Browser",
    #     "engine": "chromium",
    #     "data_dir": "C:\\Users\\...\\liebao\\User Data",
    #     "discovered_at": "2026-03-29T10:30:00",
    #     "profiles": ["Default", "Profile 1"]
    #   }
    # }


BUILTIN_SEARCH_ENGINES: list[tuple[str, str]] = [
    ("Google", "https://www.google.com/search?q={query}"),
    ("Bing", "https://www.bing.com/search?q={query}"),
    ("Baidu", "https://www.baidu.com/s?wd={query}"),
    ("DuckDuckGo", "https://duckduckgo.com/?q={query}"),
    ("Yandex", "https://yandex.com/search/?text={query}"),
    ("Brave Search", "https://search.brave.com/search?q={query}"),
]

BUILTIN_SEARCH_ENGINE_NAMES: list[str] = [name for name, _ in BUILTIN_SEARCH_ENGINES]

CUSTOM_ENGINE_KEY = "custom"


@dataclass
class SearchEngineConfig:
    """Search engine used by the web-search autocomplete action."""

    # Name of a builtin engine (e.g. "Google") or CUSTOM_ENGINE_KEY
    engine: str = "Google"
    # URL template — always kept in sync with the builtin selection.
    # For custom engines the user edits this directly.
    # Placeholder: {query}  →  replaced with URL-encoded query text.
    url_template: str = "https://www.google.com/search?q={query}"

    def build_url(self, query: str) -> str:
        import urllib.parse as _up

        return self.url_template.replace("{query}", _up.quote_plus(query))

    @property
    def display_name(self) -> str:
        """Return a short label for badges (max ~12 chars)."""
        if self.engine == CUSTOM_ENGINE_KEY:
            return "Custom"
        return self.engine


DEFAULT_FILTERED_URL_PREFIXES: list[str] = [
    # Chromium-based browser internal UI
    "chrome://",
    "edge://",
    "brave://",
    "opera://",
    "vivaldi://",
    "arc://",
    # Local filesystem
    "file://",
    # Special / temporary / about pages
    "about:",
    "blob:",
    "data:",
    # Browser extension protocols
    "chrome-extension://",
    "moz-extension://",
    "safari-extension://",
    # Firefox / Gecko internal protocols
    "resource://",
    "place:",
    # Chromium debug & isolated protocols
    "devtools://",
    "chrome-untrusted://",
    "chrome-error://",
    "filesystem:",
    # Script pseudo-protocols and source viewer
    "javascript:",
    "view-source:",
]


@dataclass
class PrivacyConfig:
    """Domain blacklist and URL-prefix filter management."""

    blacklisted_domains: list = field(default_factory=list)
    filtered_url_prefixes: list = field(default_factory=lambda: list(DEFAULT_FILTERED_URL_PREFIXES))


@dataclass
class UIConfig:
    """UI preferences including visible columns."""

    visible_columns: list = field(default_factory=lambda: ["title", "url", "browser", "visit_time"])
    column_widths: dict = field(default_factory=dict)
    scroll_bubble_tutorial_dismissed: bool = False
    scroll_bubble_mode: str = "full"  # "full" | "compact" | "minimal" | "hidden"


@dataclass
class OverlayConfig:
    """Quick-access overlay (Spotlight-style) settings."""

    enabled: bool = True
    filter_browsers: str = "auto"  # "auto" | "all" | browser_type
    open_with: str = "auto"  # "auto" | browser_type
    pos_offset_x: int = 0  # px offset from active-screen center
    pos_offset_y: int = 0


@dataclass
class FontConfig:
    """Custom font overrides for UI and monospace (log/code) elements."""

    enabled: bool = False
    # Comma-separated fallback family list, e.g. "Segoe UI, Microsoft YaHei"
    ui_family: str = "Segoe UI, PingFang SC, Microsoft YaHei, Noto Sans CJK SC"
    ui_size: int = 13  # px (QSS units)
    mono_family: str = "Consolas, Courier New, monospace"
    mono_size: int = 11  # px (QSS units)


@dataclass
class KeybindingsConfig:
    """Customizable keyboard shortcuts (in-app and global)."""

    # In-app shortcuts (QKeySequence format, e.g. "Ctrl+R").
    # Empty string means the shortcut is disabled.
    app: dict = field(default_factory=lambda: dict(DEFAULT_KEYBINDINGS))
    # Global hotkey for quick-access overlay (QKeySequence format).
    global_overlay: str = DEFAULT_GLOBAL_HOTKEY


@dataclass
class AppConfig:
    webdav: WebDavConfig = field(default_factory=WebDavConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    font: FontConfig = field(default_factory=FontConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    search_engine: SearchEngineConfig = field(default_factory=SearchEngineConfig)
    keybindings: KeybindingsConfig = field(default_factory=KeybindingsConfig)
    window_x: int = -1
    window_y: int = -1
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    db_path: str = ""
    language: str = ""  # empty = auto-detect from system
    theme: str = "system"  # "dark" | "light" | "system"
    last_backup_ts: int = 0
    last_sync_ts: int = 0
    master_password_hash: str = ""  # bcrypt hash; empty = no password set
    first_run_completed: bool = False
    # ── Device identity ───────────────────────────────────────────────────────
    device_uuid: str = ""  # Generated on first run; permanently unique
    device_name: str = ""  # User-editable device nickname

    # ── Runtime flags (not persisted) ────────────────────────────────────────
    # Fresh mode: uses a temporary directory, no disk reads or writes
    _fresh: bool = field(default=False, init=False, repr=False, compare=False)
    _fresh_tmp_dir: object = field(default=None, init=False, repr=False, compare=False)
    # Set to backup path (str) when config was corrupt; "" if backup also failed; None = no error
    _load_error: str | None = field(default=None, init=False, repr=False, compare=False)
    # WebDAV password decryption failure: original ciphertext preserved here so it is not
    # overwritten on the next config save before the user has a chance to re-enter the password.
    _webdav_password_ciphertext: str = field(default="", init=False, repr=False, compare=False)
    _webdav_password_decryption_failed: bool = field(default=False, init=False, repr=False, compare=False)

    def get_db_path(self) -> Path:
        """Return the database file path."""
        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(
                    prefix="HistorySync_fresh_",
                    ignore_cleanup_errors=True,
                )
            return Path(self._fresh_tmp_dir.name) / DB_FILENAME
        if self.db_path:
            return Path(self.db_path)
        return _resolve_data_dir() / DB_FILENAME

    def get_favicon_db_path(self) -> Path:
        """Return the favicon database path."""
        from src.utils.constants import FAVICON_DB_FILENAME

        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(
                    prefix="HistorySync_fresh_", ignore_cleanup_errors=True
                )
            return Path(self._fresh_tmp_dir.name) / FAVICON_DB_FILENAME
        return _resolve_config_dir() / FAVICON_DB_FILENAME

    def cleanup_fresh_tmp(self) -> None:
        """Explicitly clean up the temporary directory used in fresh mode.

        Should be called during application shutdown *after* all SQLite
        connections to files inside the temp directory have been closed.
        Safe to call even when not in fresh mode or when already cleaned up.
        """
        if self._fresh_tmp_dir is not None:
            try:
                self._fresh_tmp_dir.cleanup()
            except Exception:
                pass
            self._fresh_tmp_dir = None

    def to_dict(self) -> dict:
        webdav_dict = asdict(self.webdav)

        if webdav_dict.get("password"):
            from src.utils.security_utils import encrypt_text

            webdav_dict["password"] = encrypt_text(webdav_dict["password"])
        elif self._webdav_password_ciphertext:
            # Decryption failed on load and the user has not re-entered the password yet;
            # write back the original ciphertext so it is not silently erased.
            webdav_dict["password"] = self._webdav_password_ciphertext

        return {
            "config_version": 2,
            "webdav": webdav_dict,
            "scheduler": asdict(self.scheduler),
            "extractor": asdict(self.extractor),
            "privacy": asdict(self.privacy),
            "ui": asdict(self.ui),
            "font": asdict(self.font),
            "overlay": asdict(self.overlay),
            "search_engine": asdict(self.search_engine),
            "keybindings": asdict(self.keybindings),
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "db_path": self.db_path,
            "language": self.language,
            "theme": self.theme,
            "last_backup_ts": self.last_backup_ts,
            "last_sync_ts": self.last_sync_ts,
            "master_password_hash": self.master_password_hash,
            "first_run_completed": self.first_run_completed,
            "device_uuid": self.device_uuid,
            "device_name": self.device_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AppConfig:
        cfg = cls()
        if "webdav" in d:
            webdav_data = {k: v for k, v in d["webdav"].items() if k in WebDavConfig.__dataclass_fields__}
            if webdav_data.get("password"):
                try:
                    from src.utils.security_utils import DecryptionError, decrypt_text

                    webdav_data["password"] = decrypt_text(webdav_data["password"])
                except DecryptionError as e:
                    logging.getLogger(__name__).warning(
                        "WebDAV password decryption failed, preserving ciphertext to prevent data loss: %s", e
                    )
                    cfg._webdav_password_ciphertext = webdav_data["password"]
                    cfg._webdav_password_decryption_failed = True
                    webdav_data["password"] = ""
            cfg.webdav = WebDavConfig(**webdav_data)

        if "scheduler" in d:
            cfg.scheduler = SchedulerConfig(
                **{k: v for k, v in d["scheduler"].items() if k in SchedulerConfig.__dataclass_fields__}
            )
        if "extractor" in d:
            cfg.extractor = ExtractorConfig(
                **{k: v for k, v in d["extractor"].items() if k in ExtractorConfig.__dataclass_fields__}
            )
        if "privacy" in d:
            cfg.privacy = PrivacyConfig(
                **{k: v for k, v in d["privacy"].items() if k in PrivacyConfig.__dataclass_fields__}
            )
        if "ui" in d:
            cfg.ui = UIConfig(**{k: v for k, v in d["ui"].items() if k in UIConfig.__dataclass_fields__})
        if "font" in d:
            cfg.font = FontConfig(**{k: v for k, v in d["font"].items() if k in FontConfig.__dataclass_fields__})
        if "overlay" in d:
            cfg.overlay = OverlayConfig(
                **{k: v for k, v in d["overlay"].items() if k in OverlayConfig.__dataclass_fields__}
            )
        if "search_engine" in d:
            cfg.search_engine = SearchEngineConfig(
                **{k: v for k, v in d["search_engine"].items() if k in SearchEngineConfig.__dataclass_fields__}
            )
        if "keybindings" in d:
            kb_data = d["keybindings"]
            # Merge saved app bindings over defaults so newly added actions get defaults
            merged_app = dict(DEFAULT_KEYBINDINGS)
            if "app" in kb_data and isinstance(kb_data["app"], dict):
                merged_app.update(kb_data["app"])
            cfg.keybindings = KeybindingsConfig(
                app=merged_app,
                global_overlay=kb_data.get("global_overlay", DEFAULT_GLOBAL_HOTKEY),
            )
        for key in (
            "window_x",
            "window_y",
            "window_width",
            "window_height",
            "db_path",
            "language",
            "theme",
            "last_backup_ts",
            "last_sync_ts",
            "master_password_hash",
            "first_run_completed",
            "device_uuid",
            "device_name",
        ):
            if key in d:
                setattr(cfg, key, d[key])
        return cfg

    @classmethod
    def load(cls) -> AppConfig:
        """Load configuration from disk."""
        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        backup_file = config_dir / CONFIG_BACKUP_FILENAME
        config_dir.mkdir(parents=True, exist_ok=True)
        if not config_file.exists():
            # Primary missing — try the last-good backup before giving up.
            if backup_file.exists():
                logging.getLogger(__name__).warning("Config file missing; recovering from backup '%s'", backup_file)
                try:
                    with backup_file.open(encoding="utf-8") as f:
                        cfg = cls.from_dict(json.load(f))
                    # Restore backup as primary so subsequent saves work normally.
                    backup_file.replace(config_file)
                    return cfg
                except (json.JSONDecodeError, OSError):
                    pass
            return cls()
        try:
            with config_file.open(encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            log = logging.getLogger(__name__)
            # Primary is corrupt — try backup before falling back to defaults.
            if backup_file.exists():
                log.warning("Config file '%s' corrupt (%s); trying backup '%s'", config_file, exc, backup_file)
                try:
                    with backup_file.open(encoding="utf-8") as f:
                        cfg = cls.from_dict(json.load(f))
                    bak_corrupt = config_file.with_suffix(".json.bak")
                    try:
                        config_file.replace(bak_corrupt)
                    except OSError:
                        bak_corrupt = None
                    backup_file.replace(config_file)
                    log.warning("Recovered config from backup. Corrupt file backed up to '%s'.", bak_corrupt)
                    cfg._load_error = str(bak_corrupt) if bak_corrupt else ""
                    return cfg
                except (json.JSONDecodeError, OSError):
                    log.warning("Backup '%s' also unreadable; starting with defaults.", backup_file)

            bak_file = config_file.with_suffix(".json.bak")
            try:
                config_file.replace(bak_file)
            except OSError as bak_exc:
                logging.getLogger(__name__).warning("Could not back up corrupt config to '%s': %s", bak_file, bak_exc)
                bak_file = None

            log.error(
                "Config file '%s' is corrupt or unreadable (%s); starting with defaults. %s",
                config_file,
                exc,
                f"Backed up to '{bak_file}'." if bak_file else "Backup also failed.",
            )
            cfg = cls()
            cfg._load_error = str(bak_file) if bak_file else ""
            return cfg

    def save(self) -> None:
        """Persist configuration to disk.

        On any failure during the rename sequence, the previous good copy
        (rotated to ``config.json.prev``) is promoted back to ``config.json``
        so the directory is never left without a primary file.  If the
        process-wide session-end flag is set, this is a no-op — see the
        module-level docstring on ``_session_ending`` for the rationale.
        """
        if self._fresh:
            return

        if _session_state["ending"]:
            # Windows OS shutdown / orderly app quit in progress.
            # Avoid the non-atomic rotate-and-promote sequence entirely; the
            # on-disk file from the most recent interactive save is still good.
            return

        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        backup_file = config_dir / CONFIG_BACKUP_FILENAME
        config_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

        # Use a deterministic tmp filename rather than mkstemp's random
        # ``tmpXXXXXXXX.tmp``: on Windows, antivirus (Defender, corporate AV)
        # treats every new filename in a watched directory as a new artefact
        # and queues a full scan, holding the file handle long enough to make
        # the subsequent ``replace()`` race against AV during shutdown.  A
        # fixed name lets AV recognise the file as already-scanned.
        tmp_path = config_dir / f"{CONFIG_FILENAME}.tmp"
        rotated_backup = False
        try:
            # Write+fsync the new content into the tmp file.
            # ``open(..., "w")`` truncates any leftover tmp from a prior crashed
            # save attempt, which is the desired behaviour here.
            with tmp_path.open("w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Step A — rotate the existing primary to .prev so a previous good
            # copy is always on disk.  Skipped on first save when no primary
            # yet exists.
            if config_file.exists():
                try:
                    config_file.replace(backup_file)
                    rotated_backup = True
                except OSError as _bak_exc:
                    logging.getLogger(__name__).warning(
                        "Could not rotate config backup to '%s': %s", backup_file, _bak_exc
                    )

            # Step B — promote the new tmp into place.  If this fails (AV lock,
            # disk shutting down, etc.) we MUST restore the rotated backup so
            # the primary file does not vanish from disk.  Without this rescue,
            # every Step-B failure during Windows shutdown leaves config.json
            # missing — which is the symptom the previous fix only papered over
            # via load()'s .prev fallback.
            try:
                tmp_path.replace(config_file)
            except OSError as promote_exc:
                if rotated_backup and backup_file.exists() and not config_file.exists():
                    try:
                        backup_file.replace(config_file)
                        logging.getLogger(__name__).warning(
                            "Config promote step failed (%s); restored '%s' from backup.",
                            promote_exc,
                            config_file,
                        )
                    except OSError as restore_exc:
                        logging.getLogger(__name__).error(
                            "Config promote step failed (%s) AND restore failed (%s); "
                            "primary may be missing. Backup preserved at '%s'.",
                            promote_exc,
                            restore_exc,
                            backup_file,
                        )
                raise
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
