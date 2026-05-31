# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import shutil
import threading

from src.utils.constants import (
    CONFIG_BACKUP_FILENAME,
    CONFIG_FILENAME,
    DB_FILENAME,
    DEFAULT_AUTO_BACKUP_INTERVAL_HOURS,
    DEFAULT_GLOBAL_HOTKEY,
    DEFAULT_KEYBINDINGS,
    DEFAULT_SYNC_INTERVAL_HOURS,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    UPDATE_MIRROR_AUTO,
    UPDATE_POLICY_NOTIFY_DOWNLOAD,
    WEBDAV_DEFAULT_MAX_BACKUPS,
    WEBDAV_DEFAULT_REMOTE_PATH,
)


def _resolve_config_dir() -> Path:
    """Resolve config directory at runtime."""
    from src.utils.path_helper import get_config_dir

    return get_config_dir()


def _resolve_data_dir() -> Path:
    """Resolve application data directory at runtime."""
    from src.utils.path_helper import get_app_data_dir

    return get_app_data_dir()


# ── Session-end guard ────────────────────────────────────────────────────────
# Process-wide flag set when the OS is shutting down (Windows WM_QUERYENDSESSION
# / WM_ENDSESSION, Qt commitDataRequest, or the orderly tray-quit path).
#
# While set, AppConfig.save() short-circuits to a no-op.  The rationale: during
# the ~5s TerminateProcess window after WM_ENDSESSION, several closeEvent and
# queued worker-finished slots all try to persist config.json back-to-back.
# Each save's two-step "rotate primary -> .prev, then promote tmp -> primary"
# sequence is non-atomic; being TerminateProcess'd between the two steps leaves
# the primary file missing on disk, which surfaces on the next launch as
# "config wiped + first-run wizard re-fired".
#
# The on-disk config from the user's last interactive change is already a
# known-good state.  Skipping all writes during session-end trades a stale
# last_sync_ts (re-derived on next launch from the scheduler watermark anyway)
# for guaranteed config integrity.
#
# A mutable container is used so module-level state can be flipped without
# triggering ruff's PLW0603 (no `global` statement required).
_session_state: dict = {"ending": False}

# Serialise all save() calls so back-to-back writes (e.g. settings change +
# sync-finished callback) cannot interleave their two-step rename sequences.
_save_lock = threading.Lock()


def mark_session_ending() -> None:
    """Mark the process as in OS-shutdown teardown.

    Idempotent.  Once set, all subsequent ``AppConfig.save()`` calls become
    no-ops for the remaining lifetime of the process.
    """
    _session_state["ending"] = True


def is_session_ending() -> bool:
    """Return True if ``mark_session_ending()`` has been called."""
    return _session_state["ending"]


@dataclass
class WebDavConfig:
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    remote_path: str = WEBDAV_DEFAULT_REMOTE_PATH
    max_backups: int = WEBDAV_DEFAULT_MAX_BACKUPS
    verify_ssl: bool = True
    auto_backup: bool = False
    backup_favicons: bool = False


@dataclass
class SchedulerConfig:
    auto_sync_enabled: bool = True
    sync_interval_hours: int = DEFAULT_SYNC_INTERVAL_HOURS
    launch_on_startup: bool = False
    start_minimized: bool = False
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = DEFAULT_AUTO_BACKUP_INTERVAL_HOURS


@dataclass
class ExtractorConfig:
    custom_paths: dict = field(default_factory=dict)
    disabled_browsers: list = field(default_factory=list)
    learned_browsers: dict = field(default_factory=dict)  # Browsers discovered by smart scan
    custom_browsers: dict = field(default_factory=dict)
    # learned_browsers format:
    # {
    #   "detected_liebao": {
    #     "display_name": "Liebao Browser",
    #     "engine": "chromium",
    #     "data_dir": "C:\\Users\\...\\liebao\\User Data",
    #     "discovered_at": "2026-03-29T10:30:00",
    #     "profiles": ["Default", "Profile 1"]
    #   }
    # }

    def get_custom_path_map(self) -> dict[str, str]:
        """Return a browser_type -> history db path mapping for runtime components.

        Supports both the legacy ``custom_paths`` format and the new
        ``custom_browsers`` records introduced for richer UI behavior.
        """
        result: dict[str, str] = {}
        for browser_type, path in self.custom_paths.items():
            if path:
                result[browser_type] = path
        for browser_type, entry in self.custom_browsers.items():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", "")
            if path:
                result[browser_type] = path
        return result

    def _resolve_default_display_name(self, browser_type: str, fallback: str | None = None) -> str:
        """Resolve a stable display name for a custom browser entry."""
        if fallback:
            return fallback

        entry = self.custom_browsers.get(browser_type)
        if isinstance(entry, dict):
            display_name = entry.get("display_name", "")
            if display_name:
                return display_name

        try:
            from src.services.browser_defs import get_browser_def, get_builtin_browser_def

            defn = get_builtin_browser_def(browser_type) or get_browser_def(browser_type)
        except Exception:
            defn = None

        if defn is not None and getattr(defn, "display_name", ""):
            return defn.display_name
        return browser_type

    def _resolve_default_engine(
        self,
        browser_type: str,
        fallback: str = "chromium",
        path_override: str | None = None,
    ) -> str:
        """Resolve the most appropriate engine for a custom browser entry."""
        entry = self.custom_browsers.get(browser_type)
        path = path_override or ""
        if isinstance(entry, dict):
            engine = entry.get("engine", "")
            if engine and not path_override:
                return engine
            if not path:
                path = entry.get("path", "")
        if not path:
            path = self.custom_paths.get(browser_type, "")

        try:
            from src.services.browser_defs import infer_browser_engine_from_path, resolve_browser_engine

            if path:
                return infer_browser_engine_from_path(path, browser_type=browser_type, fallback=fallback)
            return resolve_browser_engine(browser_type, fallback=fallback)
        except Exception:
            return fallback

    def set_custom_browser(self, browser_type: str, path: str, display_name: str | None = None) -> None:
        """Upsert a custom browser record and keep legacy custom_paths in sync."""
        entry = dict(self.custom_browsers.get(browser_type, {}))
        entry["path"] = path
        entry["display_name"] = self._resolve_default_display_name(browser_type, fallback=display_name)
        entry["engine"] = self._resolve_default_engine(
            browser_type,
            fallback=entry.get("engine", "chromium"),
            path_override=path,
        )
        entry["source"] = "custom_path"
        self.custom_browsers[browser_type] = entry
        self.custom_paths[browser_type] = path

    def remove_custom_browser(self, browser_type: str) -> None:
        self.custom_browsers.pop(browser_type, None)
        self.custom_paths.pop(browser_type, None)

    def rename_custom_browser(self, browser_type: str, display_name: str) -> None:
        entry = dict(self.custom_browsers.get(browser_type, {}))
        entry["display_name"] = display_name
        entry["engine"] = self._resolve_default_engine(browser_type, fallback=entry.get("engine", "chromium"))
        entry["source"] = "custom_path"
        if "path" not in entry:
            entry["path"] = self.custom_paths.get(browser_type, "")
        self.custom_browsers[browser_type] = entry


BUILTIN_SEARCH_ENGINES: list[tuple[str, str]] = [
    ("Google", "https://www.google.com/search?q={query}"),
    ("Bing", "https://www.bing.com/search?q={query}"),
    ("Baidu", "https://www.baidu.com/s?wd={query}"),
    ("DuckDuckGo", "https://duckduckgo.com/?q={query}"),
    ("Yandex", "https://yandex.com/search/?text={query}"),
    ("Brave Search", "https://search.brave.com/search?q={query}"),
]

BUILTIN_SEARCH_ENGINE_NAMES: list[str] = [name for name, _ in BUILTIN_SEARCH_ENGINES]

CUSTOM_ENGINE_KEY = "custom"


@dataclass
class SearchEngineConfig:
    """Search engine used by the web-search autocomplete action."""

    # Name of a builtin engine (e.g. "Google") or CUSTOM_ENGINE_KEY
    engine: str = "Google"
    # URL template — always kept in sync with the builtin selection.
    # For custom engines the user edits this directly.
    # Placeholder: {query}  →  replaced with URL-encoded query text.
    url_template: str = "https://www.google.com/search?q={query}"

    def build_url(self, query: str) -> str:
        import urllib.parse as _up

        return self.url_template.replace("{query}", _up.quote_plus(query))

    @property
    def display_name(self) -> str:
        """Return a short label for badges (max ~12 chars)."""
        if self.engine == CUSTOM_ENGINE_KEY:
            return "Custom"
        return self.engine


DEFAULT_FILTERED_URL_PREFIXES: list[str] = [
    # Chromium-based browser internal UI
    "chrome://",
    "edge://",
    "brave://",
    "opera://",
    "vivaldi://",
    "arc://",
    # Local filesystem
    "file://",
    # Special / temporary / about pages
    "about:",
    "blob:",
    "data:",
    # Browser extension protocols
    "chrome-extension://",
    "moz-extension://",
    "safari-extension://",
    # Firefox / Gecko internal protocols
    "resource://",
    "place:",
    # Chromium debug & isolated protocols
    "devtools://",
    "chrome-untrusted://",
    "chrome-error://",
    "filesystem:",
    # Script pseudo-protocols and source viewer
    "javascript:",
    "view-source:",
]


@dataclass
class PrivacyConfig:
    """Domain blacklist and URL-prefix filter management."""

    blacklisted_domains: list = field(default_factory=list)
    filtered_url_prefixes: list = field(default_factory=lambda: list(DEFAULT_FILTERED_URL_PREFIXES))


@dataclass
class UIConfig:
    """UI preferences including visible columns."""

    visible_columns: list = field(default_factory=lambda: ["title", "url", "browser", "visit_time"])
    column_widths: dict = field(default_factory=dict)
    scroll_bubble_tutorial_dismissed: bool = False
    scroll_bubble_mode: str = "full"  # "full" | "compact" | "minimal" | "hidden"


@dataclass
class OverlayConfig:
    """Quick-access overlay (Spotlight-style) settings."""

    enabled: bool = True
    filter_browsers: str = "auto"  # "auto" | "all" | browser_type
    open_with: str = "auto"  # "auto" | browser_type
    pos_offset_x: int = 0  # px offset from active-screen center
    pos_offset_y: int = 0


@dataclass
class FontConfig:
    """Custom font overrides for UI and monospace (log/code) elements."""

    enabled: bool = False
    # Comma-separated fallback family list, e.g. "Segoe UI, Microsoft YaHei"
    ui_family: str = "Segoe UI, PingFang SC, Microsoft YaHei, Noto Sans CJK SC"
    ui_size: int = 13  # px (QSS units)
    mono_family: str = "Consolas, Courier New, monospace"
    mono_size: int = 11  # px (QSS units)


@dataclass
class KeybindingsConfig:
    """Customizable keyboard shortcuts (in-app and global)."""

    # In-app shortcuts (QKeySequence format, e.g. "Ctrl+R").
    # Empty string means the shortcut is disabled.
    app: dict = field(default_factory=lambda: dict(DEFAULT_KEYBINDINGS))
    # Global hotkey for quick-access overlay (QKeySequence format).
    global_overlay: str = DEFAULT_GLOBAL_HOTKEY


@dataclass
class UpdateConfig:
    """Online-update preferences plus learned source-reachability state.

    User-facing fields (``auto_check_enabled``, ``channel``, ``policy``,
    ``prefer_mirror``) are edited from the Settings "Updates" card.  The
    remaining fields are bookkeeping the update service maintains itself:
    when the last check happened, which version the user has already seen or
    skipped, and which metadata/download source last succeeded (so a network
    where GitHub is slow does not pay the timeout penalty on every launch).
    """

    # ── User-facing preferences ──────────────────────────────
    auto_check_enabled: bool = True
    channel: str = "stable"  # one of UPDATE_CHANNELS
    policy: str = UPDATE_POLICY_NOTIFY_DOWNLOAD  # one of UPDATE_POLICIES
    prefer_mirror: str = UPDATE_MIRROR_AUTO  # one of UPDATE_MIRROR_MODES
    reminder_frequency: str = "always"  # "always" | "weekly" | "never"

    # ── Service-managed state (not directly user-editable) ───
    last_check_ts: int = 0  # epoch seconds of the last successful check
    last_seen_version: str = ""  # newest version most recently surfaced via automatic reminder
    last_seen_ts: int = 0  # epoch seconds when the automatic reminder last surfaced
    skipped_version: str = ""  # version the user explicitly chose to skip
    suppress_banner_until_ts: int = 0  # temporary "remind me later" suppression window for update banners
    suppressed_banner_version: str = ""  # version tied to the temporary suppression window
    suppress_install_until_ts: int = 0  # temporary deferral window for auto-install on quit
    suppressed_install_version: str = ""  # version tied to the install deferral window
    last_good_metadata_source: str = ""  # "dl" | "github"
    last_good_metadata_source_ts: int = 0  # when the metadata-source memory was last confirmed
    last_good_download_source: str = ""  # "mirror" | "dl" | "github"
    last_good_download_source_ts: int = 0  # when the download-source memory was last confirmed
    # Legacy shared timestamp kept for backward compatibility with older config
    # files. New code prefers the source-specific timestamps above.
    last_good_source_ts: int = 0  # when the learned sources were last confirmed


@dataclass
class AppConfig:
    webdav: WebDavConfig = field(default_factory=WebDavConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    extractor: ExtractorConfig = field(default_factory=ExtractorConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    font: FontConfig = field(default_factory=FontConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    search_engine: SearchEngineConfig = field(default_factory=SearchEngineConfig)
    keybindings: KeybindingsConfig = field(default_factory=KeybindingsConfig)
    updater: UpdateConfig = field(default_factory=UpdateConfig)
    window_x: int = -1
    window_y: int = -1
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    db_path: str = ""
    language: str = ""  # empty = auto-detect from system
    theme: str = "system"  # "dark" | "light" | "system"
    last_backup_ts: int = 0
    last_sync_ts: int = 0
    master_password_hash: str = ""  # Password hash; empty = no password set
    first_run_completed: bool = False
    # ── Device identity ───────────────────────────────────────────────────────
    device_uuid: str = ""  # Generated on first run; permanently unique
    device_name: str = ""  # User-editable device nickname

    # ── Runtime flags (not persisted) ────────────────────────────────────────
    # Fresh mode: uses a temporary directory, no disk reads or writes
    _fresh: bool = field(default=False, init=False, repr=False, compare=False)
    _fresh_tmp_dir: object = field(default=None, init=False, repr=False, compare=False)
    # Set to backup path (str) when config was corrupt; "" if backup also failed; None = no error
    _load_error: str | None = field(default=None, init=False, repr=False, compare=False)
    # ── Legacy WebDAV-password ciphertext preservation ────────────────────────
    # Older releases stored the WebDAV password as an ``ENC:<base64>`` payload
    # in ``config.json``.  Plan A moves the secret to the OS keyring (via
    # ``SecretStore``) and tries to migrate on first use.  Until that migration
    # lands successfully we keep the original ciphertext in this in-memory
    # field so :meth:`to_dict` can write it back to disk verbatim — without it,
    # a single save between load and the user opening the WebDAV settings
    # would silently erase the saved password.
    #
    # ``_webdav_password_decryption_failed`` is a UX flag: set on permanent
    # decryption failure (HMAC mismatch, corrupt payload) so the settings page
    # can prompt "Password could not be decrypted. Please re-enter it."  It is
    # **not** set merely because keyring access was deferred.
    _webdav_password_ciphertext: str = field(default="", init=False, repr=False, compare=False)
    _webdav_password_decryption_failed: bool = field(default=False, init=False, repr=False, compare=False)
    # In-memory cache of the resolved plaintext for the current process only.
    # Populated by :meth:`resolve_webdav_password` after a keyring lookup or a
    # successful legacy migration; never written to disk.
    _webdav_password_cache: str = field(default="", init=False, repr=False, compare=False)
    # Session-level negative cache: once a keyring lookup fails in this
    # process, later resolve attempts return "" without re-querying it.
    _webdav_password_unavailable_this_session: bool = field(default=False, init=False, repr=False, compare=False)
    # Serialise concurrent resolve attempts so only one thread can touch the
    # keyring and any others observe the resulting cache state.
    _webdav_resolve_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def get_db_path(self) -> Path:
        """Return the database file path."""
        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(
                    prefix="HistorySync_fresh_",
                    ignore_cleanup_errors=True,
                )
            return Path(self._fresh_tmp_dir.name) / DB_FILENAME
        if self.db_path:
            return Path(self.db_path)
        return _resolve_data_dir() / DB_FILENAME

    def get_favicon_db_path(self) -> Path:
        """Return the favicon database path."""
        from src.utils.constants import FAVICON_DB_FILENAME

        if self._fresh:
            if self._fresh_tmp_dir is None:
                import tempfile as _tempfile

                self._fresh_tmp_dir = _tempfile.TemporaryDirectory(
                    prefix="HistorySync_fresh_", ignore_cleanup_errors=True
                )
            return Path(self._fresh_tmp_dir.name) / FAVICON_DB_FILENAME
        return _resolve_config_dir() / FAVICON_DB_FILENAME

    def cleanup_fresh_tmp(self) -> None:
        """Explicitly clean up the temporary directory used in fresh mode.

        Should be called during application shutdown *after* all SQLite
        connections to files inside the temp directory have been closed.
        Safe to call even when not in fresh mode or when already cleaned up.
        """
        if self._fresh_tmp_dir is not None:
            try:
                self._fresh_tmp_dir.cleanup()
            except Exception:
                pass
            self._fresh_tmp_dir = None

    # ── WebDAV password: lazy keyring-backed resolution ─────────────────────
    #
    # The ``WebDavConfig.password`` field is plaintext-only and should be
    # populated from one of two sources:
    #
    # 1. The user typed it into the settings UI this session (lives only in
    #    ``self.webdav.password`` and ``self._webdav_password_cache``).
    # 2. A previous session saved it to the OS keyring under
    #    ``WEBDAV_PASSWORD_KEY`` (resolved on demand by
    #    :meth:`resolve_webdav_password`).
    #
    # Persistence to disk goes via :meth:`apply_webdav_password`, which writes
    # to the keyring (or its file fallback) — never to ``config.json``.

    def apply_webdav_password(self, password: str) -> None:
        """Persist ``password`` for the WebDAV server through the secret store.

        Empty / blank passwords clear the stored secret instead of writing it,
        so re-saving an empty WebDAV form removes the credential cleanly.
        Idempotent.

        Side effects:
        - Updates ``self.webdav.password`` so the in-memory config matches
          what callers will subsequently see.
        - Clears ``self._webdav_password_ciphertext`` and the failure flag
          when the new value is non-empty (a successful overwrite supersedes
          any unmigrated legacy payload).
        """
        from src.utils.secret_store import WEBDAV_PASSWORD_KEY, get_secret_store

        store = get_secret_store()
        password = password or ""

        if password:
            try:
                store.set(WEBDAV_PASSWORD_KEY, password)
            except Exception as exc:
                logging.getLogger(__name__).warning("Could not persist WebDAV password to secret store: %s", exc)
            # In-memory truth tracks what the caller just provided.
            self._webdav_password_cache = password
            self._webdav_password_ciphertext = ""
            self._webdav_password_decryption_failed = False
            self._webdav_password_unavailable_this_session = False
        else:
            try:
                store.delete(WEBDAV_PASSWORD_KEY)
            except Exception as exc:
                logging.getLogger(__name__).debug("Could not delete WebDAV password from secret store: %s", exc)
            self._webdav_password_cache = ""
            self._webdav_password_ciphertext = ""
            self._webdav_password_decryption_failed = False
            self._webdav_password_unavailable_this_session = False

        self.webdav.password = password

    def resolve_webdav_password(self) -> str:
        """Return the WebDAV password, fetching from keyring on first use.

        Resolution order:

        1. ``self.webdav.password`` — populated by the settings UI when the
           user typed a password this session.
        2. In-memory cache from a previous resolve / from a plaintext-on-disk
           legacy config that was loaded earlier in the process.
        3. Secret store (OS keyring, with file fallback) under
           ``WEBDAV_PASSWORD_KEY``.
        4. Legacy ``ENC:`` ciphertext from ``config.json``.  Decrypted once;
           on success the plaintext is migrated into the secret store and the
           ciphertext field is cleared so the next ``save()`` strips it.

        Returns ``""`` when no password is available (or migration failed
        permanently — the UI flag is set in that case).  Never raises:
        callers wire this into network-bound code paths and a missing
        password should surface as an authentication error from the server,
        not as an exception here.
        """
        with self._webdav_resolve_lock:
            if self.webdav.password:
                return self.webdav.password
            if self._webdav_password_cache:
                self.webdav.password = self._webdav_password_cache
                return self._webdav_password_cache
            if self._webdav_password_unavailable_this_session:
                return ""

            from src.utils.secret_store import WEBDAV_PASSWORD_KEY, get_secret_store

            log = logging.getLogger(__name__)
            store = get_secret_store()
            try:
                stored = store.get(WEBDAV_PASSWORD_KEY)
            except Exception as exc:
                log.warning("WebDAV password lookup failed: %s", exc)
                stored = None
            if stored:
                self._webdav_password_cache = stored
                self.webdav.password = stored
                self._webdav_password_decryption_failed = False
                self._webdav_password_unavailable_this_session = False
                # A successful keyring read means any leftover legacy ciphertext
                # is now redundant; clear it so the next save() drops it.
                if self._webdav_password_ciphertext:
                    self._webdav_password_ciphertext = ""
                return stored

            if self._webdav_password_ciphertext:
                from src.utils.secret_store import migrate_legacy_ciphertext

                try:
                    plaintext = migrate_legacy_ciphertext(WEBDAV_PASSWORD_KEY, self._webdav_password_ciphertext)
                except Exception as exc:
                    # Keep the legacy ciphertext intact so transient failures
                    # (locked keyring, missing secret.key during migration, user
                    # dismissed unlock) remain retryable on the next access.
                    log.warning("Legacy WebDAV password could not be decrypted (will retry on next access): %s", exc)
                    self._webdav_password_decryption_failed = True
                    self._webdav_password_unavailable_this_session = True
                    return ""
                if plaintext:
                    self._webdav_password_cache = plaintext
                    self.webdav.password = plaintext
                    self._webdav_password_decryption_failed = False
                    self._webdav_password_unavailable_this_session = False
                    # Clear the ciphertext so to_dict() stops re-emitting it,
                    # but only if the secret store actually accepted the value.
                    if store.has(WEBDAV_PASSWORD_KEY):
                        self._webdav_password_ciphertext = ""
                    return plaintext

            self._webdav_password_unavailable_this_session = True
            return ""

    def to_dict(self) -> dict:
        webdav_dict = asdict(self.webdav)

        # Plan A: WebDAV password lives in the OS keyring (via SecretStore),
        # never in config.json.  We always strip it from the serialised dict.
        # The single exception is preserving an unmigrated legacy ``ENC:``
        # ciphertext: until the next successful keyring read decrypts and
        # migrates it, dropping it would silently erase the user's saved
        # password.
        webdav_dict["password"] = ""
        if self._webdav_password_ciphertext:
            webdav_dict["password"] = self._webdav_password_ciphertext

        return {
            "config_version": 2,
            "webdav": webdav_dict,
            "scheduler": asdict(self.scheduler),
            "extractor": asdict(self.extractor),
            "privacy": asdict(self.privacy),
            "ui": asdict(self.ui),
            "font": asdict(self.font),
            "overlay": asdict(self.overlay),
            "search_engine": asdict(self.search_engine),
            "keybindings": asdict(self.keybindings),
            "updater": asdict(self.updater),
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "db_path": self.db_path,
            "language": self.language,
            "theme": self.theme,
            "last_backup_ts": self.last_backup_ts,
            "last_sync_ts": self.last_sync_ts,
            "master_password_hash": self.master_password_hash,
            "first_run_completed": self.first_run_completed,
            "device_uuid": self.device_uuid,
            "device_name": self.device_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AppConfig:
        cfg = cls()
        if "webdav" in d:
            webdav_data = {k: v for k, v in d["webdav"].items() if k in WebDavConfig.__dataclass_fields__}
            raw_password = webdav_data.get("password", "")
            if raw_password:
                # Plan A: never decrypt during load — that would force a
                # synchronous keyring access on every startup (the original
                # source of the Linux autostart prompt).  Instead, classify
                # the persisted value:
                #
                # - ``ENC:<base64>``: legacy ciphertext from before the
                #   keyring-direct migration.  Stash it for to_dict() to
                #   re-emit; defer decryption until something actually
                #   needs the plaintext (resolve_webdav_password()).
                # - any other non-empty value: a plaintext password that
                #   slipped through (very old config, manual edit, or a
                #   migration that completed mid-write).  Hand it to the
                #   secret store on the next write path; for now keep it in
                #   memory but never put it back into config.json.
                from src.utils.constants import ENCRYPTION_PREFIX

                if raw_password.startswith(ENCRYPTION_PREFIX):
                    cfg._webdav_password_ciphertext = raw_password
                else:
                    # Plaintext-on-disk: set the in-memory cache so the
                    # current session works, and remember the value so a
                    # subsequent save() can move it into the secret store.
                    cfg._webdav_password_cache = raw_password
                    cfg._webdav_password_ciphertext = ""
            # The on-disk value never reaches WebDavConfig.password — that
            # field is reserved for plaintext supplied at runtime (e.g. from
            # the settings UI).
            webdav_data["password"] = ""
            cfg.webdav = WebDavConfig(**webdav_data)

        if "scheduler" in d:
            cfg.scheduler = SchedulerConfig(
                **{k: v for k, v in d["scheduler"].items() if k in SchedulerConfig.__dataclass_fields__}
            )
        if "extractor" in d:
            cfg.extractor = ExtractorConfig(
                **{k: v for k, v in d["extractor"].items() if k in ExtractorConfig.__dataclass_fields__}
            )
            if cfg.extractor.custom_paths:
                for browser_type, path in cfg.extractor.custom_paths.items():
                    if not path:
                        continue
                    entry = cfg.extractor.custom_browsers.get(browser_type)
                    if not isinstance(entry, dict):
                        entry = {}
                    entry.setdefault("display_name", cfg.extractor._resolve_default_display_name(browser_type))
                    entry.setdefault("engine", cfg.extractor._resolve_default_engine(browser_type))
                    entry.setdefault("source", "custom_path")
                    entry["path"] = path
                    cfg.extractor.custom_browsers[browser_type] = entry
                cfg.extractor.custom_paths = cfg.extractor.get_custom_path_map()
        if "privacy" in d:
            cfg.privacy = PrivacyConfig(
                **{k: v for k, v in d["privacy"].items() if k in PrivacyConfig.__dataclass_fields__}
            )
        if "ui" in d:
            cfg.ui = UIConfig(**{k: v for k, v in d["ui"].items() if k in UIConfig.__dataclass_fields__})
        if "font" in d:
            cfg.font = FontConfig(**{k: v for k, v in d["font"].items() if k in FontConfig.__dataclass_fields__})
        if "overlay" in d:
            cfg.overlay = OverlayConfig(
                **{k: v for k, v in d["overlay"].items() if k in OverlayConfig.__dataclass_fields__}
            )
        if "search_engine" in d:
            cfg.search_engine = SearchEngineConfig(
                **{k: v for k, v in d["search_engine"].items() if k in SearchEngineConfig.__dataclass_fields__}
            )
        if "keybindings" in d:
            kb_data = d["keybindings"]
            # Merge saved app bindings over defaults so newly added actions get defaults
            merged_app = dict(DEFAULT_KEYBINDINGS)
            if "app" in kb_data and isinstance(kb_data["app"], dict):
                merged_app.update(kb_data["app"])
            cfg.keybindings = KeybindingsConfig(
                app=merged_app,
                global_overlay=kb_data.get("global_overlay", DEFAULT_GLOBAL_HOTKEY),
            )
        if "updater" in d and isinstance(d["updater"], dict):
            cfg.updater = UpdateConfig(
                **{k: v for k, v in d["updater"].items() if k in UpdateConfig.__dataclass_fields__}
            )
        for key in (
            "window_x",
            "window_y",
            "window_width",
            "window_height",
            "db_path",
            "language",
            "theme",
            "last_backup_ts",
            "last_sync_ts",
            "master_password_hash",
            "first_run_completed",
            "device_uuid",
            "device_name",
        ):
            if key in d:
                setattr(cfg, key, d[key])
        return cfg

    @classmethod
    def load(cls) -> AppConfig:
        """Load configuration from disk."""
        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        backup_file = config_dir / CONFIG_BACKUP_FILENAME
        tmp_file = config_dir / f"{CONFIG_FILENAME}.tmp"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Clean up any orphaned tmp file from a crashed save so the next
        # save's ``open("w")`` doesn't pick up stale data (harmless, but
        # leaving it around is untidy and confuses manual inspection).
        try:
            tmp_file.unlink(missing_ok=True)
        except OSError:
            pass

        if not config_file.exists():
            # Primary missing — try the last-good backup before giving up.
            if backup_file.exists():
                logging.getLogger(__name__).warning("Config file missing; recovering from backup '%s'", backup_file)
                try:
                    with backup_file.open(encoding="utf-8") as f:
                        cfg = cls.from_dict(json.load(f))
                    # Restore backup as primary so subsequent saves work normally.
                    # If the atomic rename fails (AV lock, pending journal ops
                    # after a power-loss reboot, etc.), fall back to a copy.
                    try:
                        backup_file.replace(config_file)
                    except OSError as _restore_exc:
                        logging.getLogger(__name__).warning(
                            "Config restore rename failed (%s); falling back to copy", _restore_exc
                        )
                        try:
                            shutil.copy2(backup_file, config_file)
                        except OSError as _copy_exc:
                            logging.getLogger(__name__).warning(
                                "Config restore copy also failed (%s); keeping recovered config in memory only",
                                _copy_exc,
                            )
                            cfg._load_error = str(backup_file)
                    return cfg
                except (json.JSONDecodeError, OSError):
                    pass
            return cls()
        try:
            with config_file.open(encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            log = logging.getLogger(__name__)
            # Primary is corrupt — try backup before falling back to defaults.
            if backup_file.exists():
                log.warning("Config file '%s' corrupt (%s); trying backup '%s'", config_file, exc, backup_file)
                try:
                    with backup_file.open(encoding="utf-8") as f:
                        cfg = cls.from_dict(json.load(f))
                except (json.JSONDecodeError, OSError):
                    log.warning("Backup '%s' also unreadable; starting with defaults.", backup_file)
                    cfg = None

                if cfg is not None:
                    # We successfully read the backup.  Now try to restore it
                    # as the primary.  If any rename step fails, we still
                    # return the recovered config — the data is good even if
                    # the on-disk housekeeping didn't complete.
                    bak_corrupt = config_file.with_suffix(".json.bak")
                    try:
                        config_file.replace(bak_corrupt)
                    except OSError:
                        bak_corrupt = None
                    try:
                        backup_file.replace(config_file)
                    except OSError as _restore_exc:
                        log.warning("Config restore rename failed (%s); falling back to copy", _restore_exc)
                        try:
                            shutil.copy2(backup_file, config_file)
                        except OSError as _copy_exc:
                            log.warning(
                                "Config restore copy also failed (%s); keeping recovered config in memory only",
                                _copy_exc,
                            )
                    log.warning("Recovered config from backup. Corrupt file backed up to '%s'.", bak_corrupt)
                    cfg._load_error = str(bak_corrupt) if bak_corrupt else ""
                    return cfg

            bak_file = config_file.with_suffix(".json.bak")
            try:
                config_file.replace(bak_file)
            except OSError as bak_exc:
                logging.getLogger(__name__).warning("Could not back up corrupt config to '%s': %s", bak_file, bak_exc)
                bak_file = None

            log.error(
                "Config file '%s' is corrupt or unreadable (%s); starting with defaults. %s",
                config_file,
                exc,
                f"Backed up to '{bak_file}'." if bak_file else "Backup also failed.",
            )
            cfg = cls()
            cfg._load_error = str(bak_file) if bak_file else ""
            return cfg

    def save(self) -> None:
        """Persist configuration to disk.

        On any failure during the rename sequence, the previous good copy
        (rotated to ``config.json.prev``) is promoted back to ``config.json``
        so the directory is never left without a primary file.  If the
        process-wide session-end flag is set, this is a no-op — see the
        module-level docstring on ``_session_ending`` for the rationale.
        """
        if self._fresh:
            return

        if _session_state["ending"]:
            # Windows OS shutdown / orderly app quit in progress.
            # Avoid the non-atomic rotate-and-promote sequence entirely; the
            # on-disk file from the most recent interactive save is still good.
            return

        with _save_lock:
            self._save_impl()

    def _save_impl(self) -> None:
        """Internal save implementation — caller must hold ``_save_lock``."""
        config_dir = _resolve_config_dir()
        config_file = config_dir / CONFIG_FILENAME
        backup_file = config_dir / CONFIG_BACKUP_FILENAME
        config_dir.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

        # Use a deterministic tmp filename rather than mkstemp's random
        # ``tmpXXXXXXXX.tmp``: on Windows, antivirus (Defender, corporate AV)
        # treats every new filename in a watched directory as a new artefact
        # and queues a full scan, holding the file handle long enough to make
        # the subsequent ``replace()`` race against AV during shutdown.  A
        # fixed name lets AV recognise the file as already-scanned.
        tmp_path = config_dir / f"{CONFIG_FILENAME}.tmp"
        rotated_backup = False
        try:
            # Write+fsync the new content into the tmp file.
            # ``open(..., "w")`` truncates any leftover tmp from a prior crashed
            # save attempt, which is the desired behaviour here.
            with tmp_path.open("w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Step A — rotate the existing primary to .prev so a previous good
            # copy is always on disk.  Skipped on first save when no primary
            # yet exists.
            if config_file.exists():
                try:
                    config_file.replace(backup_file)
                    rotated_backup = True
                except OSError as _bak_exc:
                    logging.getLogger(__name__).warning(
                        "Could not rotate config backup to '%s': %s", backup_file, _bak_exc
                    )

            # Step B — promote the new tmp into place.  If this fails (AV lock,
            # disk shutting down, etc.) we MUST restore the rotated backup so
            # the primary file does not vanish from disk.  Without this rescue,
            # every Step-B failure during Windows shutdown leaves config.json
            # missing — which is the symptom the previous fix only papered over
            # via load()'s .prev fallback.
            try:
                tmp_path.replace(config_file)
            except OSError as promote_exc:
                if rotated_backup and backup_file.exists() and not config_file.exists():
                    try:
                        backup_file.replace(config_file)
                        logging.getLogger(__name__).warning(
                            "Config promote step failed (%s); restored '%s' from backup.",
                            promote_exc,
                            config_file,
                        )
                    except OSError as restore_exc:
                        logging.getLogger(__name__).error(
                            "Config promote step failed (%s) AND restore failed (%s); "
                            "primary may be missing. Backup preserved at '%s'.",
                            promote_exc,
                            restore_exc,
                            backup_file,
                        )
                raise
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
