# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.models.app_config import AppConfig
from src.utils.i18n import _
from src.utils.icon_helper import get_browser_pixmap, get_icon
from src.utils.logger import get_logger
from src.views.password_edit import PasswordEdit

log = get_logger("view.first_run_wizard")


def _make_dot_pixmap(color: str, size: int = 10) -> QPixmap:
    """Create a solid circle QPixmap for status indicators."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return px


def _svg_icon_pixmap(name: str, size: int, color: str) -> QPixmap:
    """Render a feather SVG icon as a colored QPixmap."""
    from src.utils.icon_helper import _svg_to_pixmap
    from src.utils.path_helper import get_icons_dir

    path = get_icons_dir() / f"{name}.svg"
    if not path.is_file():
        return QPixmap()
    return _svg_to_pixmap(path, size, color)


class _PageBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def validate(self) -> tuple[bool, str]:
        """Return (ok, error_message). Override to add validation."""
        return True, ""


# ── Page 1: Welcome ────────────────────────────────────────────────────────────


class _WelcomePage(_PageBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.addStretch()

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(64, 64)
        icon_lbl.setAlignment(Qt.AlignCenter)
        px = _svg_icon_pixmap("clock", 52, "#5b9cf6")
        if not px.isNull():
            icon_lbl.setPixmap(px)
        layout.addWidget(icon_lbl, 0, Qt.AlignCenter)

        title = QLabel(_("Welcome to HistorySync"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            _(
                "HistorySync quietly collects your browser history in the background\n"
                "and optionally syncs it to WebDAV cloud storage.\n\n"
                "Let's take a moment to configure the basics."
            )
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 13px; color: #aaa;")
        layout.addWidget(desc)
        layout.addStretch()


# ── Page 2: Browser sync settings ─────────────────────────────────────────────


class _SyncPage(_PageBase):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        px = _svg_icon_pixmap("refresh", 20, "#5b9cf6")
        if not px.isNull():
            icon_lbl.setPixmap(px)
        title_row.addWidget(icon_lbl)
        title = QLabel(_("Browser Sync Settings"))
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(_("Choose whether HistorySync should automatically collect your browser history."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(desc)

        layout.addSpacing(8)

        self._auto_sync_cb = QCheckBox(_("Enable automatic background sync"))
        self._auto_sync_cb.setChecked(config.scheduler.auto_sync_enabled)
        self._auto_sync_cb.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._auto_sync_cb)

        interval_row = QHBoxLayout()
        interval_lbl = QLabel(_("Sync interval:"))
        interval_lbl.setMinimumWidth(140)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 168)
        self._interval_spin.setValue(config.scheduler.sync_interval_hours)
        self._interval_spin.setSuffix(_(" hours"))
        self._interval_spin.setMinimumWidth(100)
        interval_row.addWidget(interval_lbl)
        interval_row.addWidget(self._interval_spin)
        interval_row.addStretch()
        layout.addLayout(interval_row)

        backup_row = QHBoxLayout()
        backup_lbl = QLabel(_("Backup interval:"))
        backup_lbl.setMinimumWidth(140)
        self._backup_spin = QSpinBox()
        self._backup_spin.setRange(1, 720)
        self._backup_spin.setValue(config.scheduler.auto_backup_interval_hours)
        self._backup_spin.setSuffix(_(" hours"))
        self._backup_spin.setMinimumWidth(100)
        backup_row.addWidget(backup_lbl)
        backup_row.addWidget(self._backup_spin)
        backup_row.addStretch()
        layout.addLayout(backup_row)

        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        note_icon = QLabel()
        note_icon.setFixedSize(14, 14)
        note_px = _svg_icon_pixmap("info", 14, "#888")
        if not note_px.isNull():
            note_icon.setPixmap(note_px)
        note_row.addWidget(note_icon)
        startup_note = QLabel(_("You can enable 'Launch on startup' in Settings → Startup later."))
        startup_note.setWordWrap(True)
        startup_note.setStyleSheet("color: #888; font-size: 11px;")
        note_row.addWidget(startup_note, 1)
        layout.addLayout(note_row)

        layout.addStretch()

    def apply(self) -> None:
        self._config.scheduler.auto_sync_enabled = self._auto_sync_cb.isChecked()
        self._config.scheduler.sync_interval_hours = self._interval_spin.value()
        self._config.scheduler.auto_backup_interval_hours = self._backup_spin.value()


# ── Page 3: Browser sync selection ────────────────────────────────────────────


class _BrowserSyncPage(_PageBase):
    """让用户选择哪些已检测到的浏览器参与同步。"""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        px = _svg_icon_pixmap("globe", 20, "#5b9cf6")
        if not px.isNull():
            icon_lbl.setPixmap(px)
        title_row.addWidget(icon_lbl)
        title = QLabel(_("Browser Sync Selection"))
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(
            _(
                "Choose which browsers HistorySync should collect history from.\n"
                "You can change this anytime via right-click on a browser card in the Overview."
            )
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Select-all / select-none buttons row

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 0, 0, 0)
        self._btn_all = QPushButton(_("Select All"))
        self._btn_all.setFixedHeight(30)
        self._btn_all.setStyleSheet("font-size: 12px;")
        self._btn_none = QPushButton(_("Deselect All"))
        self._btn_none.setFixedHeight(30)
        self._btn_none.setStyleSheet("font-size: 12px;")
        btn_row.addWidget(self._btn_all)
        btn_row.addWidget(self._btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Scroll area for browser checkboxes — stretch=1 so it expands with the window
        from PySide6.QtWidgets import QFrame, QScrollArea

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(220)

        inner = QWidget()
        self._cb_layout = QVBoxLayout(inner)
        self._cb_layout.setSpacing(6)
        self._cb_layout.setContentsMargins(0, 4, 0, 4)
        self._cb_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(inner)
        layout.addWidget(scroll)  # no stretch — trailing addStretch absorbs extra height
        layout.addStretch(1)  # all extra wizard-page height absorbed here, items stay compact

        self._checkboxes: dict[str, QCheckBox] = {}
        self._populate_browsers()

        self._btn_all.clicked.connect(self._on_select_all)
        self._btn_none.clicked.connect(self._on_deselect_all)

    def _populate_browsers(self):
        from src.services.browser_defs import BUILTIN_BROWSERS

        disabled = set(self._config.extractor.disabled_browsers)

        # Detect which browsers are actually installed
        detected = {bdef.browser_type for bdef in BUILTIN_BROWSERS if bdef.is_history_available()}

        # Sort: detected browsers first, then undetected, alphabetically within each group
        sorted_browsers = sorted(
            BUILTIN_BROWSERS, key=lambda b: (0 if b.browser_type in detected else 1, b.display_name)
        )

        for bdef in sorted_browsers:
            is_detected = bdef.browser_type in detected
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)

            # Browser icon
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(20, 20)
            icon_lbl.setAlignment(Qt.AlignCenter)
            px = get_browser_pixmap(bdef.browser_type, 20)
            if not px.isNull():
                icon_lbl.setPixmap(px)
            else:
                icon_lbl.setText(bdef.display_name[:1].upper())
            row.addWidget(icon_lbl)

            cb = QCheckBox(bdef.display_name)
            cb.setChecked(bdef.browser_type not in disabled)
            cb.setStyleSheet("font-size: 13px;")
            self._checkboxes[bdef.browser_type] = cb
            row.addWidget(cb, 1)

            # Status dot: green=detected, yellow=not detected
            dot = QLabel()
            dot.setFixedSize(10, 10)
            if is_detected:
                dot.setPixmap(_make_dot_pixmap("#34a853", 10))
                dot.setToolTip(_("Detected"))
            else:
                dot.setPixmap(_make_dot_pixmap("#d29922", 10))
                dot.setToolTip(_("Not detected"))
            row.addWidget(dot)

            self._cb_layout.addLayout(row)

        self._cb_layout.addStretch()  # absorb extra vertical space so items stay compact

    def _on_select_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _on_deselect_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(False)

    def apply(self) -> None:
        disabled = [bt for bt, cb in self._checkboxes.items() if not cb.isChecked()]
        self._config.extractor.disabled_browsers = disabled


# ── Page 4: Master password ────────────────────────────────────────────────────


class _StrengthBar(QWidget):
    """Animated password-strength progress bar with gradient fill."""

    # Colour stops: (score_threshold, hex_color)
    _STOPS = [
        "#e05252",  # 0 - Very weak
        "#e07050",  # 1 - Weak
        "#e0a030",  # 2 - Fair
        "#a0c020",  # 3 - Good
        "#34a853",  # 4 - Strong
    ]
    _LABELS = [
        lambda: _("Very weak"),
        lambda: _("Weak"),
        lambda: _("Fair"),
        lambda: _("Good"),
        lambda: _("Strong"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._score = -1  # -1 = hidden (empty password)
        self.setFixedHeight(28)
        self.setMinimumWidth(120)

    def set_score(self, score: int) -> None:
        """score: -1 (hide) or 0..4"""
        self._score = score
        self.update()

    def paintEvent(self, _event):
        if self._score < 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        bar_h = 6
        bar_y = 2
        radius = bar_h / 2

        # Background track
        painter.setBrush(QColor("#2a2a2a" if self._is_dark() else "#e0e0e0"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, bar_y, w, bar_h, radius, radius)

        # Filled portion — width proportional to (score+1)/5
        fill_w = max(int(w * (self._score + 1) / 5), int(bar_h))
        color = QColor(self._STOPS[self._score])
        painter.setBrush(color)
        painter.drawRoundedRect(0, bar_y, fill_w, bar_h, radius, radius)

        # Label — use full remaining height so text is never clipped
        label_text = self._LABELS[self._score]()
        painter.setPen(color)
        text_y = bar_y + bar_h + 3
        from PySide6.QtCore import QRectF

        painter.drawText(QRectF(0, text_y, w, h - text_y + 2), Qt.AlignLeft | Qt.AlignTop, label_text)

        painter.end()

    @staticmethod
    def _is_dark() -> bool:
        try:
            from src.utils.theme_manager import ThemeManager

            return ThemeManager.instance().current != "light"
        except Exception:
            return True


def _pw_score(text: str) -> int:
    """Linear 0-4 password strength score."""
    if not text:
        return -1
    score = 0
    if len(text) >= 6:
        score += 1
    if len(text) >= 10:
        score += 1
    has_upper = any(c.isupper() for c in text)
    has_digit = any(c.isdigit() for c in text)
    has_special = any(not c.isalnum() for c in text)
    extras = sum([has_upper, has_digit, has_special])
    if extras >= 1:
        score += 1
    if extras >= 2:
        score += 1
    return min(score, 4)


class _MasterPasswordPage(_PageBase):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        px = _svg_icon_pixmap("lock", 20, "#5b9cf6")
        if not px.isNull():
            icon_lbl.setPixmap(px)
        title_row.addWidget(icon_lbl)
        title = QLabel(_("Master Password (Optional)"))
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(
            _(
                "A master password protects sensitive settings such as WebDAV credentials, "
                "sync configuration, and privacy rules. You will be prompted before any protected action.\n\n"
                "Leave blank to skip — you can set one later in Settings → Security."
            )
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(desc)

        layout.addSpacing(8)

        def pw_row(label: str) -> tuple[QHBoxLayout, PasswordEdit]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(140)
            field = PasswordEdit()
            field.setMinimumWidth(220)
            row.addWidget(lbl)
            row.addWidget(field)
            return row, field

        row1, self._pw1 = pw_row(_("New password:"))
        row2, self._pw2 = pw_row(_("Confirm:"))
        layout.addLayout(row1)

        # Strength bar (sits right under pw1, aligned with the input field)
        strength_container = QHBoxLayout()
        strength_container.setContentsMargins(140, 0, 0, 0)  # align with input field (eye btn is inside PasswordEdit)
        self._strength_bar = _StrengthBar()
        strength_container.addWidget(self._strength_bar)
        layout.addLayout(strength_container)

        layout.addLayout(row2)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #e05252; font-size: 12px; margin-left: 144px;")
        layout.addWidget(self._error_lbl)

        self._pw1.textChanged.connect(self._update_strength)

        layout.addStretch()

    def _update_strength(self, text: str) -> None:
        self._strength_bar.set_score(_pw_score(text))

    def validate(self) -> tuple[bool, str]:
        pw1 = self._pw1.text()
        pw2 = self._pw2.text()
        if not pw1 and not pw2:
            return True, ""
        if pw1 != pw2:
            return False, _("Passwords do not match.")
        if len(pw1) < 4:
            return False, _("Password must be at least 4 characters.")
        return True, ""

    def apply(self) -> None:
        from src.utils.master_key_manager import get_session, hash_password

        pw = self._pw1.text()
        if pw:
            self._config.master_password_hash = hash_password(pw)
            get_session().unlock()
            log.info("First-run: master password set")
        else:
            self._config.master_password_hash = ""

    def show_error(self, msg: str) -> None:
        self._error_lbl.setText(msg)


# ── Page 5: Done ───────────────────────────────────────────────────────────────


class _DonePage(_PageBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.addStretch()

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(64, 64)
        icon_lbl.setAlignment(Qt.AlignCenter)
        px = _svg_icon_pixmap("check-circle", 52, "#34a853")
        if not px.isNull():
            icon_lbl.setPixmap(px)
        layout.addWidget(icon_lbl, 0, Qt.AlignCenter)

        title = QLabel(_("All set!"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            _(
                "HistorySync is ready to go.\n\n"
                "You can adjust any of these settings later in the Settings page.\n"
                "The app will run quietly in your system tray."
            )
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 13px; color: #aaa;")
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Sync checkbox
        cb_row = QHBoxLayout()
        cb_row.setContentsMargins(0, 0, 0, 0)
        cb_row.addStretch()
        self._sync_cb = QCheckBox(_("Run initial sync now"))
        self._sync_cb.setChecked(True)
        self._sync_cb.setStyleSheet("font-size: 13px;")
        sync_icon = get_icon("refresh-ccw", 16)
        if not sync_icon.isNull():
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(18, 18)
            icon_lbl.setPixmap(sync_icon.pixmap(16, 16))
            cb_row.addWidget(icon_lbl)
        cb_row.addWidget(self._sync_cb)
        cb_row.addStretch()
        layout.addLayout(cb_row)

        layout.addStretch()

    @property
    def should_sync(self) -> bool:
        return self._sync_cb.isChecked()


# ── Wizard container ───────────────────────────────────────────────────────────


class FirstRunWizard(QDialog):
    """Multi-page first-run setup wizard."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._trigger_initial_sync = False
        self.setWindowTitle(_("HistorySync — First-Time Setup"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(520, 420)
        self.setMaximumHeight(520)
        self.resize(520, 460)
        self._build_ui()

    @property
    def should_sync_on_finish(self) -> bool:
        """True if user checked 'Run initial sync now' on the Done page."""
        return self._trigger_initial_sync

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Progress indicator (5 steps)
        self._progress_bar = _ProgressIndicator(5, self)
        root.addWidget(self._progress_bar)

        # Page stack
        self._stack = QStackedWidget()
        self._page_welcome = _WelcomePage()
        self._page_sync = _SyncPage(self._config)
        self._page_browser_sync = _BrowserSyncPage(self._config)
        self._page_password = _MasterPasswordPage(self._config)
        self._page_done = _DonePage()

        for page in (
            self._page_welcome,
            self._page_sync,
            self._page_browser_sync,
            self._page_password,
            self._page_done,
        ):
            self._stack.addWidget(page)

        root.addWidget(self._stack, 1)

        # Navigation buttons
        nav = QHBoxLayout()
        nav.setContentsMargins(20, 12, 20, 16)
        nav.setSpacing(8)

        self._skip_btn = QPushButton(_("Skip Setup"))
        self._skip_btn.setObjectName("muted")
        self._skip_btn.clicked.connect(self._on_skip)

        self._back_btn = QPushButton(_("Back"))
        self._back_btn.setIcon(get_icon("chevron-left", 16))
        self._back_btn.setVisible(False)
        self._back_btn.clicked.connect(self._go_back)

        self._next_btn = QPushButton(_("Next"))
        self._next_btn.setLayoutDirection(Qt.RightToLeft)
        self._next_btn.setIcon(get_icon("chevron-right", 16))
        self._next_btn.setObjectName("primary_btn")
        self._next_btn.clicked.connect(self._go_next)

        nav.addWidget(self._skip_btn)
        nav.addStretch()
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        self._update_nav()

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _current_index(self) -> int:
        return self._stack.currentIndex()

    def _go_next(self) -> None:
        idx = self._current_index()
        page = self._stack.currentWidget()

        if hasattr(page, "validate"):
            ok, err = page.validate()
            if not ok:
                if hasattr(page, "show_error"):
                    page.show_error(err)
                return

        if hasattr(page, "apply"):
            page.apply()

        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._progress_bar.set_step(idx + 1)
            self._update_nav()
        else:
            self._finish()

    def _go_back(self) -> None:
        idx = self._current_index()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._progress_bar.set_step(idx - 1)
            self._update_nav()

    def _update_nav(self) -> None:
        idx = self._current_index()
        last = self._stack.count() - 1

        self._back_btn.setVisible(idx > 0)
        self._skip_btn.setVisible(idx < last)

        if idx == last:
            self._next_btn.setText(_("Get Started"))
            self._next_btn.setIcon(get_icon("play", 16))
        elif idx == last - 1:
            self._next_btn.setText(_("Finish"))
            self._next_btn.setIcon(get_icon("check-circle", 16))
        else:
            self._next_btn.setText(_("Next"))
            self._next_btn.setIcon(get_icon("chevron-right", 16))

    def _on_skip(self) -> None:
        reply = QMessageBox.question(
            self,
            _("Skip Setup?"),
            _(
                "Are you sure you want to skip setup?\n\n"
                "HistorySync will use default settings. You can configure everything later in the Settings page."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._config.first_run_completed = True
        try:
            self._config.save()
        except Exception as exc:
            log.warning("First-run skip: save failed: %s", exc)
        log.info("First-run wizard: skipped")
        self.reject()

    def _finish(self) -> None:
        self._trigger_initial_sync = self._page_done.should_sync
        self._config.first_run_completed = True
        try:
            self._config.save()
        except Exception as exc:
            log.warning("First-run finish: save failed: %s", exc)
        log.info("First-run wizard: completed (initial_sync=%s)", self._trigger_initial_sync)
        self.accept()


# ── Step progress indicator widget ────────────────────────────────────────────


class _ProgressIndicator(QWidget):
    def __init__(self, steps: int, parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = 0
        self.setFixedHeight(44)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(0)

        labels = [
            _("Welcome"),
            _("Sync"),
            _("Browsers"),
            _("Security"),
            _("Done"),
        ]
        self._dots: list[QLabel] = []
        for i in range(self._steps):
            dot = QLabel("●" if i == 0 else "○")
            dot.setFixedWidth(24)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("font-size:14px; color: #4a90e2;" if i == 0 else "font-size:14px; color: #555;")
            layout.addWidget(dot)
            self._dots.append(dot)

            if i < self._steps - 1:
                line = QLabel("──")
                line.setStyleSheet("color: #555; font-size: 11px;")
                layout.addWidget(line)

        layout.addStretch()

        step_lbl = QLabel(" · ".join(labels))
        step_lbl.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(step_lbl)

    def set_step(self, step: int) -> None:
        self._current = step
        for i, dot in enumerate(self._dots):
            if i < step:
                dot.setText("●")
                dot.setStyleSheet("font-size:14px; color: #34a853;")
            elif i == step:
                dot.setText("●")
                dot.setStyleSheet("font-size:14px; color: #4a90e2;")
            else:
                dot.setText("○")
                dot.setStyleSheet("font-size:14px; color: #555;")
