# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# icons 目录位于 src/resources/icons/
_ICONS_DIR = Path(__file__).parent / ".." / "resources" / "icons"

# 默认图标着色
_DEFAULT_COLOR = "#a0a8b8"
_ACTIVE_COLOR = "#5b9cf6"


def _recolor_svg_content(svg_path: str | Path, color: str) -> QByteArray:
    """
    读取 SVG 并将 stroke/fill 属性颜色替换为 color，返回 QByteArray。
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
    将 SVG 渲染为指定颜色、指定尺寸的 QPixmap。
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
    """带缓存的 SVG 图标加载，同名+尺寸+颜色组合唯一缓存。"""
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
    按名称加载图标（不含扩展名）。

    参数
    ----
    name  : 图标文件名（不含 .svg），如 "home"、"settings"
    size  : 像素尺寸，默认 20
    color : Normal 状态的颜色，默认跟随主题灰色

    返回空 QIcon 表示文件不存在（不会抛异常）。
    """
    return _load_svg_icon(name, size, color)


def get_themed_icon(name: str, size: int = 20) -> QIcon:
    """根据当前主题自动选择合适的图标颜色。"""
    try:
        from src.utils.theme_manager import ThemeManager

        color = ThemeManager.instance().icon_default_color()
    except Exception:
        color = _DEFAULT_COLOR
    return _load_svg_icon(name, size, color)


def _svg_to_pixmap_colorful(svg_path: str | Path, size: int) -> QPixmap:
    """将 SVG 渲染为原色 QPixmap，不做任何着色处理。"""
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
    """
    按优先级查找浏览器图标文件：
    1. browsers/{type}.svg
    2. browsers/{type}.png
    3. browsers/web.svg
    返回找到的第一个路径，否则 None。
    """
    browsers_dir = _ICONS_DIR / "browsers"
    for name in (browser_type, "web"):
        for ext in (".svg", ".png"):
            path = browsers_dir / f"{name}{ext}"
            if path.is_file():
                return path
    return None


def _load_browser_pixmap_raw(path: Path, size: int) -> QPixmap:
    """根据扩展名用合适的方式加载图标为 QPixmap。"""
    if path.suffix.lower() == ".svg":
        return _svg_to_pixmap_colorful(path, size)
    px = QPixmap(str(path))
    if px.isNull():
        return QPixmap()
    if px.width() != size or px.height() != size:
        px = px.scaled(size, size, aspectRatioMode=1, transformMode=1)
    return px


@lru_cache(maxsize=32)
def get_browser_pixmap(browser_type: str, size: int = 20) -> QPixmap:
    """
    返回浏览器品牌图标的原色 QPixmap，专供 DecorationRole 使用。
    支持 SVG 和 PNG 格式，优先 SVG。
    """
    path = _find_browser_icon_path(browser_type)
    if not path:
        return QPixmap()
    return _load_browser_pixmap_raw(path, size)


@lru_cache(maxsize=32)
def get_browser_icon(browser_type: str, size: int = 20) -> QIcon:
    """
    返回浏览器品牌图标的 QIcon，供 QComboBox 等控件使用。
    """
    px = get_browser_pixmap(browser_type, size)
    if px.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(px, QIcon.Normal)
    icon.addPixmap(px, QIcon.Active)
    return icon


def get_app_icon() -> QIcon:
    """
    加载应用主图标。
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
