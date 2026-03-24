# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
import sys

from src.utils.constants import APP_NAME

_runtime_config_dir: Path | None = None
_runtime_data_dir: Path | None = None


def set_runtime_paths(
    config_dir: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """在 main() 解析参数后立即调用，注入自定义路径。

    Parameters
    ----------
    config_dir:
        覆盖配置目录（config.json、secret.key 等）。
        传 None 表示不覆盖，使用平台默认值。
    data_dir:
        覆盖数据目录（history.db、logs、favicon_cache 等）。
        若未单独指定但 config_dir 有值，则与 config_dir 相同（Portable 语义）。
    """
    global _runtime_config_dir, _runtime_data_dir
    _runtime_config_dir = config_dir
    # 若 data_dir 未单独指定但 config_dir 有值，则让数据与配置同目录（portable 语义）
    _runtime_data_dir = data_dir if data_dir is not None else config_dir


# ── 平台默认路径计算 ───────────────────────────────
def _default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


# ── 公共接口 ──────────────────────────────────────────────────────────────────


def get_config_dir() -> Path:
    """返回配置目录（config.json、secret.key 等所在位置）。"""
    return _runtime_config_dir if _runtime_config_dir is not None else _default_config_dir()


def get_app_data_dir() -> Path:
    """返回应用数据根目录（DB、日志、favicon 缓存等）。"""
    return _runtime_data_dir if _runtime_data_dir is not None else _default_data_dir()


def get_log_dir() -> Path:
    if sys.platform == "darwin" and _runtime_data_dir is None:
        return Path.home() / "Library" / "Logs" / APP_NAME
    return get_app_data_dir() / "logs"


def get_icons_dir() -> Path:
    """返回图标资源目录（不随路径 override 变化）。"""
    return Path(__file__).parent.parent / "resources" / "icons"


def get_home() -> Path:
    return Path.home()


def get_username() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "User"


# ── 浏览器数据目录 ────────────────────────


def get_chrome_data_dirs() -> list[Path]:
    from src.services.browser_defs import BROWSER_DEF_MAP

    defn = BROWSER_DEF_MAP.get("chrome")
    return defn.get_data_dirs() if defn else []


def get_edge_data_dirs() -> list[Path]:
    from src.services.browser_defs import BROWSER_DEF_MAP

    defn = BROWSER_DEF_MAP.get("edge")
    return defn.get_data_dirs() if defn else []


def get_brave_data_dirs() -> list[Path]:
    from src.services.browser_defs import BROWSER_DEF_MAP

    defn = BROWSER_DEF_MAP.get("brave")
    return defn.get_data_dirs() if defn else []


def get_firefox_data_dirs() -> list[Path]:
    from src.services.browser_defs import BROWSER_DEF_MAP

    defn = BROWSER_DEF_MAP.get("firefox")
    return defn.get_data_dirs() if defn else []
