# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator
import configparser
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from typing import Literal

from src.utils.logger import get_logger

log = get_logger("browser_defs")

Engine = Literal["chromium", "firefox", "safari"]


@dataclass(frozen=True)
class BrowserDef:
    browser_type: str
    display_name: str
    engine: Engine
    _data_dirs: tuple[Path, ...] = field(default=(), compare=False, hash=False, repr=False)

    def is_available_on_platform(self) -> bool:
        """Return False if this browser has no release for the current OS.

        Currently the only case is Chrome Canary on Linux.
        """
        return self.browser_type not in _LINUX_UNAVAILABLE or sys.platform in ("win32", "darwin")

    def get_data_dirs(self) -> list[Path]:
        return list(self._data_dirs)

    def iter_history_db_paths(self, custom_db_path: Path | None = None) -> Iterator[tuple[str, Path]]:
        if custom_db_path is not None:
            yield "custom", custom_db_path
            return
        if self.engine == "chromium":
            yield from self._iter_chromium_history()
        elif self.engine == "safari":
            yield from self._iter_safari_history()
        else:
            yield from self._iter_firefox_history()

    def iter_favicon_db_paths(self) -> Iterator[tuple[str, Path]]:
        if self.engine == "chromium":
            yield from self._iter_chromium_favicons()
        elif self.engine == "safari":
            pass  # Safari favicons handled separately
        else:
            yield from self._iter_firefox_favicons()

    def is_history_available(self, custom_db_path: Path | None = None) -> bool:
        return any(p.exists() for _, p in self.iter_history_db_paths(custom_db_path))

    def is_favicon_available(self) -> bool:
        return any(p.exists() for _, p in self.iter_favicon_db_paths())

    def _iter_chromium_history(self) -> Iterator[tuple[str, Path]]:
        for data_dir in self._data_dirs:
            if not data_dir.exists():
                continue
            for profile_name, profile_dir in _enumerate_chromium_profiles(data_dir):
                db = profile_dir / "History"
                if db.exists():
                    yield profile_name, db

    def _iter_chromium_favicons(self) -> Iterator[tuple[str, Path]]:
        for data_dir in self._data_dirs:
            if not data_dir.exists():
                continue
            for profile_name, profile_dir in _enumerate_chromium_profiles(data_dir):
                db = profile_dir / "Favicons"
                if db.exists():
                    yield profile_name, db

    def _iter_firefox_history(self) -> Iterator[tuple[str, Path]]:
        seen: set[str] = set()
        for base_dir in self._data_dirs:
            ini = base_dir / "profiles.ini"
            if not ini.exists():
                continue
            for profile_name, db in _parse_firefox_profiles_ini(base_dir, ini, "places.sqlite"):
                key = str(db)
                if key not in seen:
                    seen.add(key)
                    yield profile_name, db

    def _iter_firefox_favicons(self) -> Iterator[tuple[str, Path]]:
        seen: set[str] = set()
        for base_dir in self._data_dirs:
            ini = base_dir / "profiles.ini"
            if not ini.exists():
                continue
            for profile_name, db in _parse_firefox_profiles_ini(base_dir, ini, "favicons.sqlite"):
                key = str(db)
                if key not in seen:
                    seen.add(key)
                    yield profile_name, db

    def _iter_safari_history(self) -> Iterator[tuple[str, Path]]:
        for data_dir in self._data_dirs:
            db = data_dir / "History.db"
            if db.exists():
                yield "Default", db


def _enumerate_chromium_profiles(user_data_dir: Path) -> list[tuple[str, Path]]:
    profiles: list[tuple[str, Path]] = []
    default = user_data_dir / "Default"
    if default.is_dir():
        profiles.append(("Default", default))
    try:
        for child in sorted(user_data_dir.iterdir()):
            if child.is_dir() and child.name.startswith("Profile "):
                profiles.append((child.name, child))
    except OSError:
        pass
    return profiles


def _parse_firefox_profiles_ini(base_dir: Path, ini_path: Path, db_filename: str) -> Iterator[tuple[str, Path]]:
    cfg = configparser.ConfigParser(strict=False)
    try:
        cfg.read(str(ini_path), encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to parse %s: %s", ini_path, exc)
        return
    for section in cfg.sections():
        if not section.startswith("Profile"):
            continue
        name = cfg.get(section, "Name", fallback="")
        path_val = cfg.get(section, "Path", fallback="")
        is_relative = cfg.getint(section, "IsRelative", fallback=1)
        if not path_val:
            continue
        profile_dir = base_dir / path_val if is_relative else Path(path_val)
        db = profile_dir / db_filename
        if db.exists():
            yield name or profile_dir.name, db


_LINUX_UNAVAILABLE: frozenset[str] = frozenset({"chrome_canary", "edge_canary"})
"""Browser types that have no Linux release and should resolve to zero paths on Linux."""


def _resolve_chromium_dirs(browser_type: str) -> tuple[Path, ...]:
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        mapping = {
            "chrome": [local / "Google" / "Chrome" / "User Data"],
            "chrome_beta": [local / "Google" / "Chrome Beta" / "User Data"],
            "chrome_canary": [local / "Google" / "Chrome SxS" / "User Data"],
            "chrome_dev": [local / "Google" / "Chrome Dev" / "User Data"],
            "chrome_for_testing": [local / "Google" / "Chrome for Testing" / "User Data"],
            "edge": [local / "Microsoft" / "Edge" / "User Data"],
            "edge_beta": [local / "Microsoft" / "Edge Beta" / "User Data"],
            "edge_dev": [local / "Microsoft" / "Edge Dev" / "User Data"],
            "edge_canary": [local / "Microsoft" / "Edge SxS" / "User Data"],
            "brave": [local / "BraveSoftware" / "Brave-Browser" / "User Data"],
            "brave_beta": [local / "BraveSoftware" / "Brave-Browser-Beta" / "User Data"],
            "brave_dev": [local / "BraveSoftware" / "Brave-Browser-Dev" / "User Data"],
            "brave_nightly": [local / "BraveSoftware" / "Brave-Browser-Nightly" / "User Data"],
            "opera": [roaming / "Opera Software" / "Opera Stable"],
            "opera_gx": [roaming / "Opera Software" / "Opera GX Stable"],
            "vivaldi": [local / "Vivaldi" / "User Data"],
            "arc": [local / "Arc" / "User Data"],
            "chromium": [local / "Chromium" / "User Data"],
            "yandex": [local / "Yandex" / "YandexBrowser" / "User Data"],
            "whale": [local / "Naver" / "Naver Whale" / "User Data"],
            "coccoc": [local / "CocCoc" / "Browser" / "User Data"],
            "thorium": [local / "Thorium" / "User Data"],
            "uc": [local / "UCWeb" / "UC Browser" / "User Data"],
        }
    elif sys.platform == "darwin":
        sup = home / "Library" / "Application Support"
        mapping = {
            "chrome": [sup / "Google" / "Chrome"],
            "chrome_beta": [sup / "Google" / "Chrome Beta"],
            "chrome_canary": [sup / "Google" / "Chrome Canary"],
            "chrome_dev": [sup / "Google" / "Chrome Dev"],
            "chrome_for_testing": [sup / "Google" / "Chrome for Testing"],
            "edge": [sup / "Microsoft Edge"],
            "edge_beta": [sup / "Microsoft Edge Beta"],
            "edge_dev": [sup / "Microsoft Edge Dev"],
            "edge_canary": [sup / "Microsoft Edge Canary"],
            "brave": [sup / "BraveSoftware" / "Brave-Browser"],
            "brave_beta": [sup / "BraveSoftware" / "Brave-Browser-Beta"],
            "brave_dev": [sup / "BraveSoftware" / "Brave-Browser-Dev"],
            "brave_nightly": [sup / "BraveSoftware" / "Brave-Browser-Nightly"],
            "opera": [sup / "com.operasoftware.Opera"],
            "opera_gx": [sup / "com.operasoftware.OperaGX"],
            "vivaldi": [sup / "Vivaldi"],
            "arc": [sup / "Arc" / "User Data"],
            "chromium": [sup / "Chromium"],
            "yandex": [sup / "Yandex" / "YandexBrowser"],
            "whale": [sup / "Naver" / "Whale"],
            "coccoc": [sup / "CocCoc" / "Browser"],
            "thorium": [sup / "Thorium"],
        }
    else:  # Linux / XDG
        cfg_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        snap = home / "snap"
        mapping = {
            "chrome": [cfg_home / "google-chrome", cfg_home / "chromium"],
            "chrome_beta": [cfg_home / "google-chrome-beta"],
            # chrome_canary intentionally omitted — no Linux release (see _LINUX_UNAVAILABLE)
            "chrome_dev": [cfg_home / "google-chrome-unstable"],
            "chrome_for_testing": [cfg_home / "google-chrome-for-testing"],
            "edge": [cfg_home / "microsoft-edge"],
            "edge_beta": [cfg_home / "microsoft-edge-beta"],
            "edge_dev": [cfg_home / "microsoft-edge-dev"],
            # edge_canary intentionally omitted — no Linux release (see _LINUX_UNAVAILABLE)
            "brave": [cfg_home / "BraveSoftware" / "Brave-Browser"],
            "brave_beta": [cfg_home / "BraveSoftware" / "Brave-Browser-Beta"],
            "brave_dev": [cfg_home / "BraveSoftware" / "Brave-Browser-Dev"],
            "brave_nightly": [cfg_home / "BraveSoftware" / "Brave-Browser-Nightly"],
            "opera": [cfg_home / "opera"],
            "opera_gx": [cfg_home / "opera-gx"],
            "vivaldi": [cfg_home / "vivaldi"],
            "arc": [],  # Arc not available on Linux
            "chromium": [cfg_home / "chromium", snap / "chromium" / "common" / ".config" / "chromium"],
            "yandex": [cfg_home / "yandex-browser"],
            "whale": [cfg_home / "naver-whale"],
            "coccoc": [cfg_home / "coccoc"],
            "thorium": [cfg_home / "thorium"],
        }
    return tuple(mapping.get(browser_type, []))


def _resolve_firefox_dirs(browser_type: str = "firefox") -> tuple[Path, ...]:
    home = Path.home()
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        mapping = {
            "firefox": appdata / "Mozilla" / "Firefox",
            "waterfox": appdata / "Waterfox",
            "librewolf": appdata / "librewolf",
            "palemoon": appdata / "Moonchild Productions" / "Pale Moon",
            "basilisk": appdata / "Moonchild Productions" / "Basilisk",
            "seamonkey": appdata / "Mozilla" / "SeaMonkey",
        }
        d = mapping.get(browser_type)
        return (d,) if d else (appdata / "Mozilla" / "Firefox",)
    if sys.platform == "darwin":
        sup = home / "Library" / "Application Support"
        mapping = {
            "firefox": sup / "Firefox",
            "waterfox": sup / "Waterfox",
            "librewolf": sup / "librewolf",
            "palemoon": sup / "Pale Moon",
            "seamonkey": sup / "SeaMonkey",
        }
        d = mapping.get(browser_type)
        return (d,) if d else (sup / "Firefox",)
    # Linux
    mapping = {
        "firefox": [home / ".mozilla" / "firefox", home / "snap" / "firefox" / "common" / ".mozilla" / "firefox"],
        "waterfox": [home / ".waterfox"],
        "librewolf": [home / ".librewolf"],
        "palemoon": [home / ".moonchild productions" / "pale moon"],
        "basilisk": [home / ".moonchild productions" / "basilisk"],
        "seamonkey": [home / ".mozilla" / "seamonkey"],
    }
    dirs = mapping.get(browser_type, [home / ".mozilla" / "firefox"])
    return tuple(dirs)


def _resolve_safari_dirs() -> tuple[Path, ...]:
    home = Path.home()
    if sys.platform == "darwin":
        return (home / "Library" / "Safari",)
    return ()


def _make_def(browser_type: str, display_name: str, engine: Engine) -> BrowserDef:
    if engine == "chromium":
        if sys.platform != "win32" and sys.platform != "darwin" and browser_type in _LINUX_UNAVAILABLE:
            dirs: tuple[Path, ...] = ()
        else:
            dirs = _resolve_chromium_dirs(browser_type)
    elif engine == "safari":
        dirs = _resolve_safari_dirs()
    else:
        dirs = _resolve_firefox_dirs(browser_type)
    return BrowserDef(
        browser_type=browser_type,
        display_name=display_name,
        engine=engine,
        _data_dirs=dirs,
    )


def make_custom_chromium_def(
    browser_type: str,
    display_name: str,
    user_data_dir: Path,
) -> BrowserDef:
    return BrowserDef(
        browser_type=browser_type,
        display_name=display_name,
        engine="chromium",
        _data_dirs=(user_data_dir,),
    )


# ── 内置浏览器列表 ─────────────────────────────

BUILTIN_BROWSERS: list[BrowserDef] = [
    # Chromium-based
    _make_def("chrome", "Google Chrome", "chromium"),
    _make_def("chrome_beta", "Google Chrome Beta", "chromium"),
    _make_def("chrome_canary", "Google Chrome Canary", "chromium"),
    _make_def("chrome_dev", "Google Chrome Dev", "chromium"),
    _make_def("chrome_for_testing", "Google Chrome for Testing", "chromium"),
    _make_def("edge", "Microsoft Edge", "chromium"),
    _make_def("edge_beta", "Microsoft Edge Beta", "chromium"),
    _make_def("edge_dev", "Microsoft Edge Dev", "chromium"),
    _make_def("edge_canary", "Microsoft Edge Canary", "chromium"),
    _make_def("brave", "Brave", "chromium"),
    _make_def("brave_beta", "Brave Beta", "chromium"),
    _make_def("brave_dev", "Brave Dev", "chromium"),
    _make_def("brave_nightly", "Brave Nightly", "chromium"),
    _make_def("opera", "Opera", "chromium"),
    _make_def("opera_gx", "Opera GX", "chromium"),
    _make_def("vivaldi", "Vivaldi", "chromium"),
    _make_def("arc", "Arc", "chromium"),
    _make_def("chromium", "Chromium", "chromium"),
    _make_def("yandex", "Yandex Browser", "chromium"),
    _make_def("whale", "Naver Whale", "chromium"),
    _make_def("coccoc", "Cốc Cốc", "chromium"),
    _make_def("thorium", "Thorium", "chromium"),
    # Firefox-based
    _make_def("firefox", "Mozilla Firefox", "firefox"),
    _make_def("waterfox", "Waterfox", "firefox"),
    _make_def("librewolf", "LibreWolf", "firefox"),
    _make_def("palemoon", "Pale Moon", "firefox"),
    _make_def("basilisk", "Basilisk", "firefox"),
    _make_def("seamonkey", "SeaMonkey", "firefox"),
    # Safari
    _make_def("safari", "Safari", "safari"),
]

BROWSER_DEF_MAP: dict[str, BrowserDef] = {d.browser_type: d for d in BUILTIN_BROWSERS}


def get_browser_def(browser_type: str) -> BrowserDef | None:
    return BROWSER_DEF_MAP.get(browser_type)
