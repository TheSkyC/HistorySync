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

    setup_logger(get_log_dir(), level=_logging.WARNING)
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
        fmt = {"json": "json", ".json": "json", ".html": "html", ".htm": "html"}.get(ext, "csv")

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
        ids: list[int] = []
        with db._lock:
            conn = db._ensure_conn()
            for d in args.domain:
                ids.extend(LocalDatabase._domain_ids_for(conn, d))
        domain_ids = list(set(ids)) if ids else None

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

    main_vm = MainViewModel(config)

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
        main_vm.start()

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
        main_vm._favicon_manager.shutdown(timeout_ms=FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS)
    except Exception as exc:
        log.warning("Headless shutdown error: %s", exc)

    if errors:
        pass

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
    setup_logger(log_dir, level=_logging.DEBUG)
    log = get_logger("main")
    log.warning("HistorySync starting up  args=%s", vars(args))

    # ── 1a. Legacy migration detection (before AppConfig.load) ───────────────
    # We need a minimal QApplication to show dialogs, so we set it up early
    # and re-use it below.  The full setup (font, theme, etc.) happens later.
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])

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
    if args.fresh:
        config = AppConfig()
        config._fresh = True
        log.info("Fresh mode: using default config, disk writes suppressed")
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
    from src.utils.single_instance import SingleInstanceServer, raise_existing_instance

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
    app.setQuitOnLastWindowClosed(False)

    from src.utils.icon_helper import get_app_icon as _get_app_icon

    _app_icon = _get_app_icon()
    if not _app_icon.isNull():
        app.setWindowIcon(_app_icon)

    # ── 5. ViewModel ─────────────────────────────────────────────────────────
    main_vm = MainViewModel(config)

    # ── 6. Main window ───────────────────────────────────────────────────────
    window = MainWindow(main_vm)

    # Wire up single-instance activation → bring the window to the front
    if not _single_instance_server.start():
        # In the unlikely race where start() fails here (port grabbed between
        # the raise_existing_instance() check and now), just continue without
        # the guard rather than crashing.
        log.warning("SingleInstanceServer failed to start; single-instance protection is inactive")
    _single_instance_server.request_activation.connect(window.show_and_raise)

    # ── 7. System tray ───────────────────────────────────────────────────────
    tray = TrayIcon()

    if not tray.is_available():
        log.warning("System tray not available on this platform")
        app.setQuitOnLastWindowClosed(True)

    tray.show()
    tray.set_main_vm(main_vm)
    tray.open_requested.connect(window.show_and_raise)
    tray.sync_requested.connect(main_vm.trigger_sync)
    tray.quit_requested.connect(lambda: _quit(main_vm, log))

    window.close_to_tray.connect(
        lambda: tray.show_notification(
            APP_NAME,
            _("HistorySync has been minimized to the system tray and continues running in the background."),
        )
    )

    main_vm.sync_started.connect(lambda: tray.set_syncing(True))
    main_vm.sync_finished.connect(lambda n: _on_tray_sync_done(tray, n))
    main_vm.sync_error.connect(lambda msg: _on_tray_sync_error(tray, msg))
    main_vm.stats_updated.connect(
        lambda total, __: tray.set_status(_("{total} records in total").format(total=f"{total:,}"))
    )

    # ── 8. Display strategy ──────────────────────────────────────────────────
    should_minimize = args.minimized or (config.scheduler.launch_on_startup and _is_startup_launch())

    if should_minimize:
        log.info(
            "Starting minimized to tray (minimized=%s, startup=%s)", args.minimized, config.scheduler.launch_on_startup
        )
    else:
        window.show()

    # ── 8a. First-run wizard ─────────────────────────────────────────────────
    if not config.first_run_completed:
        from src.views.first_run_wizard import FirstRunWizard

        def _show_first_run():
            wizard = FirstRunWizard(config, window if not should_minimize else None)
            wizard.learned_browsers_added.connect(main_vm.on_learned_browsers_added)
            wizard.exec()
            if window._page_settings is not None:
                window._page_settings.reload_security()
            main_vm.reload_extractor_config()

            if not config.first_run_completed:
                config.first_run_completed = True
                log.info("First-run wizard: safety-net marking first_run_completed=True")
            try:
                config.save()
            except Exception as exc:
                log.warning("First-run wizard: safety-net save failed: %s", exc)

            main_vm.start_scheduler()
            log.info("First-run wizard: scheduler started")

            # 如果用户勾选了"立即同步"，延迟触发一次同步
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
    sys.exit(app.exec())


# ══════════════════════════════════════════════════════════════════════════════
# Utility functions
# ══════════════════════════════════════════════════════════════════════════════


def _is_startup_launch() -> bool:
    try:
        if sys.platform == "win32":
            import psutil

            parent_name = psutil.Process(os.getpid()).parent().name().lower()
            return any(k in parent_name for k in ("taskeng", "svchost", "winlogon", "taskschd"))
        # Both systemd and launchd set these variables
        return (
            "INVOCATION_ID" in os.environ  # systemd
            or "LAUNCH_DAEMON" in os.environ  # launchd
        )
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
            main_vm._scheduler.stop()
            main_vm._scheduler.shutdown(timeout_ms=SCHEDULER_SHUTDOWN_TIMEOUT_MS)
            main_vm._favicon_manager.shutdown(timeout_ms=FAVICON_MANAGER_SHUTDOWN_TIMEOUT_MS)
        except Exception as exc:
            log.warning("Error during shutdown: %s", exc)

    QApplication.quit()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


def main():
    # ── Step 1: Parse CLI arguments (before any Qt / logging initialization) ─
    parser = _build_parser()
    args = parser.parse_args()

    # ── Step 2: Inject runtime path overrides ──
    from pathlib import Path

    from src.utils.path_helper import set_runtime_paths

    if args.portable:
        # Program root = parent directory of main.py (i.e., the project root)
        portable_dir = Path(_repo_root)
        set_runtime_paths(config_dir=portable_dir, data_dir=portable_dir)

    elif args.config_dir:
        custom_dir = Path(args.config_dir).expanduser().resolve()
        set_runtime_paths(config_dir=custom_dir, data_dir=custom_dir)

    # ── Step 3: Dispatch to headless export, headless sync, or GUI ──────────
    if getattr(args, "export", None):
        sys.exit(_cli_export_main(args))
    elif args.headless:
        sys.exit(_headless_main(args))
    else:
        _gui_main(args)


if __name__ == "__main__":
    main()
