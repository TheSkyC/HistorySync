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
    """Creates a favicon extractor instance based on BrowserDef and custom paths."""
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

    # ── Registry Operations ───────────────────────────────────

    def _register_builtin(self) -> None:
        """Registers favicon extractors for all built-in browsers (skipping disabled ones)."""
        for defn in BUILTIN_BROWSERS:
            if defn.browser_type not in self._disabled:
                self._registry[defn.browser_type] = _make_extractor(defn, self._custom)

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
        custom_paths: dict[str, str],
    ) -> None:
        """
        Incrementally updates the configuration, rebuilding only the extractors
        that have actually changed.
        """
        new_disabled = set(disabled_browsers)
        new_custom: dict[str, Path] = {bt: Path(p) for bt, p in (custom_paths or {}).items() if p}

        # Newly disabled: remove from registry
        newly_disabled = new_disabled - self._disabled
        for bt in newly_disabled:
            self._registry.pop(bt, None)
            log.info("FaviconExtractorManager: disabled '%s'", bt)

        # Newly enabled: re-register
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
