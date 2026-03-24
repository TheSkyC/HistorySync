# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from src.services.browser_defs import BUILTIN_BROWSERS, BrowserDef, get_browser_def
from src.services.extractors.favicon_extractor import (
    BaseFaviconExtractor,
    ChromiumFaviconExtractor,
    FirefoxFaviconExtractor,
)
from src.utils.logger import get_logger

log = get_logger("favicon_extractor_manager")


def _make_extractor(
    defn: BrowserDef,
    custom_paths: dict[str, Path],
) -> BaseFaviconExtractor:
    """根据 BrowserDef 和自定义路径字典创建图标提取器实例。"""
    override = custom_paths.get(defn.browser_type)
    if defn.engine == "chromium":
        return ChromiumFaviconExtractor(defn, override_dir=override)
    return FirefoxFaviconExtractor(defn)


class FaviconExtractorManager:
    def __init__(
        self,
        disabled_browsers: list[str] | None = None,
        custom_paths: dict[str, str] | None = None,
    ):
        self._disabled: set[str] = set(disabled_browsers or [])
        self._custom: dict[str, Path] = {bt: Path(p) for bt, p in (custom_paths or {}).items() if p}
        self._registry: dict[str, BaseFaviconExtractor] = {}
        self._register_builtin()

    # ── 注册表操作 ────────────────────────────────────────────

    def _register_builtin(self) -> None:
        """注册所有内置浏览器的图标提取器（跳过已禁用的）。"""
        for defn in BUILTIN_BROWSERS:
            if defn.browser_type not in self._disabled:
                self._registry[defn.browser_type] = _make_extractor(defn, self._custom)

    def register(self, extractor: BaseFaviconExtractor) -> None:
        """注册或覆盖一个图标提取器。"""
        self._registry[extractor.browser_type] = extractor
        log.info("FaviconExtractorManager: registered '%s'", extractor.browser_type)

    def unregister(self, browser_type: str) -> None:
        """注销指定浏览器的图标提取器。"""
        self._registry.pop(browser_type, None)
        log.info("FaviconExtractorManager: unregistered '%s'", browser_type)

    # ── 查询接口 ──────────────────────────────────────────────

    def get_available(self) -> list[BaseFaviconExtractor]:
        return [ext for ext in self._registry.values() if ext.is_available()]

    def get_all_registered(self) -> dict[str, str]:
        """返回 {browser_type: display_name} 字典（含已禁用的浏览器）。"""
        return {bt: ext.display_name for bt, ext in self._registry.items()}

    def is_browser_disabled(self, browser_type: str) -> bool:
        return browser_type in self._disabled

    # ── 配置热更新 ────────────────────────────────────────────

    def update_config(
        self,
        disabled_browsers: list[str],
        custom_paths: dict[str, str],
    ) -> None:
        """
        增量热更新配置，只重建真正发生变化的提取器条目。
        """
        new_disabled = set(disabled_browsers)
        new_custom: dict[str, Path] = {bt: Path(p) for bt, p in (custom_paths or {}).items() if p}

        # 新增禁用：从注册表移除
        newly_disabled = new_disabled - self._disabled
        for bt in newly_disabled:
            self._registry.pop(bt, None)
            log.info("FaviconExtractorManager: disabled '%s'", bt)

        # 取消禁用：重新注册
        newly_enabled = self._disabled - new_disabled
        for bt in newly_enabled:
            defn = get_browser_def(bt)
            if defn is not None:
                self._registry[bt] = _make_extractor(defn, new_custom)
                log.info("FaviconExtractorManager: re-enabled '%s'", bt)

        changed_custom = {
            bt
            for bt in (set(new_custom) | set(self._custom))
            if new_custom.get(bt) != self._custom.get(bt) and bt not in new_disabled
        }
        for bt in changed_custom:
            defn = get_browser_def(bt)
            if defn is not None and bt not in new_disabled:
                self._registry[bt] = _make_extractor(defn, new_custom)
                log.info("FaviconExtractorManager: rebuilt '%s' (custom path changed)", bt)

        self._disabled = new_disabled
        self._custom = new_custom
