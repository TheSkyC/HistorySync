# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.logger import get_logger
from src.viewmodels.settings_viewmodel import SettingsViewModel
from src.views.settings.countdown import (
    compute_next_backup_ts,
    compute_next_sync_ts,
    fmt_countdown,
)
from src.views.settings.custom_paths_section import CustomPathsSection
from src.views.settings.import_section import ImportSection
from src.views.settings.language_section import LanguageSection
from src.views.settings.maintenance_section import MaintenanceSection
from src.views.settings.privacy_section import PrivacySection
from src.views.settings.scheduler_section import SchedulerSection
from src.views.settings.security_section import SecuritySection
from src.views.settings.startup_section import StartupSection
from src.views.settings.webdav_section import WebDavSection

log = get_logger("view.settings")


class SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("stat_label")
        self.setContentsMargins(0, 8, 0, 4)


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, vm: SettingsViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._next_sync_ts: int | None = None
        self._next_backup_ts: int | None = None

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(30_000)
        self._countdown_timer.timeout.connect(self._update_countdowns)
        self._countdown_timer.start()

        self._init_ui()
        self._load_config()
        self._connect_signals()
        self._apply_wheel_event_filter()

    # ── UI construction ───────────────────────────────────────

    def _init_ui(self):
        self.setFocusPolicy(Qt.ClickFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(32, 8, 32, 32)
        self._content_layout.setSpacing(12)

        self._sec_language = LanguageSection()
        self._sec_scheduler = SchedulerSection()
        self._sec_startup = StartupSection()
        self._sec_webdav = WebDavSection()
        self._sec_privacy = PrivacySection()
        self._sec_security = SecuritySection()
        self._sec_paths = CustomPathsSection()
        self._sec_import = ImportSection()
        self._sec_maint = MaintenanceSection()

        self._add_card(_("LANGUAGE"), self._sec_language)
        self._add_card(_("AUTO SYNC"), self._sec_scheduler)
        self._add_card(_("STARTUP"), self._sec_startup)
        self._add_card(_("WEBDAV CLOUD BACKUP"), self._sec_webdav)
        self._add_card(_("PRIVACY & BLACKLIST"), self._sec_privacy)
        self._add_card(_("SECURITY"), self._sec_security)
        self._add_card(_("CUSTOM BROWSER PATHS"), self._sec_paths)
        self._add_card(_("IMPORT HISTORY DATABASE"), self._sec_import)
        self._add_card(_("DATABASE MAINTENANCE"), self._sec_maint)

        self._content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _build_header(self) -> QWidget:
        header_w = QWidget()
        header_w.setObjectName("page_header")
        h_layout = QHBoxLayout(header_w)
        h_layout.setContentsMargins(32, 28, 32, 16)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._title_lbl = QLabel(_("Preferences"))
        self._title_lbl.setObjectName("page_title")
        self._sub_lbl = QLabel(_("Configure sync behavior and browser data sources"))
        self._sub_lbl.setObjectName("page_subtitle")
        title_col.addWidget(self._title_lbl)
        title_col.addWidget(self._sub_lbl)

        self._save_btn = QPushButton(_("Save Settings"))
        self._save_btn.setObjectName("primary_btn")
        self._save_btn.setMinimumWidth(120)
        self._save_btn.setFixedHeight(36)
        self._save_btn.setIcon(get_icon("database"))
        self._save_btn.clicked.connect(self._save)

        self._status_label = QLabel("")
        self._status_label.setObjectName("muted")

        h_layout.addLayout(title_col)
        h_layout.addStretch()
        h_layout.addWidget(self._status_label)
        h_layout.addSpacing(12)
        h_layout.addWidget(self._save_btn)
        return header_w

    def _add_card(self, title: str, section_widget: QWidget):
        """Wrap *section_widget* in a titled card frame."""
        self._content_layout.addWidget(SectionHeader(title))
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(section_widget)
        self._content_layout.addWidget(frame)

    # ── Data binding ──────────────────────────────────────────

    def _load_config(self):
        cfg = self._vm.get_config()

        # Language
        self._sec_language.load(
            self._vm.get_available_languages(),
            self._vm.get_current_language(),
        )
        self._sec_language.combo.currentIndexChanged.connect(self._on_language_changed)

        # Scheduler
        self._sec_scheduler.load(cfg)
        self._sec_scheduler.auto_sync_cb.stateChanged.connect(self._update_countdowns)
        self._sec_scheduler.interval_spin.valueChanged.connect(self._update_countdowns)

        # Startup
        from src.services.scheduler import StartupManager

        self._sec_startup.load(StartupManager.is_enabled())

        # WebDAV
        self._sec_webdav.load(cfg)
        self._sec_webdav.action_requested.connect(self._on_webdav_action_requested)
        self._sec_webdav.scheduled_cb.stateChanged.connect(self._update_countdowns)
        self._sec_webdav.backup_interval_spin.valueChanged.connect(self._update_countdowns)
        self._sec_webdav.enabled_cb.stateChanged.connect(self._update_countdowns)

        # Privacy
        self._sec_privacy.refresh_blacklist(cfg.privacy.blacklisted_domains)
        self._sec_privacy.refresh_hidden_count(len(self._vm._main_vm.get_hidden_ids()))
        self._sec_privacy.add_domain_requested.connect(self._on_add_blacklist_domain)
        self._sec_privacy.remove_domain_requested.connect(self._on_remove_blacklist_domain)
        self._sec_privacy.clear_hidden_requested.connect(self._on_clear_hidden)

        # Custom paths
        self._sec_paths.refresh_paths(cfg.extractor.custom_paths)
        self._sec_paths.add_path_requested.connect(self._on_add_custom_path)
        self._sec_paths.remove_path_requested.connect(self._on_remove_custom_path)

        # Import
        self._sec_import.import_requested.connect(self._open_import_dialog)

        # Maintenance section
        self._sec_maint.vacuum_requested.connect(lambda: self._run_maintenance("vacuum"))
        self._sec_maint.normalize_domains_requested.connect(lambda: self._run_maintenance("normalize_domains"))
        self._sec_maint.rebuild_fts_requested.connect(lambda: self._run_maintenance("rebuild_fts"))
        self._sec_maint.export_requested.connect(self._open_export_dialog)
        self._sec_maint.full_resync_requested.connect(self._on_full_resync_requested)
        self._refresh_db_stats()

        # Security
        self._sec_security.load(cfg.master_password_hash)
        self._sec_security.password_changed.connect(self._on_master_password_changed)
        self._sec_security.lock_session_requested.connect(self._on_session_locked)

        self._compute_next_times()
        self._update_countdowns()

    def _save(self):
        # ── 主密码保护 ────────────────────────────────────────
        from src.views.master_password_dialog import require_master_password

        cfg = self._vm.get_config()
        if not require_master_password(cfg.master_password_hash, self):
            return

        self.setFocus()

        cfg.scheduler.auto_sync_enabled = self._sec_scheduler.get_auto_sync_enabled()
        cfg.scheduler.sync_interval_hours = self._sec_scheduler.get_interval_hours()
        cfg.scheduler.auto_backup_enabled = self._sec_webdav.get_scheduled_backup_enabled()
        cfg.scheduler.auto_backup_interval_hours = self._sec_webdav.get_backup_interval_hours()
        cfg.webdav = self._sec_webdav.get_webdav_config()

        from src.services.scheduler import StartupManager

        want_startup = self._sec_startup.get_launch_on_startup()
        if want_startup != StartupManager.is_enabled():
            ok = StartupManager.enable(sys.executable) if want_startup else StartupManager.disable()
            if ok:
                cfg.scheduler.launch_on_startup = want_startup
                self._sec_startup.set_status(
                    _("✓ Startup enabled") if want_startup else _("✓ Startup disabled"),
                    "success",
                )
            else:
                # Roll back the checkbox to reflect actual system state
                self._sec_startup.load(not want_startup)
                self._sec_startup.set_status(
                    _("⚠ Failed to configure startup — check permissions"),
                    "error",
                )
                self._set_status(_("⚠ Failed to configure startup"), "warning")

        self._vm.save(cfg)
        self._compute_next_times()
        self._update_countdowns()

    # ── Countdown ─────────────────────────────────────────────

    def _compute_next_times(self):
        cfg = self._vm.get_config()
        last_sync = cfg.last_sync_ts or None
        if last_sync is None:
            try:
                last_sync = self._vm._main_vm._db.get_last_sync_time()
            except Exception:
                last_sync = None
        self._next_sync_ts = compute_next_sync_ts(cfg, last_sync)
        self._next_backup_ts = compute_next_backup_ts(cfg)

    def _update_countdowns(self):
        now = int(time.time())
        min_delta = None

        if self._sec_scheduler.get_auto_sync_enabled() and self._next_sync_ts:
            delta = self._next_sync_ts - now
            text = fmt_countdown(delta)
            self._sec_scheduler.set_next_sync_text(
                _("⏰ Next sync in: {t}").format(t=text) if text else _("⏰ Next sync: due soon")
            )
            if text and (min_delta is None or delta < min_delta):
                min_delta = delta
        else:
            self._sec_scheduler.set_next_sync_text("")

        if self._sec_webdav.get_scheduled_backup_enabled() and self._sec_webdav.is_enabled() and self._next_backup_ts:
            delta = self._next_backup_ts - now
            text = fmt_countdown(delta)
            self._sec_webdav.set_next_backup_text(
                _("⏰ Next backup in: {t}").format(t=text) if text else _("⏰ Next backup: due soon")
            )
            if text and (min_delta is None or delta < min_delta):
                min_delta = delta
        else:
            self._sec_webdav.set_next_backup_text("")

        new_interval = 1000 if (min_delta is not None and min_delta < 60) else 30_000
        if self._countdown_timer.interval() != new_interval:
            self._countdown_timer.setInterval(new_interval)

    # ── Signal wiring ─────────────────────────────────────────

    def _connect_signals(self):
        self._vm.saved.connect(self._on_saved)
        self._vm.error.connect(self._on_error)
        self._vm.language_change_requested.connect(self._on_language_change_done)
        self._vm.webdav_action_progress.connect(self._sec_webdav.on_action_progress)
        self._vm.webdav_action_finished.connect(self._on_webdav_finished)
        self._vm.maintenance_progress.connect(self._sec_maint.append_log)
        self._vm.maintenance_finished.connect(self._on_maint_finished)

        # Full-resync feedback — hooked directly to main_vm sync signals
        main_vm = self._vm._main_vm
        main_vm.sync_started.connect(self._on_resync_started)
        main_vm.sync_finished.connect(self._on_resync_finished)
        main_vm.sync_error.connect(self._on_resync_error)

    def _apply_wheel_event_filter(self):
        for widget in self.findChildren(QComboBox) + self.findChildren(QSpinBox):
            widget.setFocusPolicy(Qt.StrongFocus)
            original = widget.wheelEvent

            def _filtered(event, w=widget, orig=original):
                orig(event) if w.hasFocus() else event.ignore()

            widget.wheelEvent = _filtered

    # ── WebDAV handlers ───────────────────────────────────────

    def _on_webdav_action_requested(self, action: str):
        if action == "restore":
            reply = QMessageBox.warning(
                self,
                _("Restore Database"),
                _(
                    "This will overwrite your current local history database with the one from WebDAV. "
                    "Are you sure you want to continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.setFocus()
        self._sec_webdav.set_action_buttons_enabled(False)
        self._sec_webdav.set_status(_("Starting..."), "muted")
        self._vm.run_webdav_action(action, self._sec_webdav.get_webdav_config())

    def _on_webdav_finished(self, action: str, success: bool, msg: str):
        hash_info = getattr(self._vm, "_last_hash_info", None)
        backups = getattr(self._vm, "_last_backup_list", []) if action == "list_backups" else None
        self._sec_webdav.on_action_finished(action, success, msg, hash_info, backups)

    # ── Language handlers ─────────────────────────────────────

    def _on_language_changed(self, _index: int):
        new_code = self._sec_language.get_selected_code()
        if new_code and new_code != self._vm.get_current_language():
            self._vm.change_language(new_code)

    def _on_language_change_done(self, _lang_code: str):
        self._sec_language.show_restart_note()

    # ── Security handlers ─────────────────────────────────────

    def _on_master_password_changed(self, new_hash: str):
        cfg = self._vm.get_config()
        cfg.master_password_hash = new_hash
        try:
            cfg.save()
        except Exception as exc:
            log.warning("Failed to save master password hash: %s", exc)
        self._set_status(
            _("Master password updated") if new_hash else _("Master password removed"),
            "success",
        )

    def reload_security(self) -> None:
        """Re-load the security section from the live config.

        Call this after any out-of-band change to master_password_hash
        (e.g. the first-run wizard) so the UI reflects the new state.
        """
        cfg = self._vm.get_config()
        self._sec_security.load(cfg.master_password_hash)

    def _on_session_locked(self):
        self._set_status(_("Session locked"), "muted")

    # ── Privacy handlers ──────────────────────────────────────

    def _on_add_blacklist_domain(self, domain: str):
        from src.views.master_password_dialog import require_master_password

        cfg = self._vm.get_config()
        if not require_master_password(cfg.master_password_hash, self):
            return
        if domain not in cfg.privacy.blacklisted_domains:
            cfg.privacy.blacklisted_domains.append(domain)
            self._vm.save(cfg)
            try:
                deleted = self._vm._main_vm._db.delete_records_by_domain(domain)
                log.info("Blacklisted %s, deleted %d records", domain, deleted)
            except Exception as exc:
                log.warning("Failed to delete blacklisted domain records: %s", exc)
        self._sec_privacy.clear_domain_input()
        self._sec_privacy.refresh_blacklist(cfg.privacy.blacklisted_domains)

    def _on_remove_blacklist_domain(self, domain: str):
        from src.views.master_password_dialog import require_master_password

        cfg = self._vm.get_config()
        if not require_master_password(cfg.master_password_hash, self):
            return
        if domain in cfg.privacy.blacklisted_domains:
            cfg.privacy.blacklisted_domains.remove(domain)
        self._vm.save(cfg)
        self._sec_privacy.refresh_blacklist(cfg.privacy.blacklisted_domains)

    def _on_clear_hidden(self):
        from src.views.master_password_dialog import require_master_password

        cfg = self._vm.get_config()
        if not require_master_password(cfg.master_password_hash, self):
            return
        self._vm._main_vm._db.clear_hidden_records()
        self._vm._main_vm.history_vm.set_hidden_ids(set())
        self._sec_privacy.refresh_hidden_count(0)
        self._set_status(_("All records unhidden"), "success")

    # ── Custom paths handlers ─────────────────────────────────

    def _on_add_custom_path(self, browser_type: str, path: str):
        cfg = self._vm.get_config()
        cfg.extractor.custom_paths[browser_type] = path
        self._vm.save(cfg)
        self._sec_paths.refresh_paths(cfg.extractor.custom_paths)

    def _on_remove_custom_path(self, browser_type: str):
        cfg = self._vm.get_config()
        cfg.extractor.custom_paths.pop(browser_type, None)
        self._vm.save(cfg)
        self._sec_paths.refresh_paths(cfg.extractor.custom_paths)

    # ── Import handler ────────────────────────────────────────

    def _open_import_dialog(self):
        try:
            from src.services.db_importer import DatabaseImporter
            from src.viewmodels.import_viewmodel import ImportViewModel
            from src.views.import_dialog import ImportDialog

            db = self._vm._main_vm._db
            importer = DatabaseImporter(db)
            import_vm = ImportViewModel(db, self)
            dlg = ImportDialog(import_vm, importer, self)
            dlg.import_finished.connect(self._on_import_finished)
            dlg.exec()
        except Exception as exc:
            log.error("Failed to open import dialog: %s", exc, exc_info=True)
            QMessageBox.critical(self, _("Error"), str(exc))

    def _on_import_finished(self, inserted: int):
        self._set_status(_("Import complete: {n} new records added.").format(n=inserted), "success")

    # ── VM signal handlers ────────────────────────────────────

    def _on_saved(self):
        self._set_status(_("✓ Saved"), "success")
        self.saved.emit()

    def _on_error(self, msg: str):
        self._set_status(_("✗ Save failed: {msg}").format(msg=msg), "error")

    def _set_status(self, text: str, kind: str = "muted"):
        self._status_label.setObjectName(kind)
        self._status_label.setText(text)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    # ── DB Maintenance handlers ──────────────────────────────

    def _refresh_db_stats(self):
        try:
            stats = self._vm.get_db_stats()
            self._sec_maint.refresh_stats(stats)
        except Exception as exc:
            log.warning("Failed to load DB stats: %s", exc)

    def _run_maintenance(self, operation: str):
        self._sec_maint.set_running(True)
        self._vm.run_db_maintenance(operation)

    def _on_maint_finished(self, operation: str, success: bool, saved_bytes: int):
        self._sec_maint.set_running(False)
        self._sec_maint.set_result(saved_bytes)
        self._refresh_db_stats()
        if success:
            op_labels = {
                "vacuum": _("Vacuum complete"),
                "normalize_domains": _("Domain normalisation complete"),
                "rebuild_fts": _("FTS rebuild complete"),
            }
            label = op_labels.get(operation, _("Operation complete"))
            if operation == "vacuum" and saved_bytes > 0:
                mb = saved_bytes / 1024 / 1024
                self._set_status(_(f"✓ {label} — saved {mb:.1f} MB"), "success")
            else:
                self._set_status(f"✓ {label}", "success")
        else:
            self._set_status(_("✗ Maintenance failed — check log"), "error")

    # ── Full-resync handlers ──────────────────────────────────

    def _on_full_resync_requested(self):
        """Confirm with user then kick off a full resync via main_vm."""
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            _("Full Resync"),
            _(
                "This will re-read the complete history from all browser databases\n"
                "and upsert every record, back-filling any fields that were missing\n"
                "No existing records will be deleted. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._resync_running = True
        self._sec_maint.set_resync_running(True)
        self._vm._main_vm.trigger_full_resync()

    def _on_resync_started(self):
        # Only update UI if we initiated the resync from this page
        if getattr(self, "_resync_running", False):
            self._sec_maint.set_resync_running(True)

    def _on_resync_finished(self, new_count: int):
        if not getattr(self, "_resync_running", False):
            return
        self._resync_running = False
        self._sec_maint.set_resync_running(False)
        self._sec_maint.set_resync_done(new_count)
        self._refresh_db_stats()
        self._set_status(
            _("✓ Full resync complete — {n} new records upserted").format(n=f"{new_count:,}"),
            "success",
        )

    def _on_resync_error(self, msg: str):
        if not getattr(self, "_resync_running", False):
            return
        self._resync_running = False
        self._sec_maint.set_resync_running(False)
        self._sec_maint.set_resync_error(msg)
        self._set_status(_("✗ Full resync failed — check log"), "error")

    # ── External API (called from main_window) ────────────────

    def add_blacklist_domain(self, domain: str):
        """Called from history page blacklist action."""
        self._sec_privacy.set_domain_input(domain)
        self._on_add_blacklist_domain(domain)

    def notify_sync_happened(self, last_sync_ts: int):
        """Update next sync countdown after a sync completes."""
        cfg = self._vm.get_config()
        self._next_sync_ts = compute_next_sync_ts(cfg, last_sync_ts)
        self._next_backup_ts = compute_next_backup_ts(cfg)
        self._update_countdowns()

    def notify_backup_happened(self, success: bool):
        """Update next backup countdown after a backup completes."""
        if not success:
            return
        self._next_backup_ts = compute_next_backup_ts(self._vm.get_config())
        self._update_countdowns()

    def _open_export_dialog(self):
        """Entry B: open ExportDialog with no pre-filled filter (export all)."""
        from src.views.export_dialog import ExportDialog

        db = self._vm._main_vm._db
        favicon_cache = None
        try:
            favicon_cache = self._vm._main_vm._favicon_manager._cache
        except AttributeError:
            pass

        dlg = ExportDialog(
            db=db,
            favicon_cache=favicon_cache,
            resolved_params=None,  # Entry B — no pre-existing filter
            parent=self,
        )
        dlg.exec()
