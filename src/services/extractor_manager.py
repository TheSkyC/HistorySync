# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

from src.services.browser_defs import BUILTIN_BROWSERS, get_browser_def
from src.services.extractors.base_extractor import BaseExtractor
from src.services.extractors.chromium_extractor import ChromiumExtractor
from src.services.extractors.firefox_extractor import FirefoxExtractor
from src.services.local_db import LocalDatabase
from src.utils.logger import get_logger
from src.utils.url_utils import normalize_domain

log = get_logger("extractor_manager")

_MAX_PARALLEL_WORKERS = 4

ProgressCallback = Callable[[str, str, int], None]  # (browser_type, status, count)


def _make_extractor(defn) -> BaseExtractor:
    """Factory: pick the right extractor class for a browser definition."""
    if defn.engine == "chromium":
        return ChromiumExtractor(defn)
    if defn.engine == "safari":
        from src.services.extractors.safari_extractor import SafariExtractor

        return SafariExtractor(defn)
    return FirefoxExtractor(defn)


class ExtractorManager:
    """
    Centrally manages and schedules all browser history extractors.
    Supports blacklisted domain filtering, URL-prefix filtering, and Safari extraction.
    """

    def __init__(
        self,
        db: LocalDatabase,
        disabled_browsers: list[str] | None = None,
        blacklisted_domains: list[str] | None = None,
        filtered_url_prefixes: list[str] | None = None,
        learned_browsers: dict | None = None,
        device_id: int | None = None,
    ):
        self._db = db
        self._disabled: set[str] = set(disabled_browsers or [])
        self._blacklisted_domains: set[str] = {normalize_domain(d) for d in (blacklisted_domains or [])}
        self._device_id: int | None = device_id
        self._registry: dict[str, BaseExtractor] = {}
        self._saved_extractors: dict[str, BaseExtractor] = {}
        # Import defaults lazily to avoid circular imports at module level
        from src.models.app_config import DEFAULT_FILTERED_URL_PREFIXES

        self._filtered_url_prefixes: tuple[str, ...] = tuple(
            filtered_url_prefixes if filtered_url_prefixes is not None else DEFAULT_FILTERED_URL_PREFIXES
        )
        self._register_builtin()
        self._register_learned(learned_browsers or {})

    # ── Registry ──────────────────────────────────────────────

    def _register_builtin(self) -> None:
        for defn in BUILTIN_BROWSERS:
            if defn.browser_type in self._disabled:
                continue
            self._registry[defn.browser_type] = _make_extractor(defn)

    def _register_learned(self, learned_browsers: dict) -> None:
        """Registers browsers discovered from smart scanning."""
        from src.services.browser_defs import create_learned_browser_def, register_learned_browser

        for browser_type, info in learned_browsers.items():
            if browser_type in self._disabled:
                continue

            try:
                # Create browser definition
                browser_def = create_learned_browser_def(
                    browser_type=browser_type,
                    display_name=info.get("display_name", "Unknown Browser"),
                    engine=info.get("engine", "chromium"),
                    data_dir=info.get("data_dir", ""),
                )

                # Register to the global mapping table
                register_learned_browser(browser_def)

                # Create extractor
                self._registry[browser_type] = _make_extractor(browser_def)
                log.info("Registered learned browser: %s", browser_def.display_name)

            except Exception as e:
                log.error("Failed to register learned browser %s: %s", browser_type, e)

    def register(self, extractor: BaseExtractor) -> None:
        self._registry[extractor.browser_type] = extractor
        log.info("Registered extractor: %s", extractor.display_name)

    def register_new_learned(self, learned_browsers: dict) -> None:
        """Registers newly discovered browsers at runtime."""
        self._register_learned(learned_browsers)

    def register_custom_path(self, browser_type: str, display_name: str, db_path: Path) -> None:
        extractor = ChromiumExtractor.for_custom_path(browser_type, display_name, db_path)
        self.register(extractor)

    def unregister(self, browser_type: str) -> None:
        self._registry.pop(browser_type, None)

    # ── Hot-reload ────────────────────────────────────────────

    def update_config(
        self,
        disabled_browsers: list[str],
        blacklisted_domains: list[str] | None = None,
        filtered_url_prefixes: list[str] | None = None,
    ) -> None:
        new_disabled = set(disabled_browsers)

        newly_disabled = new_disabled - self._disabled
        for bt in newly_disabled:
            if bt in self._registry:
                self._saved_extractors[bt] = self._registry.pop(bt)
            log.info("ExtractorManager: disabled '%s'", bt)

        newly_enabled = self._disabled - new_disabled
        for bt in newly_enabled:
            if bt in self._saved_extractors:
                self._registry[bt] = self._saved_extractors.pop(bt)
                log.info("ExtractorManager: re-enabled '%s' (restored saved extractor)", bt)
            else:
                defn = get_browser_def(bt)
                if defn is not None:
                    self._registry[bt] = _make_extractor(defn)
                    log.info("ExtractorManager: re-enabled '%s'", bt)

        self._disabled = new_disabled

        if blacklisted_domains is not None:
            self._blacklisted_domains = {normalize_domain(d) for d in blacklisted_domains}

        if filtered_url_prefixes is not None:
            self._filtered_url_prefixes = tuple(filtered_url_prefixes)
            log.info("ExtractorManager: updated filtered_url_prefixes (%d entries)", len(filtered_url_prefixes))

    def set_blacklisted_domains(self, domains: list[str]) -> None:
        self._blacklisted_domains = {normalize_domain(d) for d in domains}

    def set_filtered_url_prefixes(self, prefixes: list[str]) -> None:
        self._filtered_url_prefixes = tuple(prefixes)
        log.info("ExtractorManager: set_filtered_url_prefixes (%d entries)", len(prefixes))

    def set_device_id(self, device_id: int) -> None:
        self._device_id = device_id

    # ── Query ─────────────────────────────────────────────────

    def get_available_browsers(self) -> list[str]:
        return [bt for bt, ext in self._registry.items() if ext.is_available()]

    def get_all_registered(self) -> dict[str, str]:
        return {bt: ext.display_name for bt, ext in self._registry.items()}

    def iter_all_extractors(self) -> Iterator[tuple[str, BaseExtractor]]:
        return iter(self._registry.items())

    def unregister_browser(self, browser_type: str) -> None:
        """Removes a browser extractor from the runtime registry."""
        if browser_type in self._registry:
            self._registry.pop(browser_type)
            log.info("Unregistered browser extractor: %s", browser_type)

    def is_browser_disabled(self, browser_type: str) -> bool:
        return browser_type in self._disabled

    # ── Extraction ────────────────────────────────────────────

    def run_extraction(
        self,
        browser_types: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        force_full: bool = False,
    ) -> dict[str, int | None]:
        """Run extraction for the given browsers.

        Parameters
        ----------
        browser_types:
            Browsers to extract; ``None`` means all available browsers.
        progress_callback:
            Optional callback ``(browser_type, status, count)``.
        force_full:
            When ``True``, skip the incremental ``since_map`` watermark and
            re-extract **all** records from the browser databases. Existing
            records are upserted (ON CONFLICT DO UPDATE), so this is safe to
            run at any time — it will back-fill any fields (e.g. ``visit_count``,
            ``typed_count``) that were not captured during earlier syncs.
        """
        targets = [bt for bt in (browser_types or self.get_available_browsers()) if bt in self._registry]
        if not targets:
            return {}

        results: dict[str, int | None] = {}
        n_workers = min(_MAX_PARALLEL_WORKERS, len(targets))

        with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="hs-extract") as pool:
            futures = {pool.submit(self._extract_one, bt, progress_callback, force_full): bt for bt in targets}
            for future in as_completed(futures):
                bt = futures[future]
                try:
                    results[bt] = future.result()
                except Exception as exc:
                    log.error("Extraction task failed for %s: %s", bt, exc, exc_info=True)
                    if progress_callback:
                        progress_callback(bt, "error", 0)
                    results[bt] = None

        return results

    def _extract_one(
        self,
        browser_type: str,
        progress_callback: ProgressCallback | None,
        force_full: bool = False,
    ) -> int:
        extractor = self._registry[browser_type]

        if force_full:
            since_map: dict[str, int] = {}
            log.info("[%s] Full-resync mode: ignoring watermark, fetching all records", browser_type)
        else:
            since_map = self._db.get_max_visit_times(browser_type)
            if since_map:
                log.info(
                    "[%s] Incremental mode: %d profiles, since=%s",
                    browser_type,
                    len(since_map),
                    {k: time.strftime("%Y-%m-%d", time.localtime(v)) for k, v in since_map.items()},
                )

        if progress_callback:
            progress_callback(browser_type, "extracting", 0)

        records = extractor.extract(since_map=since_map)

        # Stamp all records with this device's id
        if self._device_id is not None:
            for r in records:
                r.device_id = self._device_id

        # Filter out internal/scheme-filtered URLs (chrome://, about:, data:, etc.)
        if self._filtered_url_prefixes:
            before = len(records)
            records = [r for r in records if not self._is_filtered_url(r.url)]
            after = len(records)
            if before != after:
                log.info("[%s] URL-prefix filter removed %d internal records", browser_type, before - after)

        # Filter out blacklisted domains
        if self._blacklisted_domains:
            before = len(records)
            records = [r for r in records if not self._is_blacklisted(r.url)]
            after = len(records)
            if before != after:
                log.info("[%s] Blacklist filtered %d records", browser_type, before - after)

        if progress_callback:
            progress_callback(browser_type, "saving", len(records))

        inserted = self._db.upsert_records(records)

        profile_counts: dict[str, int] = {}
        for r in records:
            profile_counts[r.profile_name] = profile_counts.get(r.profile_name, 0) + 1

        for profile_name, count in profile_counts.items():
            self._db.update_backup_stats(browser_type, profile_name, count)

        log.info(
            "Browser %s: extracted %d, inserted %d new",
            browser_type,
            len(records),
            inserted,
        )

        if progress_callback:
            progress_callback(browser_type, "done", inserted)

        return inserted

    def _is_filtered_url(self, url: str) -> bool:
        """Return True if the URL starts with any configured filtered prefix."""
        return bool(self._filtered_url_prefixes) and url.startswith(self._filtered_url_prefixes)

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return normalize_domain(domain)

    def _is_blacklisted(self, url: str) -> bool:
        """
        Return True if the URL's host matches a blacklisted domain or is its subdomain.
        """
        if not url or not self._blacklisted_domains:
            return False
        from src.utils.url_utils import extract_host

        host = normalize_domain(extract_host(url) or "")
        if not host:
            return False
        return any(host == domain or host.endswith("." + domain) for domain in self._blacklisted_domains)
