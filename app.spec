# -*- mode: python ; coding: utf-8 -*-
# app.spec — PyInstaller build spec for HistorySync
#
# Produces two independent bundles in a single pass:
#
#   dist/HistorySync/   Full GUI + embedded CLI binary
#                       → used by Setup.exe / .deb / .dmg / AppImage
#
#   dist/hsync/         Standalone CLI only (no PySide6)
#                       → used by the lean tar.gz for NAS / Docker / cron
#
# Usage:
#   pyinstaller app.spec --noconfirm --noupx
#
# The release workflow copies dist/hsync/hsync[.exe] into dist/HistorySync/
# so every installer ships both binaries in one package.

import sys
from pathlib import Path

# ── Platform-specific icon paths ─────────────────────────────────────────────
if sys.platform == "darwin":
    _icon = "src/resources/icons/app-icon.icns"
else:
    _icon = "src/resources/icons/app-icon.ico"

# Silently fall back to None if the icon is absent (e.g. a CI checkout that
# skips LFS objects); PyInstaller handles None gracefully.
_icon = _icon if Path(_icon).exists() else None

# ── Excluded modules shared by both targets ───────────────────────────────────
# Qt sub-modules HistorySync does not use (save ~40 MB from the GUI bundle)
_qt_dead_weight = [
    "Qt6Sql",    "Qt6Test",             "Qt6Xml",
    "Qt6Qml",    "Qt6Quick",            "Qt6WebEngineWidgets",
    "Qt6WebEngineCore",                 "Qt6WebChannel",
    "Qt6Positioning",                   "Qt6Sensors",
    "Qt6Nfc",    "Qt6Bluetooth",        "Qt6DataVisualization",
    "Qt6Multimedia",
]

# Standard-library and scientific dead-weight
_stdlib_dead_weight = [
    "tkinter",   "unittest",   "pdb",
    "doctest",   "pydoc",      "turtle",
    "test",      "lib2to3",
]

_science_dead_weight = [
    "scipy",     "matplotlib", "IPython",   "jupyter",
]

_common_excludes = _qt_dead_weight + _stdlib_dead_weight + _science_dead_weight

# ── Data files ────────────────────────────────────────────────────────────────
_gui_datas = [
    ("NOTICE",         "."),
    ("LICENSE",        "."),
    ("src/resources",  "resources"),   # styles, icons, locales, templates
]

# CLI only needs the subset of resources relevant to a headless export
_cli_resource_datas = [
    ("NOTICE",                      "."),
    ("LICENSE",                     "."),
    # HTML export template (if present)
    ("src/resources/templates",     "resources/templates"),
    # i18n strings used by exporter column headers (if present)
    ("src/resources/locales",       "resources/locales"),
]
# Only include paths that actually exist in this checkout
_cli_datas = [(src, dst) for src, dst in _cli_resource_datas if Path(src).exists()]

# ══════════════════════════════════════════════════════════════════════════════
# 1.  GUI — HistorySync  (windowed · full PySide6 · all resources)
# ══════════════════════════════════════════════════════════════════════════════

gui_a = Analysis(
    ["src/main.py"],
    pathex=["."],
    binaries=[],
    datas=_gui_datas,
    hiddenimports=[
        # Qt SVG support used by icon rendering
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        # WebDAV client loaded at runtime via import string
        "webdav4",
        "webdav4.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_common_excludes,
    noarchive=False,
)

gui_pyz = PYZ(gui_a.pure)

gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="HistorySync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # ← windowed; no black console box
    disable_windowed_traceback=False,
    icon=_icon,
)

gui_coll = COLLECT(
    gui_exe,
    gui_a.binaries,
    gui_a.datas,
    strip=False,
    upx=False,
    name="HistorySync",     # → dist/HistorySync/
)

# ══════════════════════════════════════════════════════════════════════════════
# 2.  CLI — hsync  (console · no PySide6 · minimal resources)
# ══════════════════════════════════════════════════════════════════════════════

cli_a = Analysis(
    ["src/cli.py"],
    pathex=["."],
    binaries=[],
    datas=_cli_datas,
    hiddenimports=[
        # WebDAV client (--backup command)
        "webdav4",
        "webdav4.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_common_excludes + [
        # CLI has zero Qt/GUI dependency — strip the entire stack
        "PySide6",
        "shiboken6",
    ],
    noarchive=False,
)

cli_pyz = PYZ(cli_a.pure)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="hsync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # ← console mode: shows stdout/stderr in terminal
    disable_windowed_traceback=False,
    icon=_icon,
)

cli_coll = COLLECT(
    cli_exe,
    cli_a.binaries,
    cli_a.datas,
    strip=False,
    upx=False,
    name="hsync",           # → dist/hsync/
)
