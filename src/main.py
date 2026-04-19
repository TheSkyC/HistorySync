# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from src.utils.constants import APP_VERSION as _APP_VERSION

# ══════════════════════════════════════════════════════════════════════════════
# CLI argument definitions
# ══════════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="HistorySync",
        description="HistorySync — Browser History Sync Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Launch argument examples:
  python -m src.main --minimized          # Start minimized to tray
  python -m src.main --fresh              # Clean mode, use default config, no disk read/write
  python -m src.main --config-dir D:\\MyConf  # Use a custom config directory
  python -m src.main --portable           # Portable mode, store config in program root directory
  python -m src.main --sync               # Trigger a sync immediately after startup
  python -m src.main --resync             # Full re-extraction (back-fills all historical fields)
  python -m src.main --backup             # Trigger a WebDAV backup immediately after startup
  python -m src.main --sync --backup      # Sync and backup after startup
  python -m src.main --headless --sync    # Headless sync then auto-exit (suitable for scheduled tasks)
  python -m src.main --headless --resync  # Headless full resync then auto-exit
  python -m src.main --headless --backup  # Headless backup then auto-exit

Headless export examples (no GUI launched):
  python -m src.main --export history.csv
  python -m src.main --export history.json --keyword python --after 2024-01-01
  python -m src.main --export report.html --format html --embed-icons --browser chrome
  python -m src.main --export out.csv --columns title,url,visit_time --before 2024-12-31
  python -m src.main --export out.csv --domain github.com --domain stackoverflow.com
  python -m src.main --export out.json --keyword "^https://github" --regex
        """,
    )

    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {_APP_VERSION}")

    # ── Window / Display ─────────────────────────────────────────────────────
    display_group = parser.add_argument_group("Display & Window")
    display_group.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized to the system tray without showing the main window",
    )
    display_group.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Clean mode: start with all default settings, do not read or write config files on disk. "
            "Useful for troubleshooting config issues or quickly experiencing the default state. "
        ),
    )

    # ── Debug / Stress-test ───────────────────────────────────────────────────
    debug_group = parser.add_argument_group("Debug & Stress-test")
    debug_group.add_argument(
        "--mock",
        action="store_true",
        help=(
            "Stress-test mode: generate synthetic history records, bookmarks, and annotations "
            "for performance testing. Forces --fresh so real user data is never touched. "
            "Progress is printed to the console."
        ),
    )
    debug_group.add_argument(
        "--mock-scale",
        metavar="SCALE",
        choices=["small", "medium", "large", "xl"],
        default="large",
        help=(
            "Volume of mock data to generate (default: large). "
            "small=100k  medium=500k  large=1M  xl=5M history records."
        ),
    )
    debug_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging (default: INFO).",
    )
    debug_group.add_argument(
        "--trace-memory",
        action="store_true",
        help="Enable tracemalloc memory profiling. Snapshots are logged periodically and on exit.",
    )
    debug_group.add_argument(
        "--trace-memory-interval",
        metavar="SECONDS",
        type=int,
        default=60,
        help="Interval in seconds between automatic memory snapshots (default: 60). Requires --trace-memory.",
    )

    # ── Paths ─────────────────────────────────────────────────────────────────
    path_group = parser.add_argument_group("Paths & Storage")
    path_mutex = path_group.add_mutually_exclusive_group()
    path_mutex.add_argument(
        "--config-dir",
        metavar="PATH",
        help=(
            "Specify a custom config directory (stores config.json, secret.key, history.db, etc.). "
            "Mutually exclusive with --portable."
        ),
    )
    path_mutex.add_argument(
        "--portable",
        action="store_true",
        help=(
            "Portable mode: store all config and data in the program root directory, "
            "suitable for USB drives or no-install scenarios. Mutually exclusive with --config-dir."
        ),
    )

    # ── Actions ─────────────────────────────────────────────────────────────
    action_group = parser.add_argument_group("Actions to perform immediately after startup")
    action_group.add_argument(
        "--sync",
        action="store_true",
        help="Trigger a browser history sync immediately after startup completes",
    )
    action_group.add_argument(
        "--resync",
        action="store_true",
        help=(
            "Trigger a full re-extraction of all browser history after startup. "
            "Unlike --sync, this ignores the incremental watermark and re-reads every record, "
            "back-filling fields (e.g. visit_count) that were not captured in earlier syncs. "
            "Safe to run at any time — existing records are upserted, not duplicated."
        ),
    )
    action_group.add_argument(
        "--backup",
        action="store_true",
        help="Trigger a WebDAV backup immediately after startup completes",
    )
    action_group.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Show the quick-access overlay in a running HistorySync instance. "
            "On Linux/macOS, bind this to a system hotkey as an alternative to the "
            "Windows-only Ctrl+Shift+H global hotkey."
        ),
    )

    # ── Headless ─────────────────────────────────────────────────────────────
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Headless mode: create no GUI, perform the operations specified by --sync / --backup, then exit automatically. "
            "Suitable for scheduled tasks, script invocations, and CI environments. "
            "If neither --sync nor --backup is specified, sync is performed by default. "
            "Exit code: 0 = success, 1 = error."
        ),
    )

    # ── Headless Export ───────────────────────────────────────────────────────
    export_group = parser.add_argument_group(
        "Headless Export",
        description=(
            "Run a headless export and exit immediately. No Qt GUI is launched.\n"
            "Example: python -m src.main --export history.csv --keyword python --after 2024-01-01"
        ),
    )
    export_group.add_argument(
        "--export",
        metavar="FILE_PATH",
        help=(
            "Export history to FILE_PATH and exit. "
            "Format is inferred from the file extension (.csv / .json / .html); "
            "override with --format."
        ),
    )
    export_group.add_argument(
        "--format",
        metavar="FORMAT",
        choices=["csv", "json", "html"],
        help="Export format: csv | json | html  (default: inferred from extension, fallback csv)",
    )
    export_group.add_argument(
        "--columns",
        metavar="COLS",
        help=(
            "Comma-separated list of columns to include. "
            "Available: id,title,url,visit_time,visit_count,browser_type,profile_name,domain,metadata. "
            "Default: all columns."
        ),
    )
    export_group.add_argument(
        "--embed-icons",
        action="store_true",
        help="Embed favicons as Base64 data-URIs (HTML export only).",
    )
    # Reuse existing query filters for --export
    export_group.add_argument("--keyword", metavar="TEXT", help="Filter: keyword / regex (use with --regex)")
    export_group.add_argument("--browser", metavar="TYPE", help="Filter: browser type (e.g. chrome, firefox, edge)")
    export_group.add_argument("--after", metavar="DATE", help="Filter: include records on or after DATE (YYYY-MM-DD)")
    export_group.add_argument("--before", metavar="DATE", help="Filter: include records on or before DATE (YYYY-MM-DD)")
    export_group.add_argument(
        "--domain",
        metavar="HOST",
        action="append",
        help="Filter: restrict to domain (may be repeated, e.g. --domain github.com --domain google.com)",
    )
    export_group.add_argument("--regex", action="store_true", help="Treat --keyword as a Python regular expression")

    return parser


# ══════════════════════════════════════════════════════════════════════════════
# Headless export
# ══════════════════════════════════════════════════════════════════════════════


def _cli_export_main(args: argparse.Namespace) -> int:
    """
    Perform a headless export then exit.
    Returns 0 on success, 1 on error.
    """
    from datetime import datetime
    import logging as _logging

    from src.models.app_config import AppConfig
    from src.services.exporter import ALL_COLUMNS, Exporter, ResolvedExportParams
    from src.services.favicon_cache import FaviconCache
    from src.services.local_db import LocalDatabase
    from src.utils.logger import get_logger, setup_logger
    from src.utils.path_helper import get_log_dir

    setup_logger(get_log_dir(), level=_logging.WARNING, console_only=True)
    log = get_logger("main.export")

    # ── Config ────────────────────────────────────────────────────────────────
    if getattr(args, "fresh", False):
        config = AppConfig()
        config._fresh = True
    else:
        config = AppConfig.load()

    # ── Output path & format ──────────────────────────────────────────────────
    output_path = Path(args.export).expanduser().resolve()

    if args.format:
        fmt = args.format.lower()
    else:
        ext = output_path.suffix.lower()
        fmt = {".json": "json", ".html": "html", ".htm": "html"}.get(ext, "csv")

    # ── Columns ───────────────────────────────────────────────────────────────
    if args.columns:
        requested = [c.strip() for c in args.columns.split(",")]
        columns = [c for c in requested if c in ALL_COLUMNS]
        if not columns:
            return 1
    else:
        columns = []  # empty = all

    # ── Date conversion ───────────────────────────────────────────────────────
    def _parse_date_start(s: str) -> int:
        try:
            d = datetime.strptime(s.strip(), "%Y-%m-%d")
            return int(d.replace(hour=0, minute=0, second=0).timestamp())
        except ValueError:
            sys.exit(1)

    def _parse_date_end(s: str) -> int:
        try:
            d = datetime.strptime(s.strip(), "%Y-%m-%d")
            return int(d.replace(hour=23, minute=59, second=59).timestamp())
        except ValueError:
            sys.exit(1)

    date_from = _parse_date_start(args.after) if args.after else None
    date_to = _parse_date_end(args.before) if args.before else None

    # ── Domain → domain_ids ───────────────────────────────────────────────────
    db = LocalDatabase(config.get_db_path())
    domain_ids: list[int] | None = None
    if args.domain:
        ids = db.get_domain_ids(list(args.domain))
        domain_ids = ids if ids else None

    # ── Favicon cache (needed only for HTML + embed-icons) ────────────────────
    favicon_cache: FaviconCache | None = None
    if fmt == "html" and args.embed_icons:
        favicon_cache = FaviconCache(config.get_favicon_db_path())

    # ── Build params ──────────────────────────────────────────────────────────
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

    # ── Run export ────────────────────────────────────────────────────────────
    exporter = Exporter(db, favicon_cache)

    last_pct = [-1]

    def _progress(current: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(current * 100 / total)
        if pct != last_pct[0]:
            last_pct[0] = pct

    try:
        exporter.export(params, progress_callback=_progress)
        return 0
    except Exception:
        log.exception("Export failed")
        return 1


def _headless_main(args: argparse.Namespace) -> int:
    """Run sync / backup without a GUI; returns exit code (0=success, 1=error)."""
    import logging as _logging

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from src.models.app_config import AppConfig
    from src.utils.constants import (
        APP_NAME,
        APP_VERSION,
        FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS,
        ORG_NAME,
        SCHEDULER_SHUTDOWN_TIMEOUT_MS,
    )
    from src.utils.i18n import lang_manager
    from src.utils.logger import get_logger, setup_logger
    from src.utils.path_helper import get_log_dir
    from src.viewmodels.main_viewmodel import MainViewModel

    # Logging
    setup_logger(get_log_dir(), level=_logging.INFO)
    log = get_logger("main.headless")
    log.info("HistorySync headless mode starting")

    # Config
    if args.fresh:
        config = AppConfig()
        config._fresh = True
        log.info("Headless: fresh mode — using default config")
    else:
        config = AppConfig.load()
        log.info("Headless: config loaded")

    do_sync = args.sync or (not args.sync and not args.backup and not getattr(args, "resync", False))
    do_resync = getattr(args, "resync", False)
    do_backup = args.backup

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationVersion(APP_VERSION)
    qt_app.setOrganizationName(ORG_NAME)

    lang_manager.setup_translation(config.language or None)

    main_vm = MainViewModel(config, headless=True)

    exit_code = [0]
    pending = [0]
    errors = []

    # ── Timeout guard (default 10 minutes) ───────────────────────────────────
    HEADLESS_TIMEOUT_MS = 10 * 60 * 1000

    def _on_timeout():
        log.error("Headless: operation timed out after 10 minutes")
        exit_code[0] = 1
        qt_app.quit()

    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.timeout.connect(_on_timeout)
    timeout_timer.start(HEADLESS_TIMEOUT_MS)

    def _check_done():
        pending[0] -= 1
        if pending[0] <= 0:
            timeout_timer.stop()
            log.info("Headless: all operations finished, exit_code=%d", exit_code[0])
            QTimer.singleShot(200, qt_app.quit)

    # ── Sync signals ─────────────────────────────────────────────────────────
    if do_sync or do_resync:
        pending[0] += 1

        def _on_sync_done(new_count: int):
            label = "resync" if do_resync else "sync"
            log.info("Headless %s done: %d new records", label, new_count)
            _check_done()

        def _on_sync_error(msg: str):
            label = "resync" if do_resync else "sync"
            log.error("Headless %s error: %s", label, msg)
            errors.append(msg)
            exit_code[0] = 1
            _check_done()

        main_vm.sync_finished.connect(_on_sync_done)
        main_vm.sync_error.connect(_on_sync_error)

    # ── Backup signals ────────────────────────────────────────────────────────
    if do_backup:
        if not config.webdav.enabled:
            log.warning("Headless: --backup requested but WebDAV is not enabled in config")
        else:
            pending[0] += 1

            def _on_backup_done(success: bool, msg: str):
                if success:
                    log.info("Headless backup done: %s", msg)
                else:
                    log.error("Headless backup failed: %s", msg)
                    errors.append(msg)
                    exit_code[0] = 1
                _check_done()

            main_vm.backup_finished.connect(_on_backup_done)

    # ── Start ─────────────────────────────────────────────────────────────────
    def _start():
        main_vm.start_headless()

        if do_sync:
            log.info("Headless: triggering sync")
            main_vm.trigger_sync()
        if do_resync:
            log.info("Headless: triggering full resync")
            main_vm.trigger_full_resync()
        if do_backup and config.webdav.enabled:
            log.info("Headless: triggering backup")
            main_vm.trigger_backup()

        if pending[0] <= 0:
            timeout_timer.stop()
            QTimer.singleShot(0, qt_app.quit)

    QTimer.singleShot(0, _start)
    qt_app.exec()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    try:
        main_vm._scheduler.stop()
        main_vm._scheduler.shutdown(timeout_ms=SCHEDULER_SHUTDOWN_TIMEOUT_MS)
        if main_vm._favicon_manager is not None:
            main_vm._favicon_manager.shutdown(timeout_ms=FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS)
    except Exception as exc:
        log.warning("Headless shutdown error: %s", exc)
    try:
        main_vm._db.close()
    except Exception as exc:
        log.warning("DB close error during headless shutdown: %s", exc)

    if errors:
        log.error("Headless: %d operation(s) failed:", len(errors))
        for i, err in enumerate(errors, 1):
            log.error("  [%d] %s", i, err)

    log.info("HistorySync headless exit, code=%d", exit_code[0])
    return exit_code[0]


# ══════════════════════════════════════════════════════════════════════════════
# GUI mode
# ══════════════════════════════════════════════════════════════════════════════


def _gui_main(args: argparse.Namespace) -> None:
    """Normal GUI startup flow."""
    import logging as _logging

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from src.models.app_config import AppConfig
    from src.utils.constants import (
        APP_NAME,
        APP_VERSION,
        DEFAULT_FONT_FAMILY,
        DEFAULT_FONT_SIZE,
        ORG_NAME,
    )
    from src.utils.i18n import _, lang_manager
    from src.utils.logger import get_logger, setup_logger
    from src.utils.path_helper import get_config_dir, get_log_dir
    from src.viewmodels.main_viewmodel import MainViewModel
    from src.views.main_window import MainWindow
    from src.views.tray_icon import TrayIcon

    # ── 1. Logging ───────────────────────────────────────────────────────────
    log_dir = get_log_dir()
    setup_logger(log_dir, level=_logging.DEBUG if args.debug else _logging.INFO)
    log = get_logger("main")
    log.warning("HistorySync starting up  args=%s", vars(args))

    # ── 1a. Legacy migration detection (before AppConfig.load) ───────────────
    # We need a minimal QApplication to show dialogs, so we set it up early
    # and re-use it below.  The full setup (font, theme, etc.) happens later.
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setAttribute(Qt.AA_DontUseNativeMenuBar, True)

    if not args.fresh:
        from src.utils.migration_detector import detect_legacy_installation

        legacy = detect_legacy_installation()

        if legacy.found:
            log.info("Legacy installation detected — showing migration wizard")
            from src.views.migration_wizard import MigrationWizard

            wizard = MigrationWizard(legacy)
            wizard.exec()
            log.info("Migration wizard closed")
            # Whether the user migrated, skipped, or quit, we continue with
            # the normal startup flow.  AppConfig.load() will now find a valid
            # (possibly freshly merged) config.json with first_run_completed set.

    # ── 2. Config ────────────────────────────────────────────────────────────
    if args.fresh or args.mock:
        config = AppConfig()
        config._fresh = True
        if args.mock:
            log.info("Mock mode: using fresh config, disk writes suppressed")
        else:
            log.info("Fresh mode: using default config, disk writes suppressed")

        # Clean up stale fresh-mode temp directories from previous runs
        from src.utils.path_helper import cleanup_stale_fresh_dirs

        try:
            removed = cleanup_stale_fresh_dirs(max_age_hours=24)
            if removed > 0:
                log.info("Cleaned up %d stale fresh-mode temp directories", removed)
        except Exception as exc:
            log.warning("Failed to clean stale temp directories: %s", exc)
    else:
        config = AppConfig.load()
        log.info("Config loaded from: %s", get_config_dir())

    # ── 3. i18n ──────────────────────────────────────────────────────────────
    lang_code = config.language or None
    lang_manager.setup_translation(lang_code)
    log.info("Language: %s", lang_manager.get_current_language())

    # ── 4. Qt application (already created above for migration check) ───────
    # QApplication is a singleton; just retrieve the existing instance.
    app = QApplication.instance() or QApplication(sys.argv[:1])

    # ── 4a. Single-instance guard ────────────────────────────────────────────
    # Must be created *after* QApplication so QTcpServer/QTcpSocket work, but
    # *before* we build the heavy ViewModel / MainWindow objects.
    from src.utils.single_instance import SINGLE_INSTANCE_PORT, SingleInstanceServer, raise_existing_instance

    if raise_existing_instance():
        log.warning("Another instance of HistorySync is already running — activating it and exiting.")
        sys.exit(0)

    _single_instance_server = SingleInstanceServer(app)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setStyle("Fusion")

    font = QFont()
    font.setFamily(DEFAULT_FONT_FAMILY)
    font.setPointSize(DEFAULT_FONT_SIZE)
    app.setFont(font)

    from src.utils.theme_manager import ThemeManager

    ThemeManager.instance().apply_sync(app, config.theme)

    from src.utils.font_manager import FontManager

    FontManager.instance().apply(config.font, app)
    app.setQuitOnLastWindowClosed(False)

    from src.utils.icon_helper import get_app_icon as _get_app_icon

    _app_icon = _get_app_icon()
    if not _app_icon.isNull():
        app.setWindowIcon(_app_icon)

    # ── 5. ViewModel ─────────────────────────────────────────────────────────
    # Mock data generation runs before the ViewModel so the DB is fully
    # populated when the UI first queries it.
    if args.mock:
        from src.services.local_db import LocalDatabase as _LocalDatabase
        from src.services.mock_data_generator import generate_mock_data

        log.info("Mock mode: initialising schema then generating stress-test data")
        _db_init = _LocalDatabase(config.get_db_path())
        _db_init.get_db_stats()  # triggers lazy connection + schema init
        _db_init.close()
        generate_mock_data(config.get_db_path(), scale=args.mock_scale or "large")
        log.info("Mock data generation complete")

    # Compute before ViewModel so lazy_gui can be passed at construction time.
    should_minimize = (
        args.minimized
        or config.scheduler.start_minimized
        or (config.scheduler.launch_on_startup and _is_startup_launch())
    )

    main_vm = MainViewModel(config, lazy_gui=should_minimize)

    # Register cleanup handler for fresh mode
    if config._fresh:
        import atexit

        atexit.register(config.cleanup_fresh_tmp)

    # Wire up single-instance activation → bring the window to the front
    if not _single_instance_server.start():
        # The port is occupied but raise_existing_instance() did not respond —
        # most likely another process is holding it.  Running without the guard
        # risks two instances writing to the database simultaneously, so abort.
        log.error(
            "SingleInstanceServer failed to bind port %d; aborting to protect database integrity.",
            SINGLE_INSTANCE_PORT,
        )
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None,
            _("Launch Error"),
            _(
                "HistorySync could not acquire the single-instance lock\n"
                "(port 20455 is already in use by another process).\n\n"
                "Please close any other running instances and try again."
            ),
        )
        sys.exit(1)
    _single_instance_server.request_activation.connect(lambda: _get_or_create_window().show_and_raise())

    # ── Overlay hotkey (Windows) + --quick cross-platform path ──────────────
    def _on_overlay_hotkey():
        overlay = main_vm.ensure_overlay()
        if overlay is not None:
            overlay.toggle()

    _single_instance_server.request_quick_overlay.connect(_on_overlay_hotkey)

    _hotkey_mgr = None
    if sys.platform == "win32" and config.overlay.enabled:
        from src.services.hotkey_manager import HotkeyManager

        _hotkey_mgr = HotkeyManager()
        if _hotkey_mgr.register():
            _hotkey_mgr.triggered.connect(_on_overlay_hotkey)
            app.installNativeEventFilter(_hotkey_mgr)
            log.debug("Global hotkey Ctrl+Shift+H registered")
        else:
            log.warning("Failed to register global hotkey Ctrl+Shift+H")

    if _hotkey_mgr is not None:

        def _on_settings_saved():
            if main_vm._config.overlay.enabled:
                if not _hotkey_mgr._registered:
                    _hotkey_mgr.register()
            else:
                _hotkey_mgr.unregister()

    # ── 6. Window trampoline ─────────────────────────────────────────────────
    # In lazy_gui mode the MainWindow is not constructed at startup.  The
    # trampoline is called the first time any code needs the window (tray
    # click, single-instance activation, first-run wizard, normal show path).
    _window: MainWindow | None = None

    def _show_config_error_dialog(parent, cfg):
        from PySide6.QtWidgets import QMessageBox

        if cfg._load_error:
            msg = _(
                "The configuration file was corrupt or unreadable and could not be loaded.\n\n"
                "Your settings (WebDAV credentials, privacy blacklist, etc.) have been "
                "reset to defaults.\n\n"
                "The corrupt file has been backed up to:\n{bak_path}"
            ).format(bak_path=cfg._load_error)
        else:
            msg = _(
                "The configuration file was corrupt or unreadable and could not be loaded.\n\n"
                "Your settings (WebDAV credentials, privacy blacklist, etc.) have been "
                "reset to defaults.\n\n"
                "The backup of the corrupt file also failed. "
                "Please check your config directory."
            )
        QMessageBox.warning(parent, _("Configuration Load Error"), msg)

    def _get_or_create_window() -> MainWindow:
        nonlocal _window
        if _window is not None:
            return _window
        main_vm.initialize_gui()  # no-op if not lazy_gui
        _window = MainWindow(main_vm)
        # close_to_tray notification
        _window.close_to_tray.connect(
            lambda: tray.show_notification(
                APP_NAME,
                _("HistorySync has been minimized to the system tray and continues running in the background."),
            )
        )
        # B4 fix: guard — _on_settings_saved only defined when _hotkey_mgr is not None
        if _hotkey_mgr is not None:
            _window._settings_vm.saved.connect(_on_settings_saved)
        # B1 fix: lazy_gui path — scheduler already armed by start_lazy_gui(), only run start_ui()
        if config.first_run_completed:
            if main_vm._lazy_gui:
                QTimer.singleShot(200, main_vm.start_ui)
            else:
                QTimer.singleShot(200, main_vm.start)
        else:
            QTimer.singleShot(200, main_vm.start_ui)
        # Config-load-error dialog (in lazy_gui mode appears on first open, not at startup)
        if getattr(config, "_load_error", None) is not None:
            _show_config_error_dialog(_window, config)
        return _window

    # ── 7. System tray ───────────────────────────────────────────────────────
    tray = TrayIcon()

    if not tray.is_available():
        log.warning("System tray not available on this platform")
        app.setQuitOnLastWindowClosed(True)

    tray.show()
    tray.set_main_vm(main_vm)
    tray.open_requested.connect(lambda: _get_or_create_window().show_and_raise())
    tray.sync_requested.connect(main_vm.trigger_sync)
    tray.quit_requested.connect(lambda: _quit(main_vm, log))

    main_vm.sync_started.connect(lambda: tray.set_syncing(True))
    main_vm.sync_finished.connect(lambda n: _on_tray_sync_done(tray, n))
    main_vm.sync_error.connect(lambda msg: _on_tray_sync_error(tray, msg))
    main_vm.stats_updated.connect(
        lambda total, __: tray.set_status(_("{total} records in total").format(total=f"{total:,}"))
    )

    # ── 8. Display strategy ──────────────────────────────────────────────────
    if should_minimize:
        log.info(
            "Starting minimized to tray (minimized=%s, start_minimized=%s, startup=%s)",
            args.minimized,
            config.scheduler.start_minimized,
            config.scheduler.launch_on_startup,
        )
        # Arm scheduler only — window and GUI subsystems built on first tray click.
        QTimer.singleShot(0, main_vm.start_lazy_gui)
    else:
        _get_or_create_window().show()
        # Pre-warm overlay so the first Ctrl+Shift+H is instant.
        if config.overlay.enabled:
            QTimer.singleShot(3000, main_vm.ensure_overlay)

    # ── 8a. First-run wizard ─────────────────────────────────────────────────
    if not config.first_run_completed:
        from src.views.first_run_wizard import FirstRunWizard

        def _show_first_run():
            w = _get_or_create_window()  # builds window + initialize_gui() if lazy
            wizard = FirstRunWizard(config, w)
            wizard.learned_browsers_added.connect(main_vm.on_learned_browsers_added)
            wizard.exec()
            if w._page_settings is not None:
                w._page_settings.reload_security()
            main_vm.reload_extractor_config()

            if not config.first_run_completed:
                config.first_run_completed = True
                log.info("First-run wizard: safety-net marking first_run_completed=True")
            try:
                config.save()
            except Exception as exc:
                log.warning("First-run wizard: safety-net save failed: %s", exc)

            # B2: scheduler not yet armed in lazy path (start_lazy_gui() skipped
            # first-run), so start_scheduler() here is safe to call exactly once.
            main_vm.start_scheduler()
            log.info("First-run wizard: scheduler started")

            # If user checked "sync immediately", trigger sync after a short delay
            if wizard.should_sync_on_finish:
                log.info("First-run wizard: triggering initial sync")
                QTimer.singleShot(500, main_vm.trigger_sync)

        QTimer.singleShot(300, _show_first_run)
        log.info("First-run wizard scheduled")

    # ── 9. Actions to perform immediately after startup ──────────────────────
    if args.sync:
        log.info("CLI --sync: will trigger sync after startup")
        QTimer.singleShot(500, main_vm.trigger_sync)

    if getattr(args, "resync", False):
        log.info("CLI --resync: will trigger full resync after startup")
        delay = 800 if args.sync else 500
        QTimer.singleShot(delay, main_vm.trigger_full_resync)

    if args.backup:
        if not config.webdav.enabled:
            log.warning("CLI --backup: WebDAV not enabled, skipping")
        else:
            log.info("CLI --backup: will trigger backup after startup")
            delay = 800 if args.sync else 500
            QTimer.singleShot(delay, main_vm.trigger_backup)

    # ── 10. Event loop ───────────────────────────────────────────────────────
    log.info("Application event loop starting")

    if getattr(args, "trace_memory", False):
        from src.utils.memory_tracer import dump_snapshot, schedule_periodic_dump

        schedule_periodic_dump(args.trace_memory_interval)
        import atexit

        atexit.register(dump_snapshot)

    sys.exit(app.exec())


# ══════════════════════════════════════════════════════════════════════════════
# Utility functions
# ══════════════════════════════════════════════════════════════════════════════


def _is_startup_launch() -> bool:
    """Detect whether this process was launched automatically at system startup.

    Covers:
    - Windows: Task Scheduler / winlogon parent process
    - macOS:   launchd (LAUNCH_DAEMON / LAUNCH_AGENT env vars)
    - Linux:   systemd (INVOCATION_ID), OpenRC (/run/openrc/softlevel),
               runit/s6/dinit (parent PID 1 with matching process name),
               and generic XDG autostart (DESKTOP_AUTOSTART_ID)
    """
    try:
        if sys.platform == "win32":
            import psutil

            parent_name = psutil.Process(os.getpid()).parent().name().lower()
            return any(k in parent_name for k in ("taskeng", "svchost", "winlogon", "taskschd"))

        if sys.platform == "darwin":
            return "LAUNCH_DAEMON" in os.environ or "LAUNCH_AGENT" in os.environ

        # Linux: try each init system in order of cheapness
        # 1. systemd
        if "INVOCATION_ID" in os.environ:
            return True

        # 2. XDG autostart (desktop session autostart via .desktop files)
        if "DESKTOP_AUTOSTART_ID" in os.environ:
            return True

        # 3. OpenRC — sets RUNLEVEL or writes /run/openrc/softlevel
        if Path("/run/openrc/softlevel").exists():
            return True

        # 4. runit / s6 / dinit — PID 1 is the supervision suite itself
        try:
            import psutil

            parent = psutil.Process(os.getpid()).parent()
            if parent is not None and parent.pid == 1:
                parent_name = parent.name().lower()
                if any(k in parent_name for k in ("runit", "s6", "dinit", "shepherd")):
                    return True
        except Exception:
            pass

        return False
    except Exception:
        return False


def _on_tray_sync_done(tray, new_count: int):
    from src.utils.i18n import _

    tray.set_syncing(False)
    tray.set_status(_("Last sync: {count} new").format(count=new_count))
    if new_count > 0:
        tray.show_notification(
            _("Sync Complete"),
            _("{count} new history records added").format(count=new_count),
        )


def _on_tray_sync_error(tray, msg: str):
    from PySide6.QtWidgets import QSystemTrayIcon

    from src.utils.i18n import _

    tray.set_syncing(False)
    tray.set_status(_("Sync error"))
    tray.show_notification(_("Sync Failed"), msg, QSystemTrayIcon.Warning)


def _quit(main_vm=None, log=None):
    from PySide6.QtWidgets import QApplication

    from src.utils.constants import FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS, SCHEDULER_SHUTDOWN_TIMEOUT_MS
    from src.utils.logger import get_logger

    if log is None:
        log = get_logger("main")
    log.warning("HistorySync shutting down")

    if main_vm is not None:
        try:
            if main_vm._monitor is not None:
                main_vm._monitor.stop()
            main_vm._scheduler.stop()
            main_vm._scheduler.shutdown(timeout_ms=SCHEDULER_SHUTDOWN_TIMEOUT_MS)
            if main_vm._favicon_manager is not None:
                main_vm._favicon_manager.shutdown(timeout_ms=FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS)
        except Exception as exc:
            log.warning("Error during shutdown: %s", exc)
        # Close the DB explicitly so SQLite performs a final WAL checkpoint
        # before the process exits.  On Windows, relying on GC to close the
        # connection can leave the WAL file un-checkpointed, forcing a recovery
        # pass on the next startup.
        try:
            main_vm._db.close()
        except Exception as exc:
            log.warning("DB close error during shutdown: %s", exc)
        # Fresh mode: explicitly release the TemporaryDirectory *after* all
        # SQLite connections are closed.  On Windows, open file handles block
        # directory removal, so we must not rely on the GC/weakref finalizer.
        try:
            main_vm._config.cleanup_fresh_tmp()
        except Exception as exc:
            log.warning("Fresh-mode temp cleanup error: %s", exc)

    QApplication.quit()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


def main():
    # Fast path: skip parser construction for --version/-V
    if len(sys.argv) == 2 and sys.argv[1] in ("--version", "-V"):
        print(f"HistorySync {_APP_VERSION}")  # noqa: T201
        sys.exit(0)

    # ── Step 1: Parse CLI arguments (before any Qt / logging initialization) ─
    parser = _build_parser()
    args = parser.parse_args()

    # ── Step 2: Inject runtime path overrides ──
    from pathlib import Path

    from src.utils.path_helper import set_runtime_paths

    # In a frozen (PyInstaller) build, use the directory containing the .exe.
    # In development, fall back to the project root.
    _exe_dir = Path(sys.executable).resolve().parent if hasattr(sys, "_MEIPASS") else Path(_repo_root)

    if args.portable or (_exe_dir / ".portable").exists():
        _portable_data = _exe_dir / "data"
        set_runtime_paths(config_dir=_portable_data, data_dir=_portable_data)

    elif args.config_dir:
        custom_dir = Path(args.config_dir).expanduser().resolve()
        set_runtime_paths(config_dir=custom_dir, data_dir=custom_dir)

    # ── Step 2b: Start memory tracer as early as possible ───────────────────
    if getattr(args, "trace_memory", False):
        from src.utils.memory_tracer import start as _start_tracer

        _start_tracer()

    # ── Step 3: Dispatch to headless export, headless sync, or GUI ──────────
    if getattr(args, "export", None):
        sys.exit(_cli_export_main(args))
    elif args.headless:
        sys.exit(_headless_main(args))
    elif getattr(args, "quick", False):
        # --quick: send ACTIVATE_QUICK_MSG to a running instance via stdlib
        # socket (no Qt import needed — keeps startup time ~70ms).
        from src.utils.single_instance import send_quick_overlay

        sent = send_quick_overlay()
        sys.exit(0 if sent else 1)
    else:
        _gui_main(args)


if __name__ == "__main__":
    main()
