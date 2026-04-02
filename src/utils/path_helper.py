# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
import sys

from src.utils.constants import APP_NAME

_runtime_paths: dict[str, Path | None] = {"config_dir": None, "data_dir": None}


def set_runtime_paths(
    config_dir: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """Called immediately after argument parsing in main() to inject custom paths.

    Parameters
    ----------
    config_dir:
        Overrides the configuration directory (config.json, secret.key, etc.).
        Passing None means no override, using platform defaults.
    data_dir:
        Overrides the data directory (history.db, logs, favicon_cache, etc.).
        If not specified but config_dir is provided, it defaults to config_dir (Portable semantics).
    """
    _runtime_paths["config_dir"] = config_dir
    # If data_dir is not explicitly specified but config_dir has a value, make data and config share the same directory (portable semantics)
    _runtime_paths["data_dir"] = data_dir if data_dir is not None else config_dir


# ── Platform Default Path Calculations ────────────────────────
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


# ── Public Interfaces ─────────────────────────────────────────


def get_config_dir() -> Path:
    """Returns the configuration directory (where config.json, secret.key, etc., are located)."""
    return _runtime_paths["config_dir"] if _runtime_paths["config_dir"] is not None else _default_config_dir()


def get_app_data_dir() -> Path:
    """Returns the application data root directory (DB, logs, favicon cache, etc.)."""
    return _runtime_paths["data_dir"] if _runtime_paths["data_dir"] is not None else _default_data_dir()


def get_log_dir() -> Path:
    if sys.platform == "darwin" and _runtime_paths["data_dir"] is None:
        return Path.home() / "Library" / "Logs" / APP_NAME
    return get_app_data_dir() / "logs"


def get_icons_dir() -> Path:
    import sys

    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent.parent
    return base / "resources" / "icons"


def get_locales_dir() -> Path:
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent.parent
    return base / "resources" / "locales"


def get_templates_dir() -> Path:
    """Returns the HTML templates directory."""
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent.parent
    return base / "resources" / "templates"


def get_home() -> Path:
    return Path.home()


def get_username() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "User"


# ── Browser Data Directories ──────────────────────────────────


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
