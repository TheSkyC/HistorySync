# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.models.app_config import FontConfig
from src.utils.i18n import _
from src.utils.icon_helper import get_icon, get_themed_icon

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_families(raw: str) -> list[str]:
    return [f.strip().strip("'\"") for f in raw.split(",") if f.strip()]


def _join_families(families: list[str]) -> str:
    return ", ".join(families)


def _summary(cfg: FontConfig) -> str:
    """One-line human-readable description shown in the slim card."""
    if not cfg.enabled:
        return _("Using built-in defaults")
    first_ui = (_parse_families(cfg.ui_family) or ["?"])[0]
    first_mono = (_parse_families(cfg.mono_family) or ["?"])[0]
    return _("UI: {ui} {ups}px  ·  Mono: {mono} {mps}px").format(
        ui=first_ui, ups=cfg.ui_size, mono=first_mono, mps=cfg.mono_size
    )


# ─────────────────────────────────────────────────────────────────────────────
# FontPickerWidget
# ─────────────────────────────────────────────────────────────────────────────


class FontPickerWidget(QWidget):
    """Ordered font-fallback list with size spinbox and live preview.

    Parameters
    ----------
    title           Section heading shown above the widget.
    initial_family  Comma-separated fallback list, e.g. ``"Segoe UI, Arial"``.
    initial_size    Font size in **pixels** (QSS px units).
    """

    font_changed = Signal()

    def __init__(self, title: str, initial_family: str, initial_size: int, parent=None):
        super().__init__(parent)
        self._families: list[str] = _parse_families(initial_family)
        self._title = title
        self._init_size = initial_size
        self._setup_ui()
        self._refresh_list()
        self._update_preview()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        lbl = QLabel(self._title)
        lbl.setObjectName("stat_label")
        root.addWidget(lbl)

        # Add-font row
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        self._combo = QFontComboBox()
        self._combo.setEditable(False)
        self._combo.setFontFilters(QFontComboBox.AllFonts)
        self._combo.setMinimumWidth(200)
        self._add_btn = QPushButton(_("Add"))
        self._add_btn.setObjectName("primary_btn")
        self._add_btn.setMinimumHeight(28)
        self._add_btn.setMinimumWidth(64)
        self._add_btn.clicked.connect(self._add_font)
        add_row.addWidget(QLabel(_("Font:")))
        add_row.addWidget(self._combo, 1)
        add_row.addWidget(self._add_btn)
        root.addLayout(add_row)

        # List + reorder/delete buttons
        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget()
        self._list.setMaximumHeight(96)
        self._list.setToolTip(_("Fonts are tried in order. The first one that supports a character is used."))
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.setStyleSheet(
            "QListWidget { border: 1px solid #3a3d4a; border-radius: 4px; outline: 0; }"
            "QListWidget::item { padding: 3px 8px; }"
            "QListWidget::item:selected { background-color: #2d5a9e; color: #fff; }"
        )

        btns = QVBoxLayout()
        btns.setSpacing(4)
        self._up_btn = QPushButton()
        self._up_btn.setIcon(get_themed_icon("chevron-up", 14))
        self._up_btn.setFixedSize(28, 28)
        self._up_btn.setObjectName("icon_btn")
        self._up_btn.setToolTip(_("Move Up — higher priority"))

        self._down_btn = QPushButton()
        self._down_btn.setIcon(get_themed_icon("chevron-down", 14))
        self._down_btn.setFixedSize(28, 28)
        self._down_btn.setObjectName("icon_btn")
        self._down_btn.setToolTip(_("Move Down — lower priority"))

        self._del_btn = QPushButton()
        self._del_btn.setIcon(get_icon("trash-2", 14, "#f87171"))
        self._del_btn.setFixedSize(28, 28)
        self._del_btn.setObjectName("icon_btn")
        self._del_btn.setToolTip(_("Remove"))
        self._up_btn.clicked.connect(self._move_up)
        self._down_btn.clicked.connect(self._move_down)
        self._del_btn.clicked.connect(self._remove_font)
        btns.addWidget(self._up_btn)
        btns.addWidget(self._down_btn)
        btns.addWidget(self._del_btn)
        btns.addStretch()

        mid_row.addWidget(self._list, 1)
        mid_row.addLayout(btns)
        root.addLayout(mid_row)

        # Size row
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        self._size_spin = QSpinBox()
        self._size_spin.setRange(8, 32)
        self._size_spin.setValue(self._init_size)
        self._size_spin.setSuffix(" px")
        self._size_spin.setFixedWidth(80)
        self._size_spin.valueChanged.connect(self._on_changed)
        size_row.addWidget(QLabel(_("Size:")))
        size_row.addWidget(self._size_spin)
        size_row.addStretch()
        root.addLayout(size_row)

        # Live preview
        self._preview = QLabel("Preview  预览  한국어  日本語  123 ABCabc")
        self._preview.setMinimumHeight(44)
        self._preview.setAlignment(Qt.AlignCenter)
        root.addWidget(self._preview)

        self._on_selection_changed(-1)

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self):
        self._list.blockSignals(True)
        self._list.clear()
        for f in self._families:
            self._list.addItem(QListWidgetItem(f))
        self._list.blockSignals(False)

    def _add_font(self):
        family = self._combo.currentFont().family()
        if family in self._families:
            return
        self._families.append(family)
        self._refresh_list()
        self._list.setCurrentRow(len(self._families) - 1)
        self._on_changed()

    def _remove_font(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._families.pop(row)
        self._refresh_list()
        new = min(row, len(self._families) - 1)
        if new >= 0:
            self._list.setCurrentRow(new)
        self._on_changed()

    def _move_up(self):
        row = self._list.currentRow()
        if row > 0:
            self._families[row - 1], self._families[row] = self._families[row], self._families[row - 1]
            self._refresh_list()
            self._list.setCurrentRow(row - 1)
            self._on_changed()

    def _move_down(self):
        row = self._list.currentRow()
        if row < len(self._families) - 1:
            self._families[row], self._families[row + 1] = self._families[row + 1], self._families[row]
            self._refresh_list()
            self._list.setCurrentRow(row + 1)
            self._on_changed()

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_selection_changed(self, row: int):
        n = len(self._families)
        has = row >= 0
        self._del_btn.setEnabled(has)
        self._up_btn.setEnabled(has and row > 0)
        self._down_btn.setEnabled(has and row < n - 1)

    def _on_changed(self):
        self._update_preview()
        self.font_changed.emit()

    def _update_preview(self):
        size_px = self._size_spin.value()
        # 用 QSS 设置字体，避免 setFont() 被 stylesheet 引擎覆盖的 Qt 已知问题
        families = ", ".join(f'"{f}"' for f in self._families) if self._families else "inherit"
        self._preview.setStyleSheet(
            f"border: 1px solid #3a3d4a; border-radius: 4px; padding: 4px;"
            f"font-family: {families}; font-size: {size_px}px;"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_family_str(self) -> str:
        return _join_families(self._families)

    def get_size_px(self) -> int:
        return self._size_spin.value()

    def set_data(self, family_str: str, size_px: int):
        self._families = _parse_families(family_str)
        self._refresh_list()
        self._size_spin.blockSignals(True)
        self._size_spin.setValue(size_px)
        self._size_spin.blockSignals(False)
        self._update_preview()

    def set_interactive(self, enabled: bool):
        self._combo.setEnabled(enabled)
        self._add_btn.setEnabled(enabled)
        self._list.setEnabled(enabled)
        self._size_spin.setEnabled(enabled)
        if enabled:
            self._on_selection_changed(self._list.currentRow())
        else:
            self._del_btn.setEnabled(False)
            self._up_btn.setEnabled(False)
            self._down_btn.setEnabled(False)


# ─────────────────────────────────────────────────────────────────────────────
# FontDialog
# ─────────────────────────────────────────────────────────────────────────────


class FontDialog(QDialog):
    """Full-featured font settings dialog.

    Open with ``exec()``.  After it returns ``Accepted``, read the result via
    ``get_font_config()``.

    If the user clicked "Apply Now" and then "Cancel", the previous font is
    restored automatically via FontManager.
    """

    _DEFAULT_UI_FAMILY = "Segoe UI, PingFang SC, Microsoft YaHei, Noto Sans CJK SC"
    _DEFAULT_UI_SIZE = 13
    _DEFAULT_MONO_FAMILY = "Consolas, Courier New, monospace"
    _DEFAULT_MONO_SIZE = 11

    def __init__(self, font_cfg: FontConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Font Settings"))
        self.setModal(True)
        self.resize(520, 640)
        self.setMinimumWidth(480)

        self._setup_ui(font_cfg)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self, cfg: FontConfig):
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(24, 20, 24, 20)

        # Enable checkbox
        self._enable_cb = QCheckBox(_("Enable custom fonts"))
        self._enable_cb.setChecked(cfg.enabled)
        self._enable_cb.toggled.connect(self._on_toggle)
        root.addWidget(self._enable_cb)

        note = QLabel(
            _(
                "Override the built-in UI typeface and the monospace font used in "
                "the log viewer.  Add multiple families as fallbacks — if a character "
                "isn't in the first font, the next one is tried automatically."
            )
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Pickers
        self._ui_picker = FontPickerWidget(
            title=_("Interface Font"),
            initial_family=cfg.ui_family,
            initial_size=cfg.ui_size,
        )
        root.addWidget(self._ui_picker)

        root.addSpacing(6)

        self._mono_picker = FontPickerWidget(
            title=_("Monospace Font  (log viewer)"),
            initial_family=cfg.mono_family,
            initial_size=cfg.mono_size,
        )
        root.addWidget(self._mono_picker)

        # ── 预览 label 各自独立更新，不全局应用 ──────────────────────────────
        # 字体变化只刷新对话框内对应的预览框，点 OK 后才全局生效。
        # 这样两个预览框互不干扰，也不会在取消时需要回滚。
        self._ui_picker.font_changed.connect(lambda: None)  # 内部已自行刷新
        self._mono_picker.font_changed.connect(lambda: None)

        root.addStretch()

        # Bottom button row: [Reset Defaults]  <stretch>  [OK] [Cancel]
        btn_row = QHBoxLayout()

        self._reset_btn = QPushButton(_("Reset Defaults"))
        self._reset_btn.setMinimumHeight(32)
        self._reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self._reset_btn)

        btn_row.addStretch()

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self._on_cancel)
        btn_row.addWidget(box)

        root.addLayout(btn_row)

        # Set initial interactive state
        self._on_toggle(cfg.enabled)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_toggle(self, enabled: bool):
        self._ui_picker.set_interactive(enabled)
        self._mono_picker.set_interactive(enabled)
        self._reset_btn.setEnabled(enabled)

    def _on_ok(self):
        from src.utils.font_manager import FontManager

        FontManager.instance().apply(self.get_font_config())
        self.accept()

    def _on_cancel(self):
        self.reject()

    def _reset_defaults(self):
        self._ui_picker.set_data(self._DEFAULT_UI_FAMILY, self._DEFAULT_UI_SIZE)
        self._mono_picker.set_data(self._DEFAULT_MONO_FAMILY, self._DEFAULT_MONO_SIZE)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_font_config(self) -> FontConfig:
        return FontConfig(
            enabled=self._enable_cb.isChecked(),
            ui_family=self._ui_picker.get_family_str(),
            ui_size=self._ui_picker.get_size_px(),
            mono_family=self._mono_picker.get_family_str(),
            mono_size=self._mono_picker.get_size_px(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# FontSection  (slim one-row settings-page card)
# ─────────────────────────────────────────────────────────────────────────────


class FontSection(QWidget):
    """Compact one-row card for the Settings page.

    Displays the current font state and opens FontDialog when the user clicks
    "Configure Fonts…".

    Public API
    ----------
    load(font_cfg)      Populate from a saved FontConfig.
    get_font_config()   Return the last accepted FontConfig (used by _save).
    """

    font_config_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = FontConfig()
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(2)

        title_lbl = QLabel(_("Custom Fonts"))
        title_lbl.setObjectName("stat_label")
        info.addWidget(title_lbl)

        self._status_lbl = QLabel(_("Using built-in defaults"))
        self._status_lbl.setObjectName("muted")
        info.addWidget(self._status_lbl)

        layout.addLayout(info, 1)

        self._open_btn = QPushButton(_("Configure Fonts…"))
        self._open_btn.setMinimumHeight(32)
        self._open_btn.setMinimumWidth(160)
        self._open_btn.clicked.connect(self._open_dialog)
        layout.addWidget(self._open_btn)

    def _open_dialog(self):
        dlg = FontDialog(self._cfg, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._cfg = dlg.get_font_config()
            self._refresh_status()
            self.font_config_changed.emit()

    def _refresh_status(self):
        self._status_lbl.setText(_summary(self._cfg))

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, font_cfg: FontConfig):
        self._cfg = FontConfig(
            enabled=font_cfg.enabled,
            ui_family=font_cfg.ui_family,
            ui_size=font_cfg.ui_size,
            mono_family=font_cfg.mono_family,
            mono_size=font_cfg.mono_size,
        )
        self._refresh_status()

    def get_font_config(self) -> FontConfig:
        return self._cfg
