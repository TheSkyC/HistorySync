# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import DEFAULT_GLOBAL_HOTKEY, DEFAULT_KEYBINDINGS
from src.utils.i18n import _
from src.utils.icon_helper import get_icon
from src.utils.theme_manager import ThemeManager
from src.views.settings._label_utils import constrain_label_width

# ── Shortcut scope map ────────────────────────────────────────────────────────
# Each action key is assigned to a scope that reflects where its QShortcut lives
# at runtime.  Two shortcuts are a *true conflict* only when they would compete
# for the same key event at the same time:
#   - global shortcuts (MainWindow / WindowShortcut) are active whenever the
#     app window is focused, so they can shadow any page-scoped shortcut.
#   - page-scoped shortcuts (WidgetWithChildrenShortcut) only fire when that
#     specific page widget has focus, so duplicates across *different* pages
#     never actually conflict.
_ACTION_SCOPE: dict[str, str] = {
    "__global_overlay__": "global",
    "goto_dashboard": "global",
    "goto_history": "global",
    "goto_bookmarks": "global",
    "goto_settings": "global",
    "goto_logs": "global",
    "goto_stats": "global",
    "trigger_sync": "global",
    "focus_search": "global",
    "delete_selected": "history",
    "history_open_selected": "history",
    "history_copy_url": "history",
    "history_copy_title_url": "history",
    "history_toggle_bookmark": "history",
    "history_add_note": "history",
    "history_open_export": "history",
    "history_hide_selected": "history",
    "bm_open": "bookmarks",
    "bm_copy_url": "bookmarks",
    "bm_delete": "bookmarks",
    "bm_add_note": "bookmarks",
    "bm_locate": "bookmarks",
    "stats_prev": "stats",
    "stats_next": "stats",
    "settings_save": "settings",
}

_PAGE_SCOPES = {"history", "bookmarks", "stats", "settings"}


def _do_conflict(scope_a: str, scope_b: str) -> bool:
    """Return True if two shortcuts in the given scopes can conflict at runtime.

    Page-scoped shortcuts on *different* pages never conflict because Qt only
    delivers the key event to the widget that currently has focus.  Global
    shortcuts are always active, so they will shadow any page-scoped duplicate.
    """
    if scope_a == scope_b:
        return True
    # Cross-scope conflict only when at least one side is global.
    return scope_a == "global" or scope_b == "global"


# ── Action display names ──────────────────────────────────────────────────────
# N_() is intentionally NOT used here because these labels are evaluated at
# method call time (inside load()), not at module import time.
# Entries with key "__group__" are visual section headers, not real actions.

_APP_ACTIONS: list[tuple[str, str]] = [
    ("__group__", "Navigation"),
    ("goto_dashboard", "Go to Dashboard"),
    ("goto_history", "Go to History"),
    ("goto_bookmarks", "Go to Bookmarks"),
    ("goto_settings", "Go to Settings"),
    ("goto_logs", "Go to Log Viewer"),
    ("goto_stats", "Go to Statistics"),
    ("__group__", "Global Actions"),
    ("trigger_sync", "Trigger Sync"),
    ("focus_search", "Focus Search"),
    ("__group__", "History"),
    ("delete_selected", "Delete Selected"),
    ("history_open_selected", "Open in Browser"),
    ("history_copy_url", "Copy URL"),
    ("history_copy_title_url", "Copy Title + URL"),
    ("history_toggle_bookmark", "Toggle Bookmark"),
    ("history_add_note", "Add / Edit Note"),
    ("history_open_export", "Export…"),
    ("history_hide_selected", "Hide Selected"),
    ("__group__", "Bookmarks"),
    ("bm_open", "Open in Browser"),
    ("bm_copy_url", "Copy URL"),
    ("bm_delete", "Remove Bookmark"),
    ("bm_add_note", "Add / Edit Note"),
    ("bm_locate", "Locate in History"),
    ("__group__", "Statistics"),
    ("stats_prev", "Previous Period"),
    ("stats_next", "Next Period"),
    ("__group__", "Settings"),
    ("settings_save", "Save Settings"),
]


class _KeyCaptureEdit(QWidget):
    """Inline widget that captures a keyboard shortcut.

    Shows the current key sequence as a styled label.  When the user clicks
    it, it enters recording mode and captures the next key combination.
    """

    activationRequested = Signal(object)
    recordingFinished = Signal(object)
    valueChanged = Signal()

    def __init__(self, action_key: str, default_seq: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.action_key = action_key
        self._default_seq = default_seq
        self.current_seq = default_seq
        self.original_seq = default_seq

        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("KeyCaptureEdit")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel(default_seq or _("Not set"))
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._label)

        # Buttons are overlaid children (not in layout) so they don't affect centering
        self._reset_default_btn = QPushButton(self)
        self._reset_default_btn.setFixedSize(20, 20)
        self._reset_default_btn.setToolTip(_("Reset to default shortcut"))
        self._reset_default_btn.setIcon(get_icon("refresh-ccw"))
        self._reset_default_btn.setFlat(True)
        self._reset_default_btn.setCursor(Qt.PointingHandCursor)
        self._reset_default_btn.clicked.connect(self._on_reset_to_default)

        self._clear_btn = QPushButton(self)
        self._clear_btn.setFixedSize(20, 20)
        self._clear_btn.setToolTip(_("Clear shortcut"))
        self._clear_btn.setIcon(get_icon("x-circle"))
        self._clear_btn.setFlat(True)
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)

        # Opacity effects for hover-only button visibility
        self._reset_eff = QGraphicsOpacityEffect(self._reset_default_btn)
        self._reset_eff.setOpacity(0.0)
        self._reset_default_btn.setGraphicsEffect(self._reset_eff)
        self._reset_anim = QPropertyAnimation(self._reset_eff, b"opacity", self)
        self._reset_anim.setDuration(150)
        self._reset_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._clear_eff = QGraphicsOpacityEffect(self._clear_btn)
        self._clear_eff.setOpacity(0.0)
        self._clear_btn.setGraphicsEffect(self._clear_eff)
        self._clear_anim = QPropertyAnimation(self._clear_eff, b"opacity", self)
        self._clear_anim.setDuration(150)
        self._clear_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._hovered = False
        self._has_conflict = False
        self._is_recording = False
        self._is_pressing = False
        self._apply_style()

    # ── Styling ───────────────────────────────────────────────────────────────

    def _is_dark(self) -> bool:
        return ThemeManager.instance().current == "dark"

    def _apply_style(self) -> None:
        dark = self._is_dark()
        if self._has_conflict:
            bg = "#2d1515" if dark else "#fff5f5"
            border = "#ef4444" if dark else "#dc2626"
            color = "#fca5a5" if dark else "#991b1b"
        else:
            bg = "#20232c" if dark else "#ffffff"
            border = "#303540" if dark else "#c8ccd8"
            color = "#d0d4dc" if dark else "#1e2128"
        self.setStyleSheet(
            f"QWidget#KeyCaptureEdit {{ background: {bg}; border: 1px solid {border}; border-radius: 6px; }}"
            f"QLabel {{ background: transparent; border: none; color: {color}; font-size: 12px; padding: 0 46px; }}"
            f"QPushButton {{ background: transparent; border: none; }}"
        )
        self._update_buttons()

    def _apply_recording_style(self) -> None:
        dark = self._is_dark()
        if self._is_pressing:
            bg = "#1e1838" if dark else "#f3e5f5"
            border = "#7c3aed" if dark else "#9333ea"
            color = "#c4b5fd" if dark else "#6b21a8"
        else:
            bg = "#0d2640" if dark else "#e0f2fe"
            border = "#0ea5e9" if dark else "#0284c7"
            color = "#7dd3fc" if dark else "#0369a1"
        self.setStyleSheet(
            f"QWidget#KeyCaptureEdit {{ background: {bg}; border: 2px solid {border}; border-radius: 6px; }}"
            f"QLabel {{ background: transparent; border: none; color: {color}; font-size: 12px; font-weight: bold; padding: 0 46px; }}"
            f"QPushButton {{ background: transparent; border: none; }}"
        )
        # Immediately hide buttons during recording
        self._reset_anim.stop()
        self._reset_eff.setOpacity(0.0)
        self._clear_anim.stop()
        self._clear_eff.setOpacity(0.0)

    def _reposition_buttons(self) -> None:
        btn_y = (self.height() - 20) // 2
        x = self.width() - 4
        x -= 20
        self._clear_btn.move(x, btn_y)
        x -= 22
        self._reset_default_btn.move(x, btn_y)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_buttons()

    def _update_buttons(self) -> None:
        """Animate buttons in/out based on hover state and current seq values."""
        show_reset = self.current_seq != self._default_seq
        show_clear = bool(self.current_seq)
        target = 1.0 if self._hovered else 0.0

        self._reset_default_btn.setVisible(show_reset)
        if show_reset:
            self._reset_anim.stop()
            self._reset_anim.setStartValue(self._reset_eff.opacity())
            self._reset_anim.setEndValue(target)
            self._reset_anim.start()
        else:
            self._reset_anim.stop()
            self._reset_eff.setOpacity(0.0)

        self._clear_btn.setVisible(show_clear)
        if show_clear:
            self._clear_anim.stop()
            self._clear_anim.setStartValue(self._clear_eff.opacity())
            self._clear_anim.setEndValue(target)
            self._clear_anim.start()
        else:
            self._clear_anim.stop()
            self._clear_eff.setOpacity(0.0)

        self._reposition_buttons()

    def enterEvent(self, event) -> None:
        self._hovered = True
        if not self._is_recording:
            self._update_buttons()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        # Check if cursor truly left (not just moved into a child button)
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._hovered = False
            if not self._is_recording:
                self._update_buttons()
        super().leaveEvent(event)

    def set_conflict(self, conflict: bool) -> None:
        """Mark this editor as conflicting with another. Triggers red highlight."""
        if self._has_conflict == conflict:
            return
        self._has_conflict = conflict
        if not self._is_recording:
            self._apply_style()

    # ── Mouse / Focus ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._is_recording:
            self.activationRequested.emit(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def set_recording_state(self, active: bool) -> None:
        if self._is_recording == active:
            return
        self._is_recording = active
        if active:
            self._label.setText(_("Press a key..."))
            self.setFocus()
            self._apply_recording_style()
        else:
            self._is_pressing = False
            self._label.setText(self.current_seq or _("Not set"))
            self.clearFocus()
            self._apply_style()

    def focusOutEvent(self, event):
        if self._is_recording:
            QTimer.singleShot(10, lambda: self.recordingFinished.emit(self))
        super().focusOutEvent(event)

    # ── Key capture ───────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if not self._is_recording:
            return super().keyPressEvent(event)

        key = event.key()
        modifiers = event.modifiers()
        event.accept()

        # Pure modifier press - show live preview
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            self._is_pressing = True
            self._apply_recording_style()
            parts = self._modifier_parts(modifiers)
            if parts:
                self._label.setText("+".join(parts) + "+...")
            return None

        # Escape cancels
        if key == Qt.Key_Escape:
            self._is_pressing = False
            self.recordingFinished.emit(self)
            return None

        # Backspace / Delete clears
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            self._is_pressing = False
            self.current_seq = ""
            self._label.setText("")
            self.recordingFinished.emit(self)
            return None

        # Build the sequence string
        self._is_pressing = True
        self._apply_recording_style()

        parts = self._modifier_parts(modifiers)
        # On Windows, event.key() returns the shifted character for digit keys
        # (e.g. Shift+2 -> Qt.Key_At). Use nativeVirtualKey to get the base key.
        base_key = key
        if sys.platform == "win32" and (modifiers & Qt.ShiftModifier):
            native = event.nativeVirtualKey()
            if native and (0x30 <= native <= 0x39):  # digits 0-9
                base_key = Qt.Key(native)
        key_text = QKeySequence(base_key).toString(QKeySequence.NativeText)
        if not key_text:
            return None
        parts.append(key_text)
        new_seq = "+".join(parts)

        self.current_seq = new_seq
        self._label.setText(new_seq)
        return None

    def keyReleaseEvent(self, event):
        if not self._is_recording:
            return super().keyReleaseEvent(event)
        event.accept()

        if event.key() in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            modifiers = event.modifiers()
            if self._is_pressing and not (
                modifiers & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            ):
                # All modifiers released without a non-modifier key
                self._is_pressing = False
                self._apply_recording_style()
                self._label.setText(self.current_seq or _("Press a key..."))
            return None

        if self._is_pressing:
            self._is_pressing = False
            self.recordingFinished.emit(self)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _modifier_parts(modifiers) -> list[str]:
        parts: list[str] = []
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.MetaModifier:
            parts.append("Meta")
        return parts

    def _on_clear(self) -> None:
        if self._is_recording:
            self.recordingFinished.emit(self)
        self.current_seq = ""
        self._label.setText(_("Not set"))
        self._apply_style()
        self.valueChanged.emit()

    def _on_reset_to_default(self) -> None:
        if self._is_recording:
            self.recordingFinished.emit(self)
        self.current_seq = self._default_seq
        self._label.setText(self._default_seq or _("Not set"))
        self._apply_style()
        self.valueChanged.emit()

    def reset_to_original(self) -> None:
        self.current_seq = self.original_seq
        self._label.setText(self.original_seq or _("Not set"))
        self._apply_style()

    def update_original(self, seq: str) -> None:
        self.original_seq = seq
        self.current_seq = seq
        self._label.setText(seq or _("Not set"))
        self._apply_style()


# ── Dialog ────────────────────────────────────────────────────────────────────


class KeybindingDialog(QDialog):
    """Standalone dialog for customizing all keyboard shortcuts."""

    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(parent)
        self._editors: list[_KeyCaptureEdit] = []
        self._global_editor: _KeyCaptureEdit | None = None
        self._current_active: _KeyCaptureEdit | None = None
        self._accepted_config = None  # set on successful Apply

        self.setWindowTitle(_("Keyboard Shortcuts"))
        self.setModal(True)
        self.resize(520, 560)
        self.setMinimumWidth(460)

        self._build_ui()
        self._load(cfg)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(0)

        # ── Scrollable content ────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(6)

        # ── Global hotkey group ───────────────────────────────
        self._add_group_header(form, _("GLOBAL HOTKEY"))
        hint = QLabel(_("Works system-wide even when the app window is not focused."))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addWidget(hint)
        form.addSpacing(4)

        self._global_editor = _KeyCaptureEdit("__global_overlay__", DEFAULT_GLOBAL_HOTKEY)
        self._global_editor.activationRequested.connect(self._on_activation_requested)
        self._global_editor.recordingFinished.connect(self._on_recording_finished)
        self._global_editor.valueChanged.connect(self._run_conflict_check)
        self._add_row(form, _("Quick Access Overlay"), self._global_editor)

        form.addSpacing(12)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        form.addWidget(sep)
        form.addSpacing(8)

        # ── In-app shortcuts group ────────────────────────────
        self._add_group_header(form, _("IN-APP SHORTCUTS"))
        hint2 = QLabel(_("Only active when the application window is focused."))
        hint2.setObjectName("muted")
        hint2.setWordWrap(True)
        form.addWidget(hint2)
        form.addSpacing(4)

        for entry in _APP_ACTIONS:
            if entry[0] == "__group__":
                # Render a visual sub-group separator
                form.addSpacing(6)
                sub_sep = QFrame()
                sub_sep.setFrameShape(QFrame.HLine)
                sub_sep.setObjectName("keybinding_sub_sep")
                form.addWidget(sub_sep)
                sub_hdr = QLabel(_(entry[1]).upper())
                sub_hdr.setObjectName("muted")
                sub_hdr.setContentsMargins(0, 2, 0, 0)
                form.addWidget(sub_hdr)
                continue
            action_key, display_name = entry
            default_seq = DEFAULT_KEYBINDINGS.get(action_key, "")
            editor = _KeyCaptureEdit(action_key, default_seq)
            editor.activationRequested.connect(self._on_activation_requested)
            editor.recordingFinished.connect(self._on_recording_finished)
            editor.valueChanged.connect(self._run_conflict_check)
            self._editors.append(editor)
            self._add_row(form, _(display_name), editor)

        form.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        root.addSpacing(12)

        # ── Button bar ────────────────────────────────────────
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self._reset_btn = QPushButton(_("Reset to Defaults"))
        self._reset_btn.setObjectName("danger_btn")
        self._reset_btn.clicked.connect(self._on_reset)
        btn_bar.addWidget(self._reset_btn)

        btn_bar.addStretch()

        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        ok_btn = QPushButton(_("Apply"))
        ok_btn.setObjectName("primary_btn")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_apply)
        btn_bar.addWidget(ok_btn)

        root.addLayout(btn_bar)

    @staticmethod
    def _add_group_header(layout: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("stat_label")
        lbl.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(lbl)

    @staticmethod
    def _add_row(layout: QVBoxLayout, label_text: str, editor: _KeyCaptureEdit) -> None:
        row = QHBoxLayout()
        lbl = QLabel(label_text + ":")
        lbl.setMinimumWidth(190)
        row.addWidget(lbl)
        row.addWidget(editor, 1)
        layout.addLayout(row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load(self, cfg) -> None:
        kb = cfg.keybindings
        self._global_editor.update_original(kb.global_overlay)
        for editor in self._editors:
            seq = kb.app.get(editor.action_key, DEFAULT_KEYBINDINGS.get(editor.action_key, ""))
            editor.update_original(seq)
        self._run_conflict_check()

    def get_keybindings_config(self):
        from src.models.app_config import KeybindingsConfig

        app_bindings: dict[str, str] = {}
        for editor in self._editors:
            app_bindings[editor.action_key] = editor.current_seq.strip()
        return KeybindingsConfig(
            app=app_bindings,
            global_overlay=self._global_editor.current_seq.strip(),
        )

    # ── Recording state ───────────────────────────────────────────────────────

    def _on_activation_requested(self, editor: _KeyCaptureEdit) -> None:
        if self._current_active and self._current_active is not editor:
            self._current_active.set_recording_state(False)
        self._current_active = editor
        editor.set_recording_state(True)

    def _on_recording_finished(self, editor: _KeyCaptureEdit) -> None:
        if self._current_active is editor:
            editor.set_recording_state(False)
            self._current_active = None
        self._run_conflict_check()

    def _run_conflict_check(self) -> None:
        """Highlight editors with true runtime conflicts."""
        conflict_keys = {action_key for _seq, action_keys in self._collect_conflicts() for action_key in action_keys}
        for editor in [self._global_editor, *self._editors]:
            editor.set_conflict(bool(editor.current_seq.strip()) and editor.action_key in conflict_keys)

    def _collect_conflicts(self) -> list[tuple[str, list[str]]]:
        """Return all true runtime conflicts grouped by key sequence."""
        all_editors = [self._global_editor, *self._editors]
        seq_map: dict[str, list[tuple[str, str]]] = {}
        for editor in all_editors:
            seq = editor.current_seq.strip()
            if not seq:
                continue
            scope = _ACTION_SCOPE.get(editor.action_key, "global")
            seq_map.setdefault(seq, []).append((editor.action_key, scope))

        conflicts: list[tuple[str, list[str]]] = []
        for seq, entries in seq_map.items():
            conflicting_keys: list[str] = []
            for index, (key_a, scope_a) in enumerate(entries):
                for key_b, scope_b in entries[index + 1 :]:
                    if not _do_conflict(scope_a, scope_b):
                        continue
                    if key_a not in conflicting_keys:
                        conflicting_keys.append(key_a)
                    if key_b not in conflicting_keys:
                        conflicting_keys.append(key_b)
            if conflicting_keys:
                conflicts.append((seq, conflicting_keys))
        return conflicts

    def _show_conflict_dialog(self, conflicts: list[tuple[str, list[str]]]) -> bool:
        """Show all true conflicts and return whether Force Apply was chosen."""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(_("Keybinding Conflict"))
        msg_box.setText(
            _("Found {count} shortcut conflicts. Review them below, or choose Force Apply to save anyway.").format(
                count=len(conflicts)
            )
        )
        msg_box.setInformativeText(self._format_conflict_details(conflicts))

        force_apply_btn = msg_box.addButton(_("Force Apply"), QMessageBox.AcceptRole)
        force_apply_btn.setObjectName("warning_btn")
        cancel_btn = msg_box.addButton(_("Cancel"), QMessageBox.RejectRole)
        msg_box.setDefaultButton(cancel_btn)
        msg_box.exec()
        return msg_box.clickedButton() is force_apply_btn

    def _format_conflict_details(self, conflicts: list[tuple[str, list[str]]]) -> str:
        """Return a readable summary of every conflict group."""
        lines: list[str] = []
        for seq, action_keys in conflicts:
            actions = ", ".join(
                _("{action} [{scope}]").format(
                    action=self._display_name_for(action_key),
                    scope=self._scope_label_for(action_key),
                )
                for action_key in action_keys
            )
            lines.append(_("- {key}: {actions}").format(key=seq, actions=actions))
        return "\n".join(lines)

    # ── Buttons ───────────────────────────────────────────────────────────────

    def _stop_active_recording(self) -> None:
        if self._current_active:
            self._current_active.set_recording_state(False)
            self._current_active = None

    def _on_reset(self) -> None:
        self._stop_active_recording()
        reply = QMessageBox.question(
            self,
            _("Confirm"),
            _("Reset all keybindings to their default settings?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._global_editor.update_original(DEFAULT_GLOBAL_HOTKEY)
            for editor in self._editors:
                editor.update_original(DEFAULT_KEYBINDINGS.get(editor.action_key, ""))
            self._run_conflict_check()

    def _on_apply(self) -> None:
        self._stop_active_recording()
        conflicts = self._collect_conflicts()
        if conflicts:
            if self._show_conflict_dialog(conflicts):
                self._on_force_apply()
            return
        self._accepted_config = self.get_keybindings_config()
        self.accept()

    def _on_force_apply(self) -> None:
        """Save current keybindings even when true conflicts exist.

        At runtime Qt fires the *first* matching shortcut found; global
        shortcuts take precedence over page-scoped ones.
        """
        self._stop_active_recording()
        self._accepted_config = self.get_keybindings_config()
        self.accept()

    @staticmethod
    def _display_name_for(action_key: str) -> str:
        if action_key == "__global_overlay__":
            return _("Quick Access Overlay")
        for key, name in _APP_ACTIONS:
            if key == "__group__":
                continue
            if key == action_key:
                return _(name)
        return action_key

    @staticmethod
    def _scope_label_for(action_key: str) -> str:
        scope = _ACTION_SCOPE.get(action_key, "global")
        if scope == "global":
            return _("Global")
        if scope == "history":
            return _("History")
        if scope == "bookmarks":
            return _("Bookmarks")
        if scope == "stats":
            return _("Statistics")
        if scope == "settings":
            return _("Settings")
        return scope.title()

    # ── Escape / close guard ──────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        # If a capture editor is recording, Escape cancels recording, not dialog.
        if event.key() == Qt.Key_Escape and self._current_active:
            self._stop_active_recording()
            event.accept()
            return
        super().keyPressEvent(event)

    def reject(self) -> None:
        self._stop_active_recording()
        super().reject()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _theme: str) -> None:
        self._global_editor._apply_style()
        for editor in self._editors:
            editor._apply_style()


# ── Compact card section (used in settings page) ──────────────────────────────


class KeybindingSection(QWidget):
    """Compact settings card with a button that opens KeybindingDialog.

    Signals:
        configure_requested()  - emitted when the user clicks Configure
    """

    configure_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(_("Keyboard Shortcuts"))
        title.setObjectName("stat_label")
        self._summary_lbl = constrain_label_width(
            QLabel(_("Customize in-app shortcuts and the global overlay hotkey."))
        )
        self._summary_lbl.setObjectName("muted")
        text_col.addWidget(title)
        text_col.addWidget(self._summary_lbl)
        layout.addLayout(text_col, 1)

        cfg_btn = QPushButton(_("Configure…"))
        cfg_btn.setIcon(get_icon("keyboard"))
        cfg_btn.setMinimumWidth(120)
        cfg_btn.clicked.connect(self.configure_requested)
        layout.addWidget(cfg_btn)
