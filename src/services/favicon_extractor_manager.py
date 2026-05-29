# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from src.services.browser_defs import (
    BROWSER_DEF_MAP,
    BUILTIN_BROWSERS,
    BrowserDef,
    create_custom_browser_def,
    create_learned_browser_def,
    get_browser_def,
    register_custom_browser,
    register_learned_browser,
    unregister_browser_def,
)
from src.services.extractors.favicon_extractor import (
    BaseFaviconExtractor,
    ChromiumFaviconExtractor,
    FirefoxFaviconExtractor,
)
from src.utils.logger import get_logger

log = get_logger("favicon_extractor_manager")


def _make_extractor(
    defn: BrowserDef,
) -> BaseFaviconExtractor | None:
    """Create a favicon extractor instance for the given browser definition."""
    if defn.engine == "chromium":
        return ChromiumFaviconExtractor(defn)
    if defn.engine == "firefox":
        return FirefoxFaviconExtractor(defn)
    return None


class FaviconExtractorManager:
    def __init__(
        self,
        disabled_browsers: list[str] | None = None,
        learned_browsers: dict | None = None,
        custom_paths: dict[str, str] | None = None,
    ):
        self._disabled: set[str] = set(disabled_browsers or [])
        self._learned_browsers: dict[str, dict] = {
            bt: info for bt, info in (learned_browsers or {}).items() if isinstance(info, dict)
        }
        self._custom: dict[str, Path] = {bt: Path(p) for bt, p in (custom_paths or {}).items() if p}
        self._registry: dict[str, BaseFaviconExtractor] = {}
        self._rebuild_registry()

    # ── Registry Operations ───────────────────────────────────

    def _make_custom_def(self, browser_type: str, db_path: Path) -> BrowserDef:
        base_def = get_browser_def(browser_type)
        display_name = base_def.display_name if base_def is not None else browser_type.replace("_", " ").title()
        engine = base_def.engine if base_def is not None else "chromium"
        browser_def = create_custom_browser_def(browser_type, display_name, db_path, engine=engine)
        register_custom_browser(browser_def)
        return browser_def

    def _make_learned_def(self, browser_type: str, info: dict) -> BrowserDef:
        browser_def = create_learned_browser_def(
            browser_type=browser_type,
            display_name=info.get("display_name", browser_type),
            engine=info.get("engine", "chromium"),
            data_dir=info.get("data_dir", ""),
        )
        register_learned_browser(browser_def)
        return browser_def

    def _register_supported_extractor(
        self,
        registry: dict[str, BaseFaviconExtractor],
        defn: BrowserDef,
    ) -> None:
        extractor = _make_extractor(defn)
        if extractor is None:
            log.info(
                "FaviconExtractorManager: skipping unsupported favicon engine '%s' for '%s'",
                defn.engine,
                defn.browser_type,
            )
            return
        registry[defn.browser_type] = extractor

    def _rebuild_registry(self) -> None:
        """Rebuild the favicon extractor registry from current config state."""
        valid_custom = {bt: path for bt, path in self._custom.items() if path.is_file()}
        invalid_custom = {bt: path for bt, path in self._custom.items() if not path.is_file()}
        desired_runtime = set(self._learned_browsers) | set(valid_custom)
        builtin_browser_types = {defn.browser_type for defn in BUILTIN_BROWSERS}
        current_runtime = set(BROWSER_DEF_MAP) - builtin_browser_types
        for browser_type in current_runtime - desired_runtime:
            unregister_browser_def(browser_type)
        for defn in BUILTIN_BROWSERS:
            if defn.browser_type in desired_runtime:
                continue
            if get_browser_def(defn.browser_type) is not defn:
                unregister_browser_def(defn.browser_type)
        for browser_type, db_path in invalid_custom.items():
            log.warning(
                "FaviconExtractorManager: custom path for '%s' not found, using builtin/runtime fallback: %s",
                browser_type,
                db_path,
            )

        registry: dict[str, BaseFaviconExtractor] = {}

        for defn in BUILTIN_BROWSERS:
            if defn.browser_type in self._disabled:
                continue
            if defn.browser_type in valid_custom:
                self._register_supported_extractor(
                    registry,
                    self._make_custom_def(defn.browser_type, valid_custom[defn.browser_type]),
                )
            else:
                self._register_supported_extractor(registry, defn)

        for browser_type, info in self._learned_browsers.items():
            if browser_type in self._disabled or browser_type in registry:
                continue
            self._register_supported_extractor(registry, self._make_learned_def(browser_type, info))

        for browser_type, db_path in valid_custom.items():
            if browser_type in self._disabled or browser_type in registry:
                continue
            self._register_supported_extractor(registry, self._make_custom_def(browser_type, db_path))

        self._registry = registry

    def register(self, extractor: BaseFaviconExtractor) -> None:
        """Registers or overrides a favicon extractor."""
        self._registry[extractor.browser_type] = extractor
        log.info("FaviconExtractorManager: registered '%s'", extractor.browser_type)

    def unregister(self, browser_type: str) -> None:
        """Unregisters the favicon extractor for a specific browser."""
        self._registry.pop(browser_type, None)
        log.info("FaviconExtractorManager: unregistered '%s'", browser_type)

    # ── Query Interfaces ──────────────────────────────────────

    def get_available(
        self,
        target_browsers: list[str] | None = None,
    ) -> list[BaseFaviconExtractor]:
        """
        Returns a list of available favicon extractors.

        Parameters
        ----------
        target_browsers:
            If provided, only returns extractors for the specified browsers
            (still checked via is_available()). None means return all
            registered and available extractors.
        """
        candidates = (
            [self._registry[bt] for bt in target_browsers if bt in self._registry]
            if target_browsers is not None
            else list(self._registry.values())
        )
        return [ext for ext in candidates if ext.is_available()]

    def get_all_registered(self) -> dict[str, str]:
        """Returns a {browser_type: display_name} dict (including disabled browsers)."""
        return {bt: ext.display_name for bt, ext in self._registry.items()}

    def is_browser_disabled(self, browser_type: str) -> bool:
        return browser_type in self._disabled

    # ── Configuration Hot Reload ──────────────────────────────

    def update_config(
        self,
        disabled_browsers: list[str],
        learned_browsers: dict | None = None,
        custom_paths: dict[str, str] | None = None,
    ) -> None:
        self._disabled = set(disabled_browsers)
        self._learned_browsers = {bt: info for bt, info in (learned_browsers or {}).items() if isinstance(info, dict)}
        self._custom = {bt: Path(p) for bt, p in (custom_paths or {}).items() if p}
        self._rebuild_registry()
        log.info("FaviconExtractorManager: rebuilt registry (%d extractors)", len(self._registry))
