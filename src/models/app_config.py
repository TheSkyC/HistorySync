# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile

from src.utils.constants import (
    CONFIG_FILENAME,
    DB_FILENAME,
    DEFAULT_AUTO_BACKUP_INTERVAL_HOURS,
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
class AppConfig:
    webdav: WebDavConfig = field(default_factory=WebDavConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    font: FontConfig = field(default_factory=FontConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    window_x: int = -1
    window_y: int = -1
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    db_path: str = ""
    language: str = ""  # empty = auto-detect from system
    theme: str = "dark"  # "dark" | "light" | "system"
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
            try:
                from src.utils.security_utils import encrypt_text

                webdav_dict["password"] = encrypt_text(webdav_dict["password"])
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Password encryption failed, storing as plaintext: {e}")

        return {
            "webdav": webdav_dict,
            "scheduler": asdict(self.scheduler),
            "extractor": asdict(self.extractor),
            "privacy": asdict(self.privacy),
            "ui": asdict(self.ui),
            "font": asdict(self.font),
            "overlay": asdict(self.overlay),
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
                    from src.utils.security_utils import decrypt_text

                    webdav_data["password"] = decrypt_text(webdav_data["password"])
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).warning(f"Password decryption failed, using raw value: {e}")
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
        config_dir.mkdir(parents=True, exist_ok=True)
        if not config_file.exists():
            return cls()
        try:
            with config_file.open(encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            import logging

            bak_file = config_file.with_suffix(".json.bak")
            try:
                config_file.replace(bak_file)
            except OSError as bak_exc:
                logging.getLogger(__name__).warning("Could not back up corrupt config to '%s': %s", bak_file, bak_exc)
                bak_file = None

            logging.getLogger(__name__).error(
                "Config file '%s' is corrupt or unreadable (%s); starting with defaults. %s",
                config_file,
                exc,
                f"Backed up to '{bak_file}'." if bak_file else "Backup also failed.",
            )
            cfg = cls()
            cfg._load_error = str(bak_file) if bak_file else ""
            return cfg

    def save(self) -> None:
        """Persist configuration to disk."""
        if self._fresh:
            return

        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        config_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            Path(tmp_path).replace(config_file)
        except Exception:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise
