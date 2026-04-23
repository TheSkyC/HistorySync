# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from src.utils.path_helper import get_icons_dir

_ICONS_DIR = get_icons_dir()

_BROWSER_ICON_ALIASES: dict[str, str] = {
    "chrome_for_testing": "chrome-test",
    "chrome-for-testing": "chrome-test",
}


def find_browser_icon_path(browser_type: str) -> Path | None:
    """Return the browser brand icon path without importing any Qt modules."""

    browsers_dir = _ICONS_DIR / "browsers"
    browser_type_hyphen = browser_type.replace("_", "-")
    alias = _BROWSER_ICON_ALIASES.get(browser_type) or _BROWSER_ICON_ALIASES.get(browser_type_hyphen)
    candidates = dict.fromkeys(filter(None, [alias, browser_type, browser_type_hyphen, "web"]))
    for name in candidates:
        for ext in (".svg", ".png"):
            path = browsers_dir / f"{name}{ext}"
            if path.is_file():
                return path
    return None
