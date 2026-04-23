# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.utils.browser_icon_paths import find_browser_icon_path
from src.utils.path_helper import get_icons_dir

_ICONS_DIR = get_icons_dir()

# Default Icon Colors
_DEFAULT_COLOR = "#a0a8b8"
_ACTIVE_COLOR = "#5b9cf6"


def _recolor_svg_content(svg_path: str | Path, color: str) -> QByteArray:
    """
    Reads an SVG file, replaces stroke/fill colors with the specified color, and returns a QByteArray.
    """
    try:
        with Path(svg_path).open(encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{color}"', content)
        content = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{color}"', content)
        return QByteArray(content.encode("utf-8"))
    except Exception:
        return QByteArray()


def _svg_to_pixmap(svg_path: str | Path, size: int, color: str) -> QPixmap:
    """
    Renders an SVG into a QPixmap with the specified color and size.
    """
    svg_bytes = _recolor_svg_content(svg_path, color)
    if svg_bytes.isEmpty():
        return QPixmap()

    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        return QPixmap()

    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    return px


@lru_cache(maxsize=128)
def _load_svg_icon(name: str, size: int, color: str) -> QIcon:
    """Cached SVG icon loader. Caches uniquely by name, size, and color combination."""
    path = _ICONS_DIR / f"{name}.svg"
    if not path.is_file():
        return QIcon()

    icon = QIcon()
    normal_px = _svg_to_pixmap(path, size, color)
    if not normal_px.isNull():
        icon.addPixmap(normal_px, QIcon.Normal, QIcon.Off)

    active_px = _svg_to_pixmap(path, size, _ACTIVE_COLOR)
    if not active_px.isNull():
        icon.addPixmap(active_px, QIcon.Active, QIcon.Off)
        icon.addPixmap(active_px, QIcon.Normal, QIcon.On)

    return icon


def get_icon(name: str, size: int = 20, color: str = _DEFAULT_COLOR) -> QIcon:
    """
    Loads an icon by name (excluding extension).

    Parameters
    ----------
    name  : Icon filename (without .svg), e.g., "home", "settings"
    size  : Pixel size, default is 20
    color : Color for the Normal state, defaults to theme gray

    Returns an empty QIcon if the file does not exist (does not raise an exception).
    """
    return _load_svg_icon(name, size, color)


def get_themed_icon(name: str, size: int = 20) -> QIcon:
    """Automatically selects the appropriate icon color based on the current theme."""
    try:
        from src.utils.theme_manager import ThemeManager

        color = ThemeManager.instance().icon_default_color()
    except Exception:
        color = _DEFAULT_COLOR
    return _load_svg_icon(name, size, color)


def _svg_to_pixmap_colorful(svg_path: str | Path, size: int) -> QPixmap:
    """Renders an SVG into its original colored QPixmap without any recoloring."""
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        return QPixmap()
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    return px


def _find_browser_icon_path(browser_type: str) -> Path | None:
    return find_browser_icon_path(browser_type)


def _load_browser_pixmap_raw(path: Path, size: int) -> QPixmap:
    """Loads the icon as a QPixmap using the appropriate method based on its extension."""
    if path.suffix.lower() == ".svg":
        return _svg_to_pixmap_colorful(path, size)
    px = QPixmap(str(path))
    if px.isNull():
        return QPixmap()
    if px.width() != size or px.height() != size:
        from PySide6.QtCore import Qt

        px = px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return px


@lru_cache(maxsize=32)
def get_browser_pixmap(browser_type: str, size: int = 20) -> QPixmap:
    """
    Returns the original colored QPixmap of the browser brand icon, specifically for DecorationRole.
    Supports SVG and PNG formats, prioritizing SVG.
    """
    path = _find_browser_icon_path(browser_type)
    if not path:
        return QPixmap()
    return _load_browser_pixmap_raw(path, size)


@lru_cache(maxsize=32)
def get_browser_icon(browser_type: str, size: int = 20) -> QIcon:
    """
    Returns the QIcon of the browser brand icon, for use in controls like QComboBox.
    """
    px = get_browser_pixmap(browser_type, size)
    if px.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(px, QIcon.Normal)
    icon.addPixmap(px, QIcon.Active)
    return icon


def make_transparent_icon() -> QIcon:
    px = QPixmap(16, 16)
    px.fill(QColor(0, 0, 0, 0))
    icon = QIcon()
    icon.addPixmap(px, QIcon.Normal, QIcon.Off)
    return icon


def get_app_icon() -> QIcon:
    """
    Loads the main application icon.
    """
    ico_path = _ICONS_DIR / "app-icon.ico"
    if ico_path.is_file():
        return QIcon(str(ico_path))

    svg_path = _ICONS_DIR / "app-icon.svg"
    if svg_path.is_file():
        icon = QIcon()
        for sz in (16, 24, 32, 48, 64, 128, 256):
            px = _svg_to_pixmap(svg_path, sz, _ACTIVE_COLOR)
            if not px.isNull():
                icon.addPixmap(px)
        return icon

    return QIcon()
