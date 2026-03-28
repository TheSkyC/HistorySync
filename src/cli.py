# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0
"""
hsync — HistorySync headless CLI.

Sync browser history into the local database:
    hsync --sync
    hsync --sync --browsers chrome,firefox

Back up the local database to WebDAV:
    hsync --backup

Sync and back up in one shot:
    hsync --sync --backup

Export history (format inferred from extension):
    hsync --export history.csv
    hsync --export history.json --keyword python --after 2024-01-01
    hsync --export report.html --format html --embed-icons
    hsync --export out.csv --domain github.com --domain google.com

Show database statistics:
    hsync --status

Portable mode (config + DB stored beside the binary):
    hsync --portable --sync

Custom config/data directory:
    hsync --config-dir /mnt/nas/historysync --sync

Scripting / CI:
    hsync --sync --quiet && echo "ok" || echo "failed"
    hsync --sync --no-color 2>&1 | tee sync.log
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

# ── Bootstrap ────────────────────────────────────────────────────────────────
# Make `src.*` importable when run as a script, from the project root,
# or from a PyInstaller bundle (_MEIPASS is set in frozen mode).

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ══════════════════════════════════════════════════════════════════════════════
# Terminal / ANSI helpers
# Inline implementation; zero external dependencies.
# ══════════════════════════════════════════════════════════════════════════════


def _try_enable_windows_vt() -> bool:
    """Enable VT/ANSI processing on Windows cmd.exe / PowerShell (Win10+)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


_VT_OK = _try_enable_windows_vt()
# Disable colour when: not a tty, NO_COLOR env, dumb terminal, or VT failed on Windows
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


def _section(title: str) -> None:
    bar = _dim("─" * (len(title) + 2))
    print(f"\n{_bold(title)}\n{bar}")


# ══════════════════════════════════════════════════════════════════════════════
# Argument parser
# ══════════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    from src.utils.constants import APP_VERSION

    parser = argparse.ArgumentParser(
        prog="hsync",
        description=(f"hsync {APP_VERSION} — HistorySync headless CLI  (no GUI required)"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.strip(),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )

    # ── Actions ───────────────────────────────────────────────
    act = parser.add_argument_group("Actions  (at least one required)")
    act.add_argument(
        "--sync",
        action="store_true",
        help="Extract browser history and import it into the local database",
    )
    act.add_argument(
        "--backup",
        action="store_true",
        help="Upload a zipped snapshot of the local database to WebDAV",
    )
    act.add_argument(
        "--export",
        metavar="FILE",
        help=(
            "Export history to FILE and exit. "
            "Format is inferred from the extension (.csv / .json / .html); "
            "override with --format."
        ),
    )
    act.add_argument(
        "--status",
        action="store_true",
        help="Print database statistics and exit",
    )

    # ── Sync options ──────────────────────────────────────────
    sync_grp = parser.add_argument_group("Sync options")
    sync_grp.add_argument(
        "--browsers",
        metavar="LIST",
        help=(
            "Comma-separated browser types to sync (default: all available). Example: --browsers chrome,firefox,edge"
        ),
    )

    # ── Export options ────────────────────────────────────────
    exp_grp = parser.add_argument_group("Export options")
    exp_grp.add_argument(
        "--format",
        metavar="FMT",
        choices=["csv", "json", "html"],
        help="Export format: csv | json | html  (default: inferred from FILE extension)",
    )
    exp_grp.add_argument(
        "--columns",
        metavar="COLS",
        help=(
            "Comma-separated column list (default: all). "
            "Available: id, title, url, visit_time, visit_count, browser_type, "
            "profile_name, domain, metadata, typed_count, first_visit_time, "
            "transition_type, visit_duration"
        ),
    )
    exp_grp.add_argument(
        "--embed-icons",
        action="store_true",
        help="Embed favicons as Base64 data-URIs in the HTML export",
    )
    exp_grp.add_argument(
        "--keyword",
        metavar="TEXT",
        help="Filter: full-text keyword (use --regex to treat as a regular expression)",
    )
    exp_grp.add_argument(
        "--regex",
        action="store_true",
        help="Treat --keyword as a Python regular expression",
    )
    exp_grp.add_argument(
        "--browser",
        metavar="TYPE",
        help="Filter: browser type (e.g. chrome, firefox, edge, safari)",
    )
    exp_grp.add_argument(
        "--after",
        metavar="DATE",
        help="Filter: include records on or after DATE (format: YYYY-MM-DD)",
    )
    exp_grp.add_argument(
        "--before",
        metavar="DATE",
        help="Filter: include records on or before DATE (format: YYYY-MM-DD)",
    )
    exp_grp.add_argument(
        "--domain",
        metavar="HOST",
        action="append",
        help=(
            "Filter: restrict to a domain and its subdomains. "
            "May be repeated: --domain github.com --domain stackoverflow.com"
        ),
    )

    # ── Storage ───────────────────────────────────────────────
    path_grp = parser.add_argument_group("Storage")
    path_mutex = path_grp.add_mutually_exclusive_group()
    path_mutex.add_argument(
        "--config-dir",
        metavar="PATH",
        help=(
            "Custom config and data directory "
            "(stores config.json, history.db, etc.). "
            "Mutually exclusive with --portable."
        ),
    )
    path_mutex.add_argument(
        "--portable",
        action="store_true",
        help=(
            "Portable mode: store all config and data beside the hsync binary. Mutually exclusive with --config-dir."
        ),
    )

    # ── Output control ────────────────────────────────────────
    out_grp = parser.add_argument_group("Output control")
    out_grp.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug-level logging to the log file and to the console",
    )
    out_grp.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all progress output; only print errors to stderr",
    )
    out_grp.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour output (also honoured via NO_COLOR env var)",
    )
    out_grp.add_argument(
        "--dry-run",
        action="store_true",
        help=("Parse config and discover browsers / validate parameters, but do not write anything to disk or network"),
    )

    return parser


# ══════════════════════════════════════════════════════════════════════════════
# Bootstrap helpers
# ══════════════════════════════════════════════════════════════════════════════


def _setup_paths(args: argparse.Namespace) -> None:
    """Inject custom paths before any module reads the defaults."""
    from src.utils.path_helper import set_runtime_paths

    if args.portable:
        portable_dir = Path(sys.executable).resolve().parent if hasattr(sys, "_MEIPASS") else _repo_root
        set_runtime_paths(config_dir=portable_dir, data_dir=portable_dir)
    elif args.config_dir:
        custom = Path(args.config_dir).expanduser().resolve()
        set_runtime_paths(config_dir=custom, data_dir=custom)


def _setup_logging(args: argparse.Namespace) -> None:
    """Configure the rotating-file logger (and optionally console output)."""
    import logging as _logging

    from src.utils.logger import setup_logger
    from src.utils.path_helper import get_log_dir

    level = _logging.DEBUG if args.verbose else _logging.INFO

    logger = setup_logger(get_log_dir(), level=level)

    # In normal (non-verbose) mode, remove the stdout StreamHandler that
    # setup_logger adds, so that library log lines don't clutter CLI output.
    if not args.verbose:
        for handler in logger.handlers[:]:
            if isinstance(handler, _logging.StreamHandler) and handler.stream is sys.stdout:
                logger.removeHandler(handler)


# ══════════════════════════════════════════════════════════════════════════════
# --status
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_status(config, args: argparse.Namespace) -> int:
    from src.services.local_db import LocalDatabase

    db_path = config.get_db_path()

    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _info("Run  hsync --sync  to create and populate the database.")
        return 1

    if not args.quiet:
        _section("Database Status")

    try:
        db = LocalDatabase(db_path)
        stats = db.get_db_stats()
    except Exception as exc:
        _err(f"Could not read database: {exc}")
        return 1

    if args.quiet:
        # Machine-readable one-liner
        print(f"records={stats.record_count} domains={stats.domain_count} size_kb={stats.file_size_bytes // 1024}")
        return 0

    size_mb = stats.file_size_bytes / (1024 * 1024)
    wasted = stats.wasted_pct

    _info(f"Path         : {db_path}")
    _info(
        f"Size         : {size_mb:.1f} MB"
        + (f"  {_dim(f'({wasted:.0f}% fragmented — run VACUUM to reclaim)')}" if wasted > 10 else "")
    )
    _info(f"Records      : {_bold(f'{stats.record_count:,}')}")
    _info(f"Domains      : {stats.domain_count:,}")
    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# --sync
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_sync(config, args: argparse.Namespace) -> int:
    from src.services.extractor_manager import ExtractorManager
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.sync")
    quiet = args.quiet
    dry_run = args.dry_run

    db_path = config.get_db_path()

    if not quiet:
        _section("Sync")
        _info(f"Database : {db_path}")

    # ── Build ExtractorManager directly (no Qt scheduler) ────
    db = LocalDatabase(db_path)

    disabled = list(config.extractor.disabled_browsers)
    blacklist = list(config.privacy.blacklisted_domains)

    manager = ExtractorManager(
        db=db,
        disabled_browsers=disabled,
        blacklisted_domains=blacklist,
    )

    # Register user-defined custom browser paths (Chromium-based only)
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
            log.info("Registered custom path: %s → %s", browser_type, p)
        except Exception as exc:
            _warn(f"Could not register custom browser '{browser_type}': {exc}")
            log.warning("register_custom_path failed: %s", exc)

    # ── Determine targets ─────────────────────────────────────
    all_registered = manager.get_all_registered()  # {browser_type: display_name}
    available = manager.get_available_browsers()  # installed & enabled

    if not available:
        _warn("No browser installations found on this system.")
        log.warning("No available browsers found.")
        return 0

    if args.browsers:
        requested = [b.strip() for b in args.browsers.split(",") if b.strip()]
        unknown = [b for b in requested if b not in all_registered]
        targets = [b for b in requested if b in all_registered]
        for b in unknown:
            _warn(f"Browser '{b}' is not registered; skipping. Known: {', '.join(sorted(all_registered))}")
        if not targets:
            _err("None of the requested browsers are registered.")
            return 1
        # Warn about requested browsers that are registered but not installed
        unavailable = [b for b in targets if b not in available]
        for b in unavailable:
            _warn(f"Browser '{b}' is registered but not found on this system; skipping.")
        targets = [b for b in targets if b in available]
        if not targets:
            _err("None of the requested browsers are available on this system.")
            return 1
    else:
        targets = available

    if not quiet:
        _info(f"Browsers : {', '.join(targets)}")

    if dry_run:
        _info(_dim("Dry-run mode — no data will be written."))
        return 0

    log.info("Starting sync for browsers: %s", targets)

    # ── Progress callback ─────────────────────────────────────
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
            print(
                f"  {_green('✔')}  {browser_type}: {label}  {_dim(f'({elapsed:.1f}s)')}",
                flush=True,
            )
        elif status == "error":
            print(
                f"  {_red('✖')}  {browser_type}: extraction failed",
                file=sys.stderr,
                flush=True,
            )

    # ── Run extraction (ThreadPoolExecutor internally) ────────
    t0 = time.monotonic()
    results = manager.run_extraction(browser_types=targets, progress_callback=_progress)
    elapsed = time.monotonic() - t0

    total_new = sum(results.values())
    log.info("Sync complete: %d new records in %.1fs", total_new, elapsed)

    if not quiet:
        print()
        _ok(
            f"Sync complete — "
            f"{_bold(f'{total_new:,}')} new records  "
            f"{_dim(f'across {len(results)} browser(s) in {elapsed:.1f}s')}"
        )

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# --backup
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_backup(config, args: argparse.Namespace) -> int:
    from src.services.webdav_sync import WebDavSyncService
    from src.utils.logger import get_logger

    log = get_logger("cli.backup")
    quiet = args.quiet
    dry_run = args.dry_run

    if not quiet:
        _section("WebDAV Backup")

    if not config.webdav.enabled:
        _err("WebDAV is not enabled in config. Open the GUI  →  Settings  →  WebDAV  to configure it.")
        return 1

    if not config.webdav.url.strip():
        _err("WebDAV URL is empty. Configure it in the GUI → Settings → WebDAV.")
        return 1

    if not quiet:
        _info(f"Server : {config.webdav.url}")
        _info(f"User   : {config.webdav.username}")
        _info(f"Path   : {config.webdav.remote_path}")

    if dry_run:
        _info(_dim("Dry-run mode — nothing will be uploaded."))
        return 0

    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _info("Run  hsync --sync  first to create the database.")
        return 1

    service = WebDavSyncService(config.webdav, db_path)

    # Pass the favicon cache directory if it exists alongside the DB
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
# --export
# ══════════════════════════════════════════════════════════════════════════════


def _cmd_export(config, args: argparse.Namespace) -> int:
    from datetime import datetime

    from src.services.exporter import ALL_COLUMNS, Exporter, ResolvedExportParams
    from src.services.favicon_cache import FaviconCache
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger

    log = get_logger("cli.export")
    quiet = args.quiet
    dry_run = args.dry_run

    output_path = Path(args.export).expanduser().resolve()

    # ── Format ───────────────────────────────────────────────────────────────
    if args.format:
        fmt = args.format.lower()
    else:
        ext = output_path.suffix.lower()
        fmt = {".json": "json", ".html": "html", ".htm": "html"}.get(ext, "csv")

    # ── Column validation ─────────────────────────────────────────────────────
    columns: list[str] = []
    if args.columns:
        requested = [c.strip() for c in args.columns.split(",") if c.strip()]
        invalid = [c for c in requested if c not in ALL_COLUMNS]
        if invalid:
            _err(f"Unknown column(s): {', '.join(invalid)}")
            _info(f"Available: {', '.join(ALL_COLUMNS)}")
            return 1
        columns = [c for c in ALL_COLUMNS if c in requested]  # preserve canonical order

    # ── Date filters ──────────────────────────────────────────────────────────
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

    date_from = _parse_date_start(args.after) if args.after else None
    date_to = _parse_date_end(args.before) if args.before else None

    # ── Database ──────────────────────────────────────────────────────────────
    db_path = config.get_db_path()
    if not db_path.exists():
        _err(f"Database not found: {db_path}")
        _info("Run  hsync --sync  first to populate the database.")
        return 1

    db = LocalDatabase(db_path)

    # ── Domain filter → domain IDs ────────────────────────────────────────────
    domain_ids: list[int] | None = None
    if args.domain:
        ids: list[int] = []
        with db._conn(write=False) as conn:
            for d in args.domain:
                ids.extend(LocalDatabase._domain_ids_for(conn, d))
        domain_ids = list(set(ids)) if ids else None
        if args.domain and domain_ids is None and not quiet:
            _warn(f"No records found for domain(s): {', '.join(args.domain)}")

    # ── Favicon cache (HTML + --embed-icons only) ─────────────────────────────
    favicon_cache: FaviconCache | None = None
    if fmt == "html" and args.embed_icons:
        favicon_db_path = config.get_favicon_db_path()
        if favicon_db_path.exists():
            favicon_cache = FaviconCache(favicon_db_path)
        elif not quiet:
            _warn("Favicon database not found; --embed-icons will be skipped.")

    # ── Summary ───────────────────────────────────────────────────────────────
    if not quiet:
        _section("Export")
        _info(f"Output  : {output_path}")
        _info(f"Format  : {fmt.upper()}")
        if columns:
            _info(f"Columns : {', '.join(columns)}")
        if args.keyword:
            _info(f"Filter  : keyword={args.keyword!r}" + ("  [regex]" if args.regex else ""))
        if date_from or date_to:
            _info(f"Filter  : {args.after or '*'} → {args.before or '*'}")
        if args.browser:
            _info(f"Filter  : browser={args.browser}")
        if args.domain:
            _info(f"Filter  : domains={', '.join(args.domain)}")

    if dry_run:
        _info(_dim("Dry-run mode — no file will be written."))
        return 0

    # ── Output directory ──────────────────────────────────────────────────────
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _err(f"Cannot create output directory '{output_path.parent}': {exc}")
        return 1

    # ── Build ResolvedExportParams ────────────────────────────────────────────
    params = ResolvedExportParams(
        output_path=output_path,
        fmt=fmt,
        columns=columns,
        embed_icons=bool(args.embed_icons),
        keyword=args.keyword or "",
        browser_type=args.browser or "",
        date_from=date_from,
        date_to=date_to,
        domain_ids=domain_ids,
        use_regex=bool(args.regex),
    )

    exporter = Exporter(db, favicon_cache)
    last_pct = [-1]
    t0 = time.monotonic()

    def _progress(current: int, total: int) -> None:
        if quiet or total <= 0:
            return
        pct = int(current * 100 / total)
        if pct != last_pct[0] and (pct % 5 == 0 or pct == 100):
            last_pct[0] = pct
            bar_done = pct // 5
            bar_empty = 20 - bar_done
            bar = _green("█" * bar_done) + _dim("░" * bar_empty)
            print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)

    # ── Run export ────────────────────────────────────────────────────────────
    log.info("Exporting to %s (fmt=%s)", output_path, fmt)
    try:
        exporter.export(params, progress_callback=_progress)
    except Exception as exc:
        if not quiet:
            print()  # end progress line
        _err(f"Export failed: {exc}")
        log.exception("Export failed")
        return 1

    elapsed = time.monotonic() - t0
    size_kb = output_path.stat().st_size / 1024 if output_path.exists() else 0

    log.info("Export complete: %.0f KB in %.1fs", size_kb, elapsed)

    if not quiet:
        print()  # end progress line
        _ok(f"Exported → {_bold(str(output_path))}  {_dim(f'({size_kb:.0f} KB  ·  {elapsed:.1f}s)')}")

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ── Honour --no-color early (before any output) ───────────
    global _NO_COLOR
    if args.no_color:
        _NO_COLOR = True

    # ── Mutual-exclusion checks ───────────────────────────────
    if args.quiet and args.verbose:
        _err("--quiet and --verbose are mutually exclusive.")
        sys.exit(2)

    if not any([args.sync, args.backup, args.export, args.status]):
        parser.print_help()
        sys.exit(0)

    # ── Bootstrap ─────────────────────────────────────────────
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
        "hsync starting  sync=%s backup=%s export=%s status=%s dry_run=%s",
        args.sync,
        args.backup,
        bool(args.export),
        args.status,
        args.dry_run,
    )

    # ── Dispatch ──────────────────────────────────────────────
    # --status is always standalone; exit immediately after.
    if args.status:
        sys.exit(_cmd_status(config, args))

    exit_code = 0

    if args.sync:
        rc = _cmd_sync(config, args)
        if rc != 0:
            exit_code = rc

    if args.backup:
        rc = _cmd_backup(config, args)
        if rc != 0:
            exit_code = rc

    if args.export:
        rc = _cmd_export(config, args)
        if rc != 0:
            exit_code = rc

    log.info("hsync exiting, code=%d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
