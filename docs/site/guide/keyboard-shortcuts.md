---
title: Keyboard Shortcuts
description: HistorySync's 25 configurable keyboard shortcuts — one global hotkey and 24 in-app bindings.
---

# Keyboard Shortcuts

HistorySync provides **25 configurable shortcuts** — one global hotkey and 24 in-app bindings. All of them can be changed in **Settings → Keyboard Shortcuts**.

---

## Global Hotkey

This shortcut works system-wide — it fires even when HistorySync is in the background or minimised to the tray.

| Action | Default | Notes |
|---|---|---|
| **Open Quick-Access Overlay** | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | Summons / hides the Spotlight-style search overlay |

!!! info "Linux / Wayland"
    Global hotkeys via `pynput` are **not supported on Wayland**. Use `--quick` with a system-level key binding as a workaround:
    ```bash
    # Bind this command to a system shortcut in your DE settings
    python -m src.main --quick
    ```

!!! info "macOS"
    The first time the global hotkey fires, macOS will ask for **Accessibility** permission. Grant it in **System Settings → Privacy & Security → Accessibility**.

---

## In-App Shortcuts

These shortcuts are active when the HistorySync window is focused.

### Current Defaults

| Category | Defaults |
|---|---|
| **Page navigation** | Dashboard <kbd>Ctrl</kbd>+<kbd>1</kbd>, History <kbd>Ctrl</kbd>+<kbd>2</kbd>, Bookmarks <kbd>Ctrl</kbd>+<kbd>3</kbd>, Settings <kbd>Ctrl</kbd>+<kbd>4</kbd>, Logs <kbd>Ctrl</kbd>+<kbd>5</kbd>, Statistics <kbd>Ctrl</kbd>+<kbd>6</kbd> |
| **Global actions** | Sync now <kbd>Ctrl</kbd>+<kbd>R</kbd>, Focus search <kbd>Ctrl</kbd>+<kbd>F</kbd> |
| **History page** | Open selected <kbd>Enter</kbd>, Delete selected <kbd>Delete</kbd>, Copy URL <kbd>Ctrl</kbd>+<kbd>C</kbd>, Copy title + URL <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>, Toggle bookmark <kbd>Ctrl</kbd>+<kbd>B</kbd>, Add note <kbd>Ctrl</kbd>+<kbd>N</kbd>, Open export <kbd>Ctrl</kbd>+<kbd>E</kbd>, Hide selected unassigned by default |
| **Bookmarks page** | Open <kbd>Enter</kbd>, Copy URL <kbd>Ctrl</kbd>+<kbd>C</kbd>, Delete <kbd>Delete</kbd>, Add note <kbd>Ctrl</kbd>+<kbd>N</kbd>, Locate in history <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| **Statistics page** | Previous period <kbd>Alt</kbd>+<kbd>Left</kbd>, Next period <kbd>Alt</kbd>+<kbd>Right</kbd> |
| **Settings page** | Save <kbd>Ctrl</kbd>+<kbd>S</kbd> |

The settings dialog is the source of truth. Blank shortcuts are intentionally left unassigned until you bind them.

---

## Customising Shortcuts

1. Go to **Settings → Keyboard Shortcuts**.
2. Click the shortcut you want to change.
3. Press the new key combination.
4. Click **Save**.

To **disable** a shortcut, click it and press <kbd>Backspace</kbd> or <kbd>Delete</kbd> to clear it.

!!! warning "Conflicts"
    If two actions share the same key combination, the most recently set one wins. The Settings dialog will show a warning icon for conflicts.

---

## Quick-Access Overlay Shortcuts

These shortcuts work inside the overlay (the `Ctrl+Shift+H` panel):

| Action | Key |
|---|---|
| **Navigate results** | <kbd>↑</kbd> / <kbd>↓</kbd> |
| **Open selected URL** | <kbd>Enter</kbd> |
| **Open in new tab** (if browser supports it) | <kbd>Ctrl</kbd>+<kbd>Enter</kbd> |
| **Dismiss overlay** | <kbd>Esc</kbd> |
| **Clear search** | <kbd>Ctrl</kbd>+<kbd>A</kbd> then <kbd>Delete</kbd> |
