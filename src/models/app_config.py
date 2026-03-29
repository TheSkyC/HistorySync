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
    """运行时解析配置目录。"""
    from src.utils.path_helper import get_config_dir

    return get_config_dir()


def _resolve_data_dir() -> Path:
    """运行时解析数据目录。"""
    from src.utils.path_helper import get_app_data_dir

    return get_app_data_dir()


@dataclass
class WebDavConfig:
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = ""
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
    learned_browsers: dict = field(default_factory=dict)  # 智能扫描发现的浏览器
    # learned_browsers 格式：
    # {
    #   "detected_liebao": {
    #     "display_name": "Liebao Browser",
    #     "engine": "chromium",
    #     "data_dir": "C:\\Users\\...\\liebao\\User Data",
    #     "discovered_at": "2026-03-29T10:30:00",
    #     "profiles": ["Default", "Profile 1"]
    #   }
    # }


@dataclass
class PrivacyConfig:
    """Domain blacklist management."""

    blacklisted_domains: list = field(default_factory=list)


@dataclass
class UIConfig:
    """UI preferences including visible columns."""

    visible_columns: list = field(default_factory=lambda: ["title", "url", "browser", "visit_time"])
    column_widths: dict = field(default_factory=dict)


@dataclass
class AppConfig:
    webdav: WebDavConfig = field(default_factory=WebDavConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
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

    # ── 运行时标志（不持久化）─────────────────────────────────────────────────
    # fresh 模式
    _fresh: bool = field(default=False, init=False, repr=False, compare=False)
    _fresh_tmp_dir: object = field(default=None, init=False, repr=False, compare=False)

    def get_db_path(self) -> Path:
        """
        返回数据库文件路径。
        """
        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(prefix="HistorySync_fresh_")
            return Path(self._fresh_tmp_dir.name) / DB_FILENAME
        if self.db_path:
            return Path(self.db_path)
        return _resolve_data_dir() / DB_FILENAME

    def get_favicon_db_path(self) -> Path:
        """
        返回 favicon 数据库路径。
        """
        from src.utils.constants import FAVICON_DB_FILENAME

        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(prefix="HistorySync_fresh_")
            return Path(self._fresh_tmp_dir.name) / FAVICON_DB_FILENAME
        return _resolve_config_dir() / FAVICON_DB_FILENAME

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
        ):
            if key in d:
                setattr(cfg, key, d[key])
        return cfg

    @classmethod
    def load(cls) -> AppConfig:
        """从磁盘加载配置。"""
        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        config_dir.mkdir(parents=True, exist_ok=True)
        if not config_file.exists():
            return cls()
        try:
            with config_file.open(encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self) -> None:
        """持久化配置到磁盘。"""
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
