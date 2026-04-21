# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

# ── Application identity ─────────────────────────────────────────────────────

APP_NAME = "HistorySync"
APP_VERSION = "1.1.1"
ORG_NAME = "HistorySync"

BUNDLE_ID = "com.historysync.app"

# ── File / directory names ────────────────────────────────────────────────────

CONFIG_FILENAME = "config.json"
DB_FILENAME = "history.db"
LOG_FILENAME = "historysync.log"
SECRET_FILENAME = "secret.key"

FAVICON_DB_FILENAME = "favicons.db"
FAVICON_CACHE_DIR_NAME = "favicon_cache"

# ── Security ─────────────────────────────────────────────────────────────────

KEYRING_SERVICE = APP_NAME
KEYRING_USER = "master_key"

#: Prefix that marks a value as encrypted (stored in config.json)
ENCRYPTION_PREFIX = "ENC:"

# ── Database ──────────────────────────────────────────────────────────────────

# Number of records inserted per SQLite executemany batch.
DB_BATCH_SIZE = 2000

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per log file
LOG_BACKUP_COUNT = 3  # keep 3 rotated files

# ── UI / window defaults ──────────────────────────────────────────────────────

DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 10  # pt

DEFAULT_WINDOW_WIDTH = 1100  # px
DEFAULT_WINDOW_HEIGHT = 700  # px

# ── Shutdown timeouts ─────────────────────────────────────────────────────────

SCHEDULER_SHUTDOWN_TIMEOUT_MS = 8_000
FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS = 10_000

# ── Favicon extraction ────────────────────────────────────────────────────────

# Maximum seconds a single browser's favicon extraction may run
FAVICON_EXTRACTOR_TIMEOUT_SEC = 60

# Days after which a cached favicon is considered stale and re-extracted
FAVICON_TTL_DAYS = 30

# Maximum number of pixmap entries kept in the in-memory LRU cache
FAVICON_LRU_MAX_SIZE = 600

# Colour palette used to generate letter-avatar fallback icons
FAVICON_LETTER_PALETTE: list[str] = [
    "#4285F4",
    "#EA4335",
    "#34A853",
    "#FBBC04",
    "#7C4DFF",
    "#FF6D00",
    "#00BCD4",
    "#8BC34A",
    "#FF6B6B",
    "#4ECDC4",
    "#45B7D1",
    "#C678DD",
]

# ── WebDAV / backup defaults ──────────────────────────────────────────────────

WEBDAV_DEFAULT_REMOTE_PATH = "/HistorySync/"
WEBDAV_DEFAULT_MAX_BACKUPS = 10

# Filename prefix for remote backup archives, e.g. ``history_1700000000.zip``
WEBDAV_BACKUP_NAME_PREFIX = "history_"

# Lightweight manifest in WebDAV root — lets clients check "do I need to sync?" cheaply
WEBDAV_MANIFEST_FILENAME = "sync_manifest.json"

# Metadata file embedded inside each backup ZIP
SNAPSHOT_INFO_FILENAME = "snapshot_info.json"

# ── Scheduler defaults ────────────────────────────────────────────────────────

DEFAULT_SYNC_INTERVAL_HOURS = 2
DEFAULT_AUTO_BACKUP_INTERVAL_HOURS = 48

# ── Extractor ─────────────────────────────────────────────────────────────────

# Maximum number of browser extractors that run concurrently
EXTRACTOR_MAX_PARALLEL_WORKERS = 4

# Seconds allowed to copy a live SQLite database (WAL-safe file copy)
DB_COPY_TIMEOUT_SEC = 10

# ── Keybindings ───────────────────────────────────────────────────────────────

# Default in-app keyboard shortcuts (QKeySequence format).
DEFAULT_KEYBINDINGS: dict[str, str] = {
    # Navigation
    "goto_dashboard": "Ctrl+1",
    "goto_history": "Ctrl+2",
    "goto_bookmarks": "Ctrl+3",
    "goto_settings": "Ctrl+4",
    "goto_logs": "Ctrl+5",
    "goto_stats": "Ctrl+6",
    # Global actions
    "trigger_sync": "Ctrl+R",
    "focus_search": "Ctrl+F",
    # History page
    "delete_selected": "Del",
    "history_open_selected": "Return",
    "history_copy_url": "Ctrl+C",
    "history_copy_title_url": "Ctrl+Shift+C",
    "history_toggle_bookmark": "Ctrl+B",
    "history_add_note": "Ctrl+N",
    "history_open_export": "Ctrl+E",
    "history_hide_selected": "",
    # Bookmarks page
    "bm_open": "Return",
    "bm_copy_url": "Ctrl+C",
    "bm_delete": "Del",
    "bm_add_note": "Ctrl+N",
    "bm_locate": "Ctrl+L",
    # Statistics page
    "stats_prev": "Alt+Left",
    "stats_next": "Alt+Right",
    # Settings page
    "settings_save": "Ctrl+S",
}

# Default global hotkey (pynput format).
DEFAULT_GLOBAL_HOTKEY: str = "Ctrl+Shift+H"

# Map QKeySequence display format to pynput format for global hotkeys.
_PYNPUT_MODIFIER_MAP: dict[str, str] = {
    "Ctrl": "<ctrl>",
    "Shift": "<shift>",
    "Alt": "<alt>",
    "Meta": "<cmd>",
}


def qt_keyseq_to_pynput(seq: str) -> str:
    """Convert a Qt-style key sequence like 'Ctrl+Shift+H' to pynput format '<ctrl>+<shift>+h'."""
    if not seq:
        return ""
    parts = [p.strip() for p in seq.split("+")]
    result = []
    for p in parts:
        mapped = _PYNPUT_MODIFIER_MAP.get(p)
        if mapped:
            result.append(mapped)
        else:
            result.append(p.lower())
    return "+".join(result)
