# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0
"""
hsync — HistorySync headless CLI.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CLASSIC FLAGS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sync browser history:
    hsync -s  /  hsync --sync
    hsync -s --browsers chrome,firefox

Backup to WebDAV:
    hsync -b  /  hsync --backup

Sync then backup in one shot:
    hsync -sb

Export history:
    hsync -e history.csv
    hsync -e history.json --keyword python --after 2024-01-01
    hsync -e report.html --format html --embed-icons
    hsync -e out.csv --domain github.com --domain google.com

Show database statistics:
    hsync -S  /  hsync --status
    hsync -S --json          # machine-readable JSON

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SUBCOMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Search history:
    hsync search                             # browse recent history (latest 20)
    hsync search --limit 100                 # browse latest 100 records
    hsync search -i                          # interactive mode with keyboard navigation
    hsync search python                      # simple keyword search
    hsync search "domain:github.com python"  # structured query
    hsync search "after:2024-01-01 browser:chrome" --limit 50
    hsync search "is:bookmarked tag:work" --format json
    hsync search "react -tutorial" --open   # open first result in browser

Restore from WebDAV:
    hsync restore                            # list backups and merge interactively
    hsync restore --latest                   # merge latest backup automatically
    hsync restore --list                     # list available backups (JSON)
    hsync restore --replace                  # replace mode: overwrite local database

Database maintenance:
    hsync db vacuum           # VACUUM + ANALYZE
    hsync db rebuild-fts      # rebuild full-text search index
    hsync db normalize        # normalise domain names
    hsync db stats            # alias for --status (supports --json)

Config management:
    hsync config list                        # list all config keys and values
    hsync config get webdav.url              # read a single value
    hsync config set webdav.enabled true     # write a value
    hsync config set webdav.url https://...

Interactive guided menu:
    hsync -i  /  hsync --interactive

Watch (continuous sync):
    hsync -s -w 30            # sync every 30 minutes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SCRIPTING / CI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    hsync -s -q && echo "ok" || echo "failed"
    hsync -s --no-color 2>&1 | tee sync.log
    hsync -S --json | jq .record_count
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

# ── Bootstrap ────────────────────────────────────────────────────────────────
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ══════════════════════════════════════════════════════════════════════════════
# Terminal / ANSI helpers
# ══════════════════════════════════════════════════════════════════════════════


def _try_enable_windows_vt() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


_VT_OK = _try_enable_windows_vt()
_NO_COLOR: bool = (
    not sys.stdout.isatty()
    or bool(os.environ.get("NO_COLOR"))
    or os.environ.get("TERM") == "dumb"
    or (sys.platform == "win32" and not _VT_OK)
)


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"


def _bold(t: str) -> str:
    return _c("1", t)


def _dim(t: str) -> str:
    return _c("2", t)


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _ok(msg: str) -> None:
    print(f"  {_green('✔')}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_yellow('⚠')}  {msg}", file=sys.stderr)


def _err(msg: str) -> None:
    print(f"  {_red('✖')}  {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"     {msg}")


def _hint(msg: str) -> None:
    print(f"     {_dim('→  ' + msg)}")


def _section(title: str) -> None:
    width = min(shutil.get_terminal_size((80, 24)).columns - 2, 60)
    bar = _dim("─" * width)
    print(f"\n{_bold(title)}\n{bar}")


def _kv(key: str, value: str, key_width: int = 14) -> None:
    print(f"     {_dim(key.ljust(key_width) + ' :  ')}{value}")


# ══════════════════════════════════════════════════════════════════════════════
# Progress bar
# ══════════════════════════════════════════════════════════════════════════════


class _ProgressBar:
    """Width-adaptive terminal progress bar with ETA."""

    def __init__(self, total: int, quiet: bool = False) -> None:
        self.total = total
        self.quiet = quiet
        self._start = time.monotonic()
        self._last_pct = -1

    def update(self, current: int) -> None:
        if self.quiet or self.total <= 0:
            return
        pct = int(current * 100 / self.total)
        if pct == self._last_pct:
            return
        self._last_pct = pct

        cols = shutil.get_terminal_size((80, 24)).columns
        bar_width = max(10, min(40, cols - 20))
        filled = int(bar_width * pct / 100)
        bar = _green("█" * filled) + _dim("░" * (bar_width - filled))

        elapsed = time.monotonic() - self._start
        if pct > 0 and elapsed > 0.5:
            eta = elapsed / pct * (100 - pct)
            eta_str = _dim(f" ETA {eta:.0f}s") if eta >= 1 else ""
        else:
            eta_str = ""

        print(f"\r  [{bar}] {pct:3d}%{eta_str}", end="", flush=True)

    def done(self) -> None:
        if not self.quiet:
            print()


# ══════════════════════════════════════════════════════════════════════════════
# Shell completion setup
# ══════════════════════════════════════════════════════════════════════════════


def _setup_shell_completion(parser: argparse.ArgumentParser) -> None:
    """Configure argcomplete for intelligent shell completion.

    Provides context-aware completions for:
    - Subcommands (db, config)
    - Format choices (csv, json, html)
    - Config keys (webdav.url, scheduler.auto_sync_enabled, etc.)
    - Boolean values (true, false)

    Installation (one-time setup):
        # Bash
        activate-global-python-argcomplete --user
        # or add to ~/.bashrc:
        eval "$(register-python-argcomplete hsync)"

        # Zsh
        autoload -U bashcompinit && bashcompinit
        eval "$(register-python-argcomplete hsync)"
        # or add to ~/.zshrc

        # Fish
        register-python-argcomplete --shell fish hsync > ~/.config/fish/completions/hsync.fish
    """
    try:
        import argcomplete
    except ImportError:
        return

    # Custom completer for config keys
    def _config_key_completer(prefix, **_kwargs):
        return [k for k in _CONFIG_KEYS if k.startswith(prefix)]

    # Custom completer for config values (context-aware)
    def _config_value_completer(_prefix, parsed_args, **_kwargs):
        key = getattr(parsed_args, "key", None)
        if not key or key not in _CONFIG_KEYS:
            return []
        _, _, expected_type = _CONFIG_KEYS[key]
        if expected_type is bool:
            return ["true", "false"]
        return []

    # Custom completer for browser types
    def _browser_completer(prefix, **_kwargs):
        common_browsers = [
            "chrome",
            "firefox",
            "edge",
            "safari",
            "brave",
            "opera",
            "vivaldi",
            "arc",
            "chromium",
        ]
        return [b for b in common_browsers if b.startswith(prefix)]

    # Custom completer for search query tokens
    def _search_query_completer(prefix, **_kwargs):
        tokens = [
            "domain:",
            "after:",
            "before:",
            "title:",
            "url:",
            "browser:",
            "device:",
            "is:bookmarked",
            "has:note",
            "tag:",
        ]
        if ":" in prefix:
            token_type = prefix.split(":")[0] + ":"
            if token_type == "browser:":
                browser_prefix = prefix.split(":", 1)[1]
                return [token_type + b for b in _browser_completer(browser_prefix)]
            if token_type == "is:":
                return ["is:bookmarked"]
            if token_type == "has:":
                return ["has:note"]
        return [t for t in tokens if t.startswith(prefix)]

    # Attach completers to specific arguments
    for action in parser._actions:
        if action.dest == "format":
            action.completer = argcomplete.completers.ChoicesCompleter(["csv", "json", "html"])
        elif action.dest == "browser":
            action.completer = _browser_completer

    # Find subparsers and attach completers
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # Search subcommand
            if "search" in action.choices:
                search_parser = action.choices["search"]
                for search_action in search_parser._actions:
                    if search_action.dest == "query":
                        search_action.completer = _search_query_completer
                    elif search_action.dest == "format":
                        search_action.completer = argcomplete.completers.ChoicesCompleter(
                            ["table", "json", "tsv", "csv"]
                        )

            # Config subcommand
            if "config" in action.choices:
                config_parser = action.choices["config"]
                for cfg_action in config_parser._actions:
                    if isinstance(cfg_action, argparse._SubParsersAction):
                        if "get" in cfg_action.choices:
                            get_parser = cfg_action.choices["get"]
                            for get_action in get_parser._actions:
                                if get_action.dest == "key":
                                    get_action.completer = _config_key_completer
                        if "set" in cfg_action.choices:
                            set_parser = cfg_action.choices["set"]
                            for set_action in set_parser._actions:
                                if set_action.dest == "key":
                                    set_action.completer = _config_key_completer
                                elif set_action.dest == "value":
                                    set_action.completer = _config_value_completer

    # Enable argcomplete
    argcomplete.autocomplete(parser)


# ══════════════════════════════════════════════════════════════════════════════
# Argument parser
# ══════════════════════════════════════════════════════════════════════════════


def _add_global_args(p: argparse.ArgumentParser) -> None:
    path_grp = p.add_argument_group("Storage")
    path_mutex = path_grp.add_mutually_exclusive_group()
    path_mutex.add_argument(
        "--config-dir", metavar="PATH", help="Custom config and data directory. Mutually exclusive with --portable."
    )
    path_mutex.add_argument(
        "--portable", action="store_true", help="Portable mode: store all data beside the hsync binary."
    )

    out_grp = p.add_argument_group("Output control")
    out_grp.add_argument("-v", "--verbose", action="store_true", help="Enable debug-level logging")
    out_grp.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output; only print errors to stderr"
    )
    out_grp.add_argument("--no-color", action="store_true", help="Disable ANSI colour (also via NO_COLOR env var)")
    out_grp.add_argument(
        "--dry-run", action="store_true", help="Discover/validate without writing anything to disk or network"
    )


def _build_parser() -> argparse.ArgumentParser:
    from src.utils.constants import APP_VERSION

    parser = argparse.ArgumentParser(
        prog="hsync",
        description=f"hsync {APP_VERSION} — HistorySync headless CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.strip(),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Launch a guided interactive menu (great for first-time use)"
    )

    # ── Classic action flags ──────────────────────────────────────────────────
    act = parser.add_argument_group("Actions  (use at least one, or a subcommand)")
    act.add_argument(
        "-s", "--sync", action="store_true", help="Extract browser history and import it into the local database"
    )
    act.add_argument(
        "-b", "--backup", action="store_true", help="Upload a zipped snapshot of the local database to WebDAV"
    )
    act.add_argument(
        "-e", "--export", metavar="FILE", help="Export history to FILE (.csv/.json/.html; override with --format)"
    )
    act.add_argument("-S", "--status", action="store_true", help="Print database statistics and exit")
    act.add_argument(
        "--json", action="store_true", help="With --status or db stats: emit JSON instead of human-readable text"
    )

    # ── Sync options ──────────────────────────────────────────────────────────
    sync_grp = parser.add_argument_group("Sync options")
    sync_grp.add_argument(
        "--browsers", metavar="LIST", help="Comma-separated browser types to sync (default: all). E.g. chrome,firefox"
    )
    sync_grp.add_argument(
        "-w",
        "--watch",
        metavar="MINUTES",
        type=int,
        help="Run --sync repeatedly every MINUTES minutes. Press Ctrl-C to stop.",
    )

    # ── Export options ────────────────────────────────────────────────────────
    exp_grp = parser.add_argument_group("Export options")
    exp_grp.add_argument(
        "--format",
        metavar="FMT",
        choices=["csv", "json", "html"],
        help="Export format: csv | json | html  (default: inferred from extension)",
    )
    exp_grp.add_argument(
        "--columns",
        metavar="COLS",
        help=(
            "Comma-separated column list (default: all). "
            "Available: id,title,url,visit_time,visit_count,browser_type,"
            "profile_name,domain,metadata,typed_count,first_visit_time,"
            "transition_type,visit_duration"
        ),
    )
    exp_grp.add_argument("--embed-icons", action="store_true", help="Embed favicons as Base64 data-URIs in HTML export")
    exp_grp.add_argument("--keyword", metavar="TEXT", help="Filter: full-text keyword search")
    exp_grp.add_argument("--regex", action="store_true", help="Treat --keyword as a Python regular expression")
    exp_grp.add_argument("--browser", metavar="TYPE", help="Filter: browser type (e.g. chrome, firefox, edge)")
    exp_grp.add_argument("--after", metavar="DATE", help="Filter: include records on or after DATE (YYYY-MM-DD)")
    exp_grp.add_argument("--before", metavar="DATE", help="Filter: include records on or before DATE (YYYY-MM-DD)")
    exp_grp.add_argument(
        "--domain",
        metavar="HOST",
        action="append",
        help="Filter: restrict to a domain. Repeatable: --domain a.com --domain b.com",
    )

    # ── Storage + output (on main parser) ─────────────────────────────────────
    _add_global_args(parser)

    # ── Subcommands ───────────────────────────────────────────────────────────
    subs = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    # --- db -------------------------------------------------------------------
    db_p = subs.add_parser(
        "db",
        help="Database maintenance (vacuum / rebuild-fts / normalize / stats)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n  hsync db vacuum\n  hsync db rebuild-fts\n  hsync db normalize\n  hsync db stats --json\n"
        ),
    )
    db_subs = db_p.add_subparsers(dest="db_cmd", metavar="CMD", required=True)
    p_vac = db_subs.add_parser("vacuum", help="VACUUM the database and ANALYZE")
    p_fts = db_subs.add_parser("rebuild-fts", help="Rebuild the full-text search index")
    p_nor = db_subs.add_parser("normalize", help="Normalise domain names in all records")
    p_dst = db_subs.add_parser("stats", help="Show database statistics (alias for hsync -S)")
    p_dst.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    for p in (p_vac, p_fts, p_nor, p_dst):
        _add_global_args(p)

    # --- search ---------------------------------------------------------------
    search_p = subs.add_parser(
        "search",
        help="Search history records with structured query syntax",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Query syntax:\n"
            "  domain:github.com      - filter by domain\n"
            "  after:2023-01-01       - date range start\n"
            "  before:2024-01-01      - date range end\n"
            "  title:python           - search in title only\n"
            "  url:github             - search in URL only\n"
            "  browser:chrome         - filter by browser\n"
            "  device:laptop          - filter by device name/UUID\n"
            "  -react                 - exclude term\n"
            "  is:bookmarked          - only bookmarked records\n"
            "  has:note               - only records with annotations\n"
            "  tag:work               - filter bookmarks by tag\n\n"
            "Examples:\n"
            "  hsync search                                # browse recent history\n"
            "  hsync search -i                             # interactive mode\n"
            "  hsync search python\n"
            "  hsync search 'domain:github.com python'\n"
            "  hsync search 'after:2024-01-01 browser:chrome'\n"
            "  hsync search 'is:bookmarked tag:work' --limit 50\n"
            "  hsync search 'react -tutorial' --format json\n"
            "  hsync search 'python async' --open\n"
        ),
    )
    search_p.add_argument("query", nargs="?", default="", help="Search query with structured tokens")
    search_p.add_argument("--limit", type=int, default=20, help="Maximum number of results (default: 20)")
    search_p.add_argument(
        "--format",
        choices=["table", "json", "tsv", "csv"],
        default="table",
        help="Output format: table (default) | json | tsv | csv",
    )
    search_p.add_argument("--open", action="store_true", help="Open the first result URL in default browser")
    search_p.add_argument(
        "--columns",
        metavar="COLS",
        help="Comma-separated columns for table/tsv/csv (default: title,url,visit_time,browser_type)",
    )
    search_p.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive mode: refine search and browse results with keyboard navigation",
    )
    _add_global_args(search_p)

    # --- restore --------------------------------------------------------------
    restore_p = subs.add_parser(
        "restore",
        help="Restore database from WebDAV backup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "By default, restore merges backup records with your local database.\n"
            "Use --replace to completely replace the local database instead.\n\n"
            "Examples:\n"
            "  hsync restore                    # list backups and merge interactively\n"
            "  hsync restore --latest           # merge latest backup automatically\n"
            "  hsync restore --list             # list backups in JSON format\n"
            "  hsync restore --replace          # replace mode: overwrite local database\n"
        ),
    )
    restore_p.add_argument(
        "--latest", action="store_true", help="Automatically restore the latest backup without prompting"
    )
    restore_p.add_argument("--list", action="store_true", help="List available backups in JSON format and exit")
    restore_p.add_argument(
        "--replace",
        action="store_true",
        help="Replace mode: completely overwrite local database (default is merge)",
    )
    restore_p.add_argument(
        "--restore-favicons", action="store_true", help="Also restore favicon cache (if available in backup)"
    )
    _add_global_args(restore_p)

    # --- config ---------------------------------------------------------------
    cfg_p = subs.add_parser(
        "config",
        help="Read and write configuration values",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Settable keys (section.field):\n"
            "  webdav.enabled / url / username / remote_path\n"
            "  webdav.max_backups / verify_ssl / auto_backup / backup_favicons\n"
            "  scheduler.auto_sync_enabled / sync_interval_hours\n"
            "  scheduler.auto_backup_enabled / auto_backup_interval_hours\n"
            "  scheduler.launch_on_startup\n"
            "  theme  (dark|light|system)\n"
            "  language  (e.g. zh_CN, or empty for auto)\n\n"
            "Examples:\n"
            "  hsync config list\n"
            "  hsync config get webdav.url\n"
            "  hsync config set webdav.enabled true\n"
            "  hsync config set webdav.url https://dav.example.com/\n"
        ),
    )
    cfg_subs = cfg_p.add_subparsers(dest="cfg_cmd", metavar="CMD", required=True)
    p_cls = cfg_subs.add_parser("list", help="List all configuration keys and current values")
    p_cgt = cfg_subs.add_parser("get", help="Print the value of one config key")
    p_cgt.add_argument("key", help="Dot-separated key path, e.g. webdav.url")
    p_cst = cfg_subs.add_parser("set", help="Set a config key to a new value")
    p_cst.add_argument("key", help="Dot-separated key path, e.g. webdav.enabled")
    p_cst.add_argument("value", help="New value (booleans: true/false, integers: digits)")
    for p in (p_cls, p_cgt, p_cst):
        _add_global_args(p)

    # ── Shell completion ──────────────────────────────────────────────────────
    _setup_shell_completion(parser)

    return parser


# ══════════════════════════════════════════════════════════════════════════════
# Bootstrap helpers
# ══════════════════════════════════════════════════════════════════════════════


def _setup_paths(args: argparse.Namespace) -> None:
    from src.utils.path_helper import set_runtime_paths

    portable = getattr(args, "portable", False)
    config_dir = getattr(args, "config_dir", None)
    if portable:
        portable_dir = Path(sys.executable).resolve().parent if hasattr(sys, "_MEIPASS") else _repo_root
        set_runtime_paths(config_dir=portable_dir, data_dir=portable_dir)
    elif config_dir:
        custom = Path(config_dir).expanduser().resolve()
        set_runtime_paths(config_dir=custom, data_dir=custom)


def _setup_logging(args: argparse.Namespace) -> None:
    import logging as _logging

    from src.utils.logger import setup_logger
    from src.utils.path_helper import get_log_dir

    verbose = getattr(args, "verbose", False)
    level = _logging.DEBUG if verbose else _logging.INFO
    logger = setup_logger(get_log_dir(), level=level)
    if not verbose:
        for handler in logger.handlers[:]:
            if isinstance(handler, _logging.StreamHandler) and handler.stream is sys.stdout:
                logger.removeHandler(handler)


# ══════════════════════════════════════════════════════════════════════════════
# -S / --status   (and  hsync db stats)
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_status(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase

    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _hint("Run  hsync -s  to create and populate the database.")
        return 1

    try:
        db = LocalDatabase(db_path)
        stats = db.get_db_stats()
    except Exception as exc:
        _err(f"Could not read database: {exc}")
        return 1

    use_json = getattr(args, "json", False)
    quiet = getattr(args, "quiet", False)

    if use_json:
        last_sync_ts = getattr(config, "last_sync_ts", 0)
        last_backup_ts = getattr(config, "last_backup_ts", 0)
        out = {
            "db_path": str(db_path),
            "file_size_bytes": stats.file_size_bytes,
            "page_count": stats.page_count,
            "free_page_count": stats.free_page_count,
            "page_size": stats.page_size,
            "wasted_bytes": stats.wasted_bytes,
            "wasted_pct": round(stats.wasted_pct, 2),
            "record_count": stats.record_count,
            "domain_count": stats.domain_count,
            "fts_size_bytes": stats.fts_size_bytes,
            "last_sync_ts": last_sync_ts,
            "last_backup_ts": last_backup_ts,
        }
        print(json.dumps(out, indent=2))
        return 0

    if quiet:
        print(f"records={stats.record_count} domains={stats.domain_count} size_kb={stats.file_size_bytes // 1024}")
        return 0

    _section("Database Status")

    size_mb = stats.file_size_bytes / (1024 * 1024)
    fts_mb = stats.fts_size_bytes / (1024 * 1024)
    wasted = stats.wasted_pct

    size_str = f"{size_mb:.1f} MB"
    if wasted > 10:
        size_str += f"  {_yellow(f'({wasted:.0f}% fragmented)')}"

    _kv("Path", str(db_path))
    _kv("Size", size_str)

    if wasted > 10:
        _hint("Run  hsync db vacuum  to reclaim fragmented space.")

    _kv("Records", _bold(f"{stats.record_count:,}"))
    _kv("Domains", f"{stats.domain_count:,}")
    _kv("FTS index", f"{fts_mb:.1f} MB")

    try:
        browser_types = db.get_browser_types()
        if browser_types:
            _kv("Browsers", ", ".join(browser_types))
    except Exception:
        pass

    import datetime as _dt

    def _fmt_ts(ts: int) -> str:
        if not ts:
            return _dim("never")
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    _kv("Last sync", _fmt_ts(getattr(config, "last_sync_ts", 0)))
    _kv("Last backup", _fmt_ts(getattr(config, "last_backup_ts", 0)))

    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# -s / --sync
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_sync(config, args: argparse.Namespace) -> int:
    from src.services.extractor_manager import ExtractorManager
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.sync")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    db_path = config.get_db_path()

    if not quiet:
        _section("Sync")
        _kv("Database", str(db_path))

    db = LocalDatabase(db_path)
    disabled = list(config.extractor.disabled_browsers)
    blacklist = list(config.privacy.blacklisted_domains)
    manager = ExtractorManager(db=db, disabled_browsers=disabled, blacklisted_domains=blacklist)

    for browser_type, path_str in config.extractor.custom_paths.items():
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists():
            _warn(f"Custom path for '{browser_type}' not found, skipping: {p}")
            log.warning("Custom path missing: %s → %s", browser_type, p)
            continue
        try:
            manager.register_custom_path(browser_type, browser_type, p)
        except Exception as exc:
            _warn(f"Could not register custom browser '{browser_type}': {exc}")

    all_registered = manager.get_all_registered()
    available = manager.get_available_browsers()

    if not available:
        _warn("No browser installations found on this system.")
        return 0

    browsers_arg = getattr(args, "browsers", None)
    if browsers_arg:
        requested = [b.strip() for b in browsers_arg.split(",") if b.strip()]
        unknown = [b for b in requested if b not in all_registered]
        targets = [b for b in requested if b in all_registered]
        for b in unknown:
            _warn(f"Browser '{b}' is not registered; skipping. Known: {', '.join(sorted(all_registered))}")
        if not targets:
            _err("None of the requested browsers are registered.")
            return 1
        unavailable = [b for b in targets if b not in available]
        for b in unavailable:
            _warn(f"Browser '{b}' is registered but not installed; skipping.")
        targets = [b for b in targets if b in available]
        if not targets:
            _err("None of the requested browsers are available on this system.")
            return 1
    else:
        targets = available

    if not quiet:
        _kv("Browsers", ", ".join(targets))

    if dry_run:
        _info(_dim("Dry-run mode — no data will be written."))
        return 0

    log.info("Starting sync for browsers: %s", targets)
    start_times: dict[str, float] = {}

    def _progress(browser_type: str, status: str, count: int) -> None:
        if quiet:
            return
        if status == "extracting":
            start_times[browser_type] = time.monotonic()
            print(f"  {_cyan('→')}  {browser_type}: extracting …", flush=True)
        elif status == "saving":
            elapsed = time.monotonic() - start_times.get(browser_type, time.monotonic())
            print(
                f"  {_cyan('→')}  {browser_type}: saving {_bold(f'{count:,}')} records  {_dim(f'({elapsed:.1f}s)')}",
                flush=True,
            )
        elif status == "done":
            elapsed = time.monotonic() - start_times.get(browser_type, time.monotonic())
            label = f"{_bold(f'{count:,}')} new" if count else _dim("no new records")
            print(f"  {_green('✔')}  {browser_type}: {label}  {_dim(f'({elapsed:.1f}s)')}", flush=True)
        elif status == "error":
            print(f"  {_red('✖')}  {browser_type}: extraction failed", file=sys.stderr, flush=True)

    t0 = time.monotonic()
    results = manager.run_extraction(browser_types=targets, progress_callback=_progress)
    elapsed = time.monotonic() - t0

    total_new = sum(results.values())
    log.info("Sync complete: %d new records in %.1fs", total_new, elapsed)

    if not quiet:
        print()
        _ok(
            f"Sync complete — {_bold(f'{total_new:,}')} new records  "
            f"{_dim(f'across {len(results)} browser(s) in {elapsed:.1f}s')}"
        )

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# -b / --backup
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_backup(config, args: argparse.Namespace) -> int:
    from src.services.webdav_sync import WebDavSyncService
    from src.utils.logger import get_logger

    log = get_logger("cli.backup")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)

    if not quiet:
        _section("WebDAV Backup")

    if not config.webdav.enabled:
        _err("WebDAV is not enabled in config.")
        _hint("Run  hsync config set webdav.enabled true  and configure the URL.")
        return 1

    if not config.webdav.url.strip():
        _err("WebDAV URL is empty.")
        _hint("Run  hsync config set webdav.url https://your-server/dav/")
        return 1

    if not quiet:
        _kv("Server", config.webdav.url)
        _kv("User", config.webdav.username)
        _kv("Path", config.webdav.remote_path)

    if dry_run:
        _info(_dim("Dry-run mode — nothing will be uploaded."))
        return 0

    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _hint("Run  hsync -s  first to create the database.")
        return 1

    service = WebDavSyncService(config.webdav, db_path)

    favicon_cache_dir: Path | None = None
    favicon_db_path = config.get_favicon_db_path()
    if favicon_db_path.exists():
        favicon_cache_dir = favicon_db_path.parent

    def _progress(msg: str) -> None:
        if not quiet:
            _info(msg)
        log.info("Backup: %s", msg)

    log.info("Starting WebDAV backup to %s", config.webdav.url)
    t0 = time.monotonic()
    result = service.sync(progress_callback=_progress, favicon_cache_dir=favicon_cache_dir)
    elapsed = time.monotonic() - t0

    if result.success:
        log.info("Backup succeeded in %.1fs", elapsed)
        if not quiet:
            _ok(f"Backup complete  {_dim(f'({elapsed:.1f}s)')}")
        return 0

    log.error("Backup failed: %s", result.message)
    _err(f"Backup failed: {result.message}")
    return 1


# ══════════════════════════════════════════════════════════════════════════════
# -e / --export
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_export(config, args: argparse.Namespace) -> int:
    from datetime import datetime

    from src.services.exporter import ALL_COLUMNS, Exporter, ResolvedExportParams
    from src.services.favicon_cache import FaviconCache
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.export")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)

    output_path = Path(args.export).expanduser().resolve()

    fmt_arg = getattr(args, "format", None)
    fmt = (
        fmt_arg.lower()
        if fmt_arg
        else {".json": "json", ".html": "html", ".htm": "html"}.get(output_path.suffix.lower(), "csv")
    )

    cols_arg = getattr(args, "columns", None)
    columns: list[str] = []
    if cols_arg:
        requested = [c.strip() for c in cols_arg.split(",") if c.strip()]
        invalid = [c for c in requested if c not in ALL_COLUMNS]
        if invalid:
            _err(f"Unknown column(s): {', '.join(invalid)}")
            _hint(f"Available: {', '.join(ALL_COLUMNS)}")
            return 1
        columns = [c for c in ALL_COLUMNS if c in requested]

    def _parse_date_start(s: str) -> int:
        try:
            return int(datetime.strptime(s.strip(), "%Y-%m-%d").replace(hour=0, minute=0, second=0).timestamp())
        except ValueError:
            _err(f"Invalid date '{s}'. Expected format: YYYY-MM-DD")
            sys.exit(1)

    def _parse_date_end(s: str) -> int:
        try:
            return int(datetime.strptime(s.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp())
        except ValueError:
            _err(f"Invalid date '{s}'. Expected format: YYYY-MM-DD")
            sys.exit(1)

    after_arg = getattr(args, "after", None)
    before_arg = getattr(args, "before", None)
    date_from = _parse_date_start(after_arg) if after_arg else None
    date_to = _parse_date_end(before_arg) if before_arg else None

    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _hint("Run  hsync -s  first to populate the database.")
        return 1

    db = LocalDatabase(db_path)

    domain_arg = getattr(args, "domain", None)
    domain_ids: list[int] | None = None
    if domain_arg:
        ids: list[int] = []
        with db._conn(write=False) as conn:
            for d in domain_arg:
                ids.extend(LocalDatabase._domain_ids_for(conn, d))
        domain_ids = list(set(ids)) if ids else None
        if domain_arg and domain_ids is None and not quiet:
            _warn(f"No records found for domain(s): {', '.join(domain_arg)}")

    embed_icons_arg = getattr(args, "embed_icons", False)
    favicon_cache: FaviconCache | None = None
    if fmt == "html" and embed_icons_arg:
        favicon_db_path = config.get_favicon_db_path()
        if favicon_db_path.exists():
            favicon_cache = FaviconCache(favicon_db_path)
        elif not quiet:
            _warn("Favicon database not found; --embed-icons will be skipped.")

    keyword_arg = getattr(args, "keyword", None)
    browser_arg = getattr(args, "browser", None)
    regex_arg = getattr(args, "regex", False)

    if not quiet:
        _section("Export")
        _kv("Output", str(output_path))
        _kv("Format", fmt.upper())
        if columns:
            _kv("Columns", ", ".join(columns))
        if keyword_arg:
            _kv("Filter", f"keyword={keyword_arg!r}" + ("  [regex]" if regex_arg else ""))
        if date_from or date_to:
            _kv("Filter", f"date  {after_arg or '*'} → {before_arg or '*'}")
        if browser_arg:
            _kv("Filter", f"browser={browser_arg}")
        if domain_arg:
            _kv("Filter", f"domains={', '.join(domain_arg)}")

    if dry_run:
        _info(_dim("Dry-run mode — no file will be written."))
        return 0

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _err(f"Cannot create output directory '{output_path.parent}': {exc}")
        return 1

    params = ResolvedExportParams(
        output_path=output_path,
        fmt=fmt,
        columns=columns,
        embed_icons=bool(embed_icons_arg),
        keyword=keyword_arg or "",
        browser_type=browser_arg or "",
        date_from=date_from,
        date_to=date_to,
        domain_ids=domain_ids,
        use_regex=bool(regex_arg),
    )

    exporter = Exporter(db, favicon_cache)
    t0 = time.monotonic()
    bar = _ProgressBar(total=0, quiet=quiet)

    def _progress(current: int, total: int) -> None:
        bar.total = total
        bar.update(current)

    log.info("Exporting to %s (fmt=%s)", output_path, fmt)
    try:
        exporter.export(params, progress_callback=_progress)
    except Exception as exc:
        bar.done()
        _err(f"Export failed: {exc}")
        log.exception("Export failed")
        return 1

    bar.done()
    elapsed = time.monotonic() - t0
    size_kb = output_path.stat().st_size / 1024 if output_path.exists() else 0

    log.info("Export complete: %.0f KB in %.1fs", size_kb, elapsed)
    if not quiet:
        _ok(f"Exported → {_bold(str(output_path))}  {_dim(f'({size_kb:.0f} KB  ·  {elapsed:.1f}s)')}")

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# hsync db  subcommands
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_db_vacuum(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.db.vacuum")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    db_path = config.get_db_path()

    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        return 1

    if not quiet:
        _section("Database Vacuum")
        _kv("Database", str(db_path))

    if dry_run:
        _info(_dim("Dry-run mode — nothing will be changed."))
        return 0

    db = LocalDatabase(db_path)
    stats_before = db.get_db_stats()

    def _progress(msg: str) -> None:
        if not quiet:
            _info(msg)
        log.info("vacuum: %s", msg)

    t0 = time.monotonic()
    try:
        db.vacuum_and_analyze(progress_callback=_progress)
    except Exception as exc:
        _err(f"Vacuum failed: {exc}")
        log.exception("Vacuum failed")
        return 1

    elapsed = time.monotonic() - t0
    stats_after = db.get_db_stats()
    saved_kb = (stats_before.file_size_bytes - stats_after.file_size_bytes) / 1024

    log.info("Vacuum complete in %.1fs, saved %.0f KB", elapsed, saved_kb)
    if not quiet:
        saved_str = f"  {_green(f'(saved {saved_kb:.0f} KB)')}" if saved_kb > 0 else f"  {_dim('(nothing to reclaim)')}"
        _ok(f"Vacuum complete  {_dim(f'({elapsed:.1f}s)')}{saved_str}")

    return 0


def _cmd_db_rebuild_fts(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.db.rebuild_fts")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    db_path = config.get_db_path()

    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        return 1

    if not quiet:
        _section("Rebuild FTS Index")
        _kv("Database", str(db_path))

    if dry_run:
        _info(_dim("Dry-run mode — nothing will be changed."))
        return 0

    db = LocalDatabase(db_path)

    def _progress(msg: str) -> None:
        if not quiet:
            _info(msg)
        log.info("rebuild-fts: %s", msg)

    t0 = time.monotonic()
    try:
        db.rebuild_fts_index(progress_callback=_progress)
    except Exception as exc:
        _err(f"FTS rebuild failed: {exc}")
        log.exception("FTS rebuild failed")
        return 1

    elapsed = time.monotonic() - t0
    log.info("FTS rebuild complete in %.1fs", elapsed)
    if not quiet:
        _ok(f"Full-text search index rebuilt  {_dim(f'({elapsed:.1f}s)')}")
    return 0


def _cmd_db_normalize(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.db.normalize")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    db_path = config.get_db_path()

    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        return 1

    if not quiet:
        _section("Normalise Domains")
        _kv("Database", str(db_path))

    if dry_run:
        _info(_dim("Dry-run mode — nothing will be changed."))
        return 0

    db = LocalDatabase(db_path)

    def _progress(msg: str) -> None:
        if not quiet:
            _info(msg)
        log.info("normalize: %s", msg)

    t0 = time.monotonic()
    try:
        db.normalize_domains(progress_callback=_progress)
    except Exception as exc:
        _err(f"Normalise failed: {exc}")
        log.exception("Normalise failed")
        return 1

    elapsed = time.monotonic() - t0
    log.info("Domain normalisation complete in %.1fs", elapsed)
    if not quiet:
        _ok(f"Domain names normalised  {_dim(f'({elapsed:.1f}s)')}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# hsync search  subcommand
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_search(config, args: argparse.Namespace) -> int:
    from datetime import datetime

    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger
    from src.utils.search_parser import parse_query

    log = get_logger("cli.search")
    quiet = getattr(args, "quiet", False)
    query_str = getattr(args, "query", "")
    limit = getattr(args, "limit", 20)
    fmt = getattr(args, "format", "table")
    open_first = getattr(args, "open", False)
    columns_arg = getattr(args, "columns", None)
    interactive = getattr(args, "interactive", False)

    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _hint("Run  hsync -s  first to populate the database.")
        return 1

    db = LocalDatabase(db_path)

    # Interactive mode
    if interactive:
        return _cmd_search_interactive(db, query_str, limit, quiet, log)

    # If no query provided, show recent records
    if not query_str:
        if not quiet:
            _section(f"Recent History (latest {limit} records)")
        query = parse_query("")
    else:
        query = parse_query(query_str)
    log.info("Search query: %s", query_str)

    db = LocalDatabase(db_path)

    # Resolve date range
    date_from = int(datetime.combine(query.after, datetime.min.time()).timestamp()) if query.after else None
    date_to = int(datetime.combine(query.before, datetime.max.time()).timestamp()) if query.before else None

    # Resolve domain IDs
    domain_ids: list[int] | None = None
    if query.domains:
        ids: list[int] = []
        with db._conn(write=False) as conn:
            for d in query.domains:
                ids.extend(LocalDatabase._domain_ids_for(conn, d))
        domain_ids = list(set(ids)) if ids else None
        if not domain_ids and not quiet:
            _warn(f"No records found for domain(s): {', '.join(query.domains)}")
            return 0

    # Resolve device IDs
    device_ids: list[int] | None = None
    if query.device:
        device_ids = db.resolve_device_ids(query.device)
        if not device_ids and not quiet:
            _warn(f"No device found matching: {query.device}")
            return 0

    try:
        records = db.get_records(
            keyword=query.keyword,
            browser_type=query.browser,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=0,
            domain_ids=domain_ids,
            excludes=query.excludes,
            title_only=query.title_only,
            url_only=query.url_only,
            use_regex=query.use_regex,
            bookmarked_only=query.bookmarked_only,
            has_annotation=query.has_annotation,
            bookmark_tag=query.bookmark_tag,
            device_ids=device_ids,
        )
    except Exception as exc:
        _err(f"Search failed: {exc}")
        log.exception("Search failed")
        return 1

    if not records:
        if not quiet:
            _info("No results found.")
        return 0

    log.info("Found %d results", len(records))

    # Open first result if requested
    if open_first and records:
        import webbrowser

        url = records[0].url
        try:
            webbrowser.open(url)
            if not quiet:
                _ok(f"Opened in browser: {url}")
        except Exception as exc:
            _warn(f"Could not open URL: {exc}")

    # Output results
    if fmt == "json":
        import json

        output = [
            {
                "id": r.id,
                "title": r.title,
                "url": r.url,
                "visit_time": r.visit_time,
                "visit_count": r.visit_count,
                "browser_type": r.browser_type,
                "profile_name": r.profile_name,
                "domain": r.domain,
            }
            for r in records
        ]
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    # Determine columns
    default_cols = ["title", "url", "visit_time", "browser_type"]
    cols = [c.strip() for c in columns_arg.split(",") if c.strip()] if columns_arg else default_cols

    if fmt == "tsv":
        print("\t".join(cols))
        for r in records:
            row = []
            for col in cols:
                val = getattr(r, col, "")
                if col == "visit_time" and isinstance(val, int):
                    val = datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M:%S")
                row.append(str(val))
            print("\t".join(row))
        return 0

    if fmt == "csv":
        import csv
        import sys

        writer = csv.writer(sys.stdout)
        writer.writerow(cols)
        for r in records:
            row = []
            for col in cols:
                val = getattr(r, col, "")
                if col == "visit_time" and isinstance(val, int):
                    val = datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M:%S")
                row.append(str(val))
            writer.writerow(row)
        return 0

    # Table format (default)
    if not quiet:
        _section(f"Search Results ({len(records)} found)")

    term_width = shutil.get_terminal_size((80, 24)).columns
    title_width = max(20, min(50, term_width - 60))
    url_width = max(30, term_width - title_width - 30)

    for i, r in enumerate(records, 1):
        title = r.title[:title_width] if len(r.title) > title_width else r.title
        url = r.url[:url_width] if len(r.url) > url_width else r.url
        ts = datetime.fromtimestamp(r.visit_time).strftime("%Y-%m-%d %H:%M")

        print(f"\n  {_bold(_cyan(f'[{i}]'))}  {_bold(title)}")
        print(f"      {_dim('URL:')} {url}")
        print(f"      {_dim('Time:')} {ts}  {_dim('Browser:')} {r.browser_type}  {_dim('Visits:')} {r.visit_count}")

    print()
    return 0


def _cmd_search_interactive(db, initial_query: str, limit: int, quiet: bool, log) -> int:
    """Interactive search mode with prompt-based refinement."""
    from datetime import datetime

    from src.models.history_record import HistoryRecord
    from src.services.local_db import LocalDatabase
    from src.utils.search_parser import parse_query

    current_query = initial_query
    current_page = 0

    def _fetch_results(query_str: str, page: int) -> list[HistoryRecord]:
        query = parse_query(query_str)
        date_from = int(datetime.combine(query.after, datetime.min.time()).timestamp()) if query.after else None
        date_to = int(datetime.combine(query.before, datetime.max.time()).timestamp()) if query.before else None

        domain_ids: list[int] | None = None
        if query.domains:
            ids: list[int] = []
            with db._conn(write=False) as conn:
                for d in query.domains:
                    ids.extend(LocalDatabase._domain_ids_for(conn, d))
            domain_ids = list(set(ids)) if ids else None

        device_ids: list[int] | None = None
        if query.device:
            device_ids = db.resolve_device_ids(query.device)

        try:
            return db.get_records(
                keyword=query.keyword,
                browser_type=query.browser,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=page * limit,
                domain_ids=domain_ids,
                excludes=query.excludes,
                title_only=query.title_only,
                url_only=query.url_only,
                use_regex=query.use_regex,
                bookmarked_only=query.bookmarked_only,
                has_annotation=query.has_annotation,
                bookmark_tag=query.bookmark_tag,
                device_ids=device_ids,
            )
        except Exception:
            log.exception("Search failed in interactive mode")
            return []

    def _display_results(records: list[HistoryRecord], query: str, page: int) -> None:
        print("\n" + _bold(_cyan("═" * 80)))
        print(_bold("  Interactive Search Mode"))
        print(_bold(_cyan("═" * 80)))
        print(f"  Query: {_yellow(query or '(browse mode)')}")
        print(f"  Results: {_bold(str(len(records)))}  |  Page: {page + 1}  |  Limit: {limit}")
        print(_dim("  Commands: [n]ext page  [p]rev page  [/]new search  [o]pen URL  [q]uit"))
        print(_bold(_cyan("─" * 80)))

        if not records:
            print("\n  " + _dim("No results found."))
            print()
            return

        term_width = shutil.get_terminal_size((80, 24)).columns
        title_width = max(20, min(50, term_width - 60))
        url_width = max(30, term_width - title_width - 30)

        for i, r in enumerate(records, 1):
            title = r.title[:title_width] if len(r.title) > title_width else r.title
            url = r.url[:url_width] if len(r.url) > url_width else r.url
            ts = datetime.fromtimestamp(r.visit_time).strftime("%Y-%m-%d %H:%M")

            print(f"\n  {_bold(_cyan(f'[{i}]'))}  {_bold(title)}")
            print(f"      {_dim('URL:')} {url}")
            print(f"      {_dim('Time:')} {ts}  {_dim('Browser:')} {r.browser_type}  {_dim('Visits:')} {r.visit_count}")

        print("\n" + _bold(_cyan("─" * 80)))

    if not quiet:
        _section("Interactive Search")
        print(_dim("  Tip: Use structured queries like 'domain:github.com python' or 'after:2024-01-01'"))
        print()

    records = _fetch_results(current_query, current_page)
    _display_results(records, current_query, current_page)

    try:
        while True:
            try:
                cmd = input(f"\n  {_bold('Command:')} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if not cmd:
                continue

            if cmd in ("q", "quit", "exit"):
                return 0

            if cmd in ("n", "next"):
                current_page += 1
                records = _fetch_results(current_query, current_page)
                if not records:
                    _warn("No more results.")
                    current_page -= 1
                else:
                    _display_results(records, current_query, current_page)

            elif cmd in ("p", "prev", "previous"):
                if current_page > 0:
                    current_page -= 1
                    records = _fetch_results(current_query, current_page)
                    _display_results(records, current_query, current_page)
                else:
                    _warn("Already at first page.")

            elif cmd.startswith("/"):
                new_query = cmd[1:].strip()
                current_query = new_query
                current_page = 0
                records = _fetch_results(current_query, current_page)
                _display_results(records, current_query, current_page)

            elif cmd.startswith("o"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(records):
                        import webbrowser

                        url = records[idx].url
                        _ok(f"Opening: {url}")
                        try:
                            webbrowser.open(url)
                        except Exception as exc:
                            _warn(f"Could not open URL: {exc}")
                    else:
                        _warn(f"Invalid index. Choose 1-{len(records)}")
                else:
                    _warn("Usage: o <number>  (e.g., 'o 1' to open first result)")

            elif cmd in {"h", "help"}:
                print()
                print(_bold("  Available Commands:"))
                print(f"    {_cyan('n, next')}       - Next page")
                print(f"    {_cyan('p, prev')}       - Previous page")
                print(f"    {_cyan('/query')}        - New search (e.g., '/python domain:github.com')")
                print(f"    {_cyan('o <num>')}       - Open URL by number (e.g., 'o 1')")
                print(f"    {_cyan('h, help')}       - Show this help")
                print(f"    {_cyan('q, quit')}       - Exit interactive mode")
                print()

            else:
                _warn(f"Unknown command: {cmd}")
                _hint("Type 'h' for help")

    except KeyboardInterrupt:
        print()
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# hsync restore  subcommand
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_restore(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase
    from src.services.webdav_sync import WebDavSyncService
    from src.utils.logger import get_logger

    log = get_logger("cli.restore")
    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    list_only = getattr(args, "list", False)
    latest = getattr(args, "latest", False)
    replace_mode = getattr(args, "replace", False)
    restore_favicons = getattr(args, "restore_favicons", False)

    if not config.webdav.enabled:
        _err("WebDAV is not enabled in config.")
        _hint("Run  hsync config set webdav.enabled true  and configure the URL.")
        return 1

    if not config.webdav.url.strip():
        _err("WebDAV URL is empty.")
        _hint("Run  hsync config set webdav.url https://your-server/dav/")
        return 1

    db_path = config.get_db_path()
    service = WebDavSyncService(config.webdav, db_path)

    # List backups
    if not quiet:
        _section("WebDAV Restore")
        _kv("Server", config.webdav.url)
        _kv("User", config.webdav.username)
        _kv("Path", config.webdav.remote_path)
        print()

    try:
        backups = service.list_backups()
    except Exception as exc:
        _err(f"Failed to list backups: {exc}")
        log.exception("Failed to list backups")
        return 1

    if not backups:
        _warn("No backups found on server.")
        return 0

    # List mode
    if list_only:
        import json

        print(json.dumps(backups, indent=2))
        return 0

    # Display available backups
    if not quiet:
        _info(f"Found {_bold(str(len(backups)))} backup(s):")
        print()
        for i, backup in enumerate(backups, 1):
            import datetime

            ts = backup.get("timestamp", 0)
            size_mb = backup.get("size_bytes", 0) / (1024 * 1024)
            date_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"
            print(f"  {_bold(_cyan(f'[{i}]'))}  {backup.get('filename', 'unknown')}")
            print(f"      {_dim('Date:')} {date_str}  {_dim('Size:')} {size_mb:.1f} MB")

        print()

    # Auto-select latest
    if latest:
        selected_backup = backups[0]
        if not quiet:
            _info(f"Auto-selecting latest backup: {selected_backup.get('filename', 'unknown')}")
    else:
        # Interactive selection
        if dry_run:
            _info(_dim("Dry-run mode — no restore will be performed."))
            return 0

        try:
            choice = input(
                f"  {_bold('Select backup to restore [1-' + str(len(backups)) + ', or q to quit]:')} "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice.lower() in ("q", "quit", "exit"):
            return 0

        if not choice.isdigit() or not (1 <= int(choice) <= len(backups)):
            _err(f"Invalid choice: {choice}")
            return 1

        selected_backup = backups[int(choice) - 1]

    # Confirm action
    if not latest and not quiet:
        if replace_mode:
            _warn("This will REPLACE your local database completely!")
        else:
            _info("This will merge backup records with your local database.")
        try:
            confirm = input(f"  {_bold('Continue? [y/N]:')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if confirm not in ("y", "yes"):
            _info("Restore cancelled.")
            return 0

    if dry_run:
        _info(_dim("Dry-run mode — no restore will be performed."))
        return 0

    # Perform restore
    favicon_cache_dir: Path | None = None
    if restore_favicons:
        favicon_db_path = config.get_favicon_db_path()
        if favicon_db_path.exists():
            favicon_cache_dir = favicon_db_path.parent

    def _progress(msg: str) -> None:
        if not quiet:
            _info(msg)
        log.info("Restore: %s", msg)

    log.info("Starting WebDAV restore from %s", selected_backup.get("filename", "unknown"))
    t0 = time.monotonic()

    if not replace_mode:
        # Merge mode (default): download and merge records
        _progress("Downloading backup for merge...")

        try:
            result = service.restore(progress_callback=_progress, restore_favicons=False, favicon_cache_dir=None)
            if not result.success:
                _err(f"Restore failed: {result.message}")
                return 1

            # Merge downloaded DB with local DB
            downloaded_db = result.downloaded_path
            if not downloaded_db or not downloaded_db.exists():
                _err("Downloaded database file not found.")
                return 1

            _progress("Merging records into local database...")
            db = LocalDatabase(db_path)
            try:
                db.merge_from_db(downloaded_db)
                _progress("Merge complete.")
            except Exception as exc:
                _err(f"Merge failed: {exc}")
                log.exception("Merge failed")
                return 1
            finally:
                # Clean up temp file
                try:
                    downloaded_db.unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception as exc:
            _err(f"Restore failed: {exc}")
            log.exception("Restore failed")
            return 1
    else:
        # Replace mode: overwrite local database
        _progress("Downloading backup to replace local database...")
        try:
            result = service.restore(
                progress_callback=_progress,
                restore_favicons=restore_favicons,
                favicon_cache_dir=favicon_cache_dir,
            )
        except Exception as exc:
            _err(f"Restore failed: {exc}")
            log.exception("Restore failed")
            return 1

        if not result.success:
            _err(f"Restore failed: {result.message}")
            return 1

        # Move downloaded DB to replace local DB
        downloaded_db = result.downloaded_path
        if downloaded_db and downloaded_db.exists():
            try:
                import shutil

                shutil.move(str(downloaded_db), str(db_path))
                _progress("Database replaced successfully.")
            except Exception as exc:
                _err(f"Failed to replace database: {exc}")
                return 1

    elapsed = time.monotonic() - t0

    log.info("Restore succeeded in %.1fs", elapsed)
    if not quiet:
        _ok(f"Restore complete  {_dim(f'({elapsed:.1f}s)')}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# hsync config  subcommands
# ══════════════════════════════════════════════════════════════════════════════

_CONFIG_KEYS: dict[str, tuple[str | None, str, type]] = {
    "webdav.enabled": ("webdav", "enabled", bool),
    "webdav.url": ("webdav", "url", str),
    "webdav.username": ("webdav", "username", str),
    "webdav.remote_path": ("webdav", "remote_path", str),
    "webdav.max_backups": ("webdav", "max_backups", int),
    "webdav.verify_ssl": ("webdav", "verify_ssl", bool),
    "webdav.auto_backup": ("webdav", "auto_backup", bool),
    "webdav.backup_favicons": ("webdav", "backup_favicons", bool),
    "scheduler.auto_sync_enabled": ("scheduler", "auto_sync_enabled", bool),
    "scheduler.sync_interval_hours": ("scheduler", "sync_interval_hours", int),
    "scheduler.auto_backup_enabled": ("scheduler", "auto_backup_enabled", bool),
    "scheduler.auto_backup_interval_hours": ("scheduler", "auto_backup_interval_hours", int),
    "scheduler.launch_on_startup": ("scheduler", "launch_on_startup", bool),
    "theme": (None, "theme", str),
    "language": (None, "language", str),
}


def _config_get_value(config, key: str):
    if key not in _CONFIG_KEYS:
        return None, False
    section_attr, field_attr, _ = _CONFIG_KEYS[key]
    obj = getattr(config, section_attr) if section_attr else config
    return getattr(obj, field_attr, None), True


def _config_set_value(config, key: str, raw_value: str) -> tuple[bool, str]:
    if key not in _CONFIG_KEYS:
        return False, f"Unknown config key: {key!r}. Run  hsync config list  to see valid keys."
    section_attr, field_attr, expected_type = _CONFIG_KEYS[key]
    obj = getattr(config, section_attr) if section_attr else config
    try:
        if expected_type is bool:
            if raw_value.lower() in ("true", "1", "yes", "on"):
                coerced: object = True
            elif raw_value.lower() in ("false", "0", "no", "off"):
                coerced = False
            else:
                return False, f"Expected true/false for {key!r}, got {raw_value!r}"
        elif expected_type is int:
            coerced = int(raw_value)
        else:
            coerced = raw_value
    except (ValueError, TypeError) as exc:
        return False, f"Type error for {key!r}: {exc}"
    setattr(obj, field_attr, coerced)
    return True, ""


def _cmd_config_list(config, args: argparse.Namespace) -> int:
    quiet = getattr(args, "quiet", False)
    if not quiet:
        _section("Configuration")

    current_section: str | None = "__none__"
    for key, (section_attr, field_attr, _) in _CONFIG_KEYS.items():
        section_label = section_attr or "general"
        if not quiet and section_label != current_section:
            current_section = section_label
            print(f"\n  {_bold(_cyan(section_label))}")
        value, _ = _config_get_value(config, key)
        if quiet:
            print(f"{key}={value}")
        else:
            val_str = (
                _green(str(value))
                if isinstance(value, bool) and value
                else _red(str(value))
                if isinstance(value, bool)
                else _dim("(empty)")
                if value == ""
                else str(value)
            )
            print(f"    {_dim(field_attr.ljust(34))} {val_str}")

    print()
    return 0


def _cmd_config_get(config, args: argparse.Namespace) -> int:
    key = args.key
    value, found = _config_get_value(config, key)
    if not found:
        _err(f"Unknown config key: {key!r}")
        _hint("Run  hsync config list  to see all valid keys.")
        return 1
    print(value)
    return 0


def _cmd_config_set(config, args: argparse.Namespace) -> int:
    from src.utils.logger import get_logger

    log = get_logger("cli.config.set")

    key = args.key
    raw_value = args.value
    quiet = getattr(args, "quiet", False)

    success, error = _config_set_value(config, key, raw_value)
    if not success:
        _err(error)
        return 1

    value, _ = _config_get_value(config, key)
    try:
        config.save()
    except Exception as exc:
        _err(f"Could not save config: {exc}")
        log.exception("Config save failed")
        return 1

    log.info("config set %s = %r", key, value)
    if not quiet:
        _ok(f"Set {_bold(key)} = {_cyan(str(value))}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Interactive mode
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_interactive(config, parser: argparse.ArgumentParser) -> int:
    _section("HistorySync — Interactive Menu")
    print()

    MENU = [
        ("s", "Sync browser history", ["-s"]),
        ("b", "Backup database to WebDAV", ["-b"]),
        ("sb", "Sync then backup", ["-s", "-b"]),
        ("S", "Show database statistics", ["-S"]),
        ("Sj", "Show statistics (JSON output)", ["-S", "--json"]),
        ("V", "Vacuum database", ["db", "vacuum"]),
        ("f", "Rebuild full-text search index", ["db", "rebuild-fts"]),
        ("n", "Normalise domain names", ["db", "normalize"]),
        ("c", "List configuration", ["config", "list"]),
        ("q", "Quit", None),
    ]

    for key, label, _ in MENU:
        print(f"   {_bold(_cyan(f'[{key}]')):<20}  {label}")

    print()
    try:
        choice = input("  Choose: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    mapping = {k: (label, argv) for k, label, argv in MENU}

    if choice not in mapping:
        _warn(f"Unknown option: {choice!r}")
        return 1

    label, argv = mapping[choice]
    if argv is None:
        _info("Bye!")
        return 0
    print(f"\n  Running: {_bold('hsync ' + ' '.join(argv))}\n")

    try:
        sub_args = parser.parse_args(argv)
    except SystemExit:
        return 1

    return _dispatch(config, sub_args, parser)


# ══════════════════════════════════════════════════════════════════════════════
# Watch mode
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_watch(config, args: argparse.Namespace) -> int:
    minutes = args.watch
    quiet = getattr(args, "quiet", False)

    if not quiet:
        _section("Watch Mode")
        _info(f"Syncing every {_bold(str(minutes))} minute(s).  Press {_bold('Ctrl-C')} to stop.")

    iteration = 0
    try:
        while True:
            iteration += 1
            if not quiet:
                import datetime

                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"\n  {_dim(f'[{ts}]')} Run #{iteration}")
            rc = _cmd_sync(config, args)
            if rc != 0 and not quiet:
                _warn(f"Sync run #{iteration} exited with code {rc}")
            if not quiet:
                _info(_dim(f"Next run in {minutes} minute(s) …"))
            time.sleep(minutes * 60)
    except KeyboardInterrupt:
        print()
        if not quiet:
            _ok(f"Watch stopped after {iteration} run(s).")
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# Central dispatcher
# ══════════════════════════════════════════════════════════════════════════════


def _dispatch(config, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    subcommand = getattr(args, "subcommand", None)

    if subcommand == "db":
        db_cmd = getattr(args, "db_cmd", None)
        dispatch = {
            "vacuum": _cmd_db_vacuum,
            "rebuild-fts": _cmd_db_rebuild_fts,
            "normalize": _cmd_db_normalize,
            "stats": _cmd_status,
        }
        if db_cmd in dispatch:
            return dispatch[db_cmd](config, args)
        _err(f"Unknown db command: {db_cmd}")
        return 2

    if subcommand == "search":
        return _cmd_search(config, args)

    if subcommand == "restore":
        return _cmd_restore(config, args)

    if subcommand == "config":
        cfg_cmd = getattr(args, "cfg_cmd", None)
        dispatch = {"list": _cmd_config_list, "get": _cmd_config_get, "set": _cmd_config_set}
        if cfg_cmd in dispatch:
            return dispatch[cfg_cmd](config, args)
        _err(f"Unknown config command: {cfg_cmd}")
        return 2

    if getattr(args, "interactive", False):
        return _cmd_interactive(config, parser)

    has_action = any(
        [
            getattr(args, "sync", False),
            getattr(args, "backup", False),
            getattr(args, "export", None),
            getattr(args, "status", False),
        ]
    )
    if not has_action:
        parser.print_help()
        return 0

    if getattr(args, "status", False):
        return _cmd_status(config, args)

    if getattr(args, "watch", None) and getattr(args, "sync", False):
        return _cmd_watch(config, args)

    exit_code = 0
    if getattr(args, "sync", False):
        rc = _cmd_sync(config, args)
        if rc != 0:
            exit_code = rc
    if getattr(args, "backup", False):
        rc = _cmd_backup(config, args)
        if rc != 0:
            exit_code = rc
    if getattr(args, "export", None):
        rc = _cmd_export(config, args)
        if rc != 0:
            exit_code = rc

    return exit_code


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    global _NO_COLOR
    if getattr(args, "no_color", False):
        _NO_COLOR = True

    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)
    if quiet and verbose:
        _err("--quiet and --verbose are mutually exclusive.")
        sys.exit(2)

    subcommand = getattr(args, "subcommand", None)
    interactive = getattr(args, "interactive", False)
    has_classic = any(
        [
            getattr(args, "sync", False),
            getattr(args, "backup", False),
            getattr(args, "export", None),
            getattr(args, "status", False),
        ]
    )
    if not subcommand and not interactive and not has_classic:
        parser.print_help()
        sys.exit(0)

    _setup_paths(args)
    _setup_logging(args)

    from src.models.app_config import AppConfig
    from src.utils.logger import get_logger

    log = get_logger("cli")

    try:
        config = AppConfig.load()
    except Exception as exc:
        _err(f"Failed to load config: {exc}")
        sys.exit(1)

    log.info(
        "hsync starting  subcommand=%s sync=%s backup=%s export=%s status=%s dry_run=%s",
        subcommand,
        getattr(args, "sync", False),
        getattr(args, "backup", False),
        bool(getattr(args, "export", None)),
        getattr(args, "status", False),
        getattr(args, "dry_run", False),
    )

    exit_code = _dispatch(config, args, parser)
    log.info("hsync exiting, code=%d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
