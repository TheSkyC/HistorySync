---
title: Quick Start
description: Get HistorySync up and running in under five minutes — automatic background sync, cloud backup, and Spotlight search.
---

# Quick Start

This guide gets you from zero to a fully automated browser-history backup in **under five minutes**.

---

## Step 1 — First Launch

Start HistorySync. On the first run, a **Setup Wizard** walks you through the essential settings.

If you installed from source:
```bash
python -m src.main
```

---

## Step 2 — Sync Your Browsers

On the **Dashboard**, click **Sync Now**. HistorySync will:

1. Auto-detect all installed browsers on your system.
2. Safely read their SQLite history databases using WAL snapshots — the browsers can stay open.
3. Import records into the local HistorySync database.

!!! tip "First sync takes longer"
    If you have years of history across multiple browsers, the first sync may take a minute or two. Subsequent syncs are **incremental** — only new records are imported.

### Selective sync

To sync only specific browsers, use the CLI:
```bash
hsync -s --browsers chrome,firefox
```

---

## Step 3 — Search Your History

### GUI Search
Use the search bar at the top of the **History** tab. As you type, results appear instantly.

### Global Overlay (Spotlight)
Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> from **any application** to summon the quick-access overlay. Works on Windows, macOS, and Linux (X11). On Wayland, use `python -m src.main --quick` with a system-level shortcut instead.

Type naturally, or use the [Advanced Query DSL](cli-reference.md#query-dsl):

| Example query | What it finds |
|---|---|
| `python async` | Pages with those words in title or URL |
| `domain:github.com` | Only GitHub pages |
| `after:2024-06-01 domain:arxiv.org` | Papers read after June 2024 |
| `is:bookmarked tag:work` | Bookmarked pages tagged "work" |
| `react -tutorial` | React pages, excluding tutorials |

---

## Step 4 — Enable Automatic Sync

Go to **Settings → Auto Sync** and:

1. Enable **Auto Sync**.
2. Set your preferred interval (default: 2 hours).
3. Enable **Launch at system startup** so HistorySync starts silently in the background.

From now on, your browser history is continuously merged into one searchable database — automatically.

---

## Step 5 — Set Up Cloud Backup (Optional)

WebDAV backup lets you restore your history on a new machine or share it across devices.

1. Go to **Settings → WebDAV Cloud Backup**.
2. Enter your WebDAV server URL, username, and password.
3. Enable **Auto Backup** and set an interval.
4. Click **Test Connection** to verify.

See the [WebDAV Setup guide](webdav-setup.md) for a list of compatible providers with step-by-step instructions.

---

## Step 6 — Enable Update Checks

Go to **Settings → Updates** and decide how you want HistorySync to handle new releases:

1. Leave **Automatically check for updates** enabled if you want passive update reminders.
2. Choose a release channel such as **Stable** or **Beta**.
3. Pick a reminder policy, for example once per week instead of every launch.
4. Use **Check for Updates** any time you want an on-demand check.

When a newer build is available, HistorySync can show a banner, open a detailed release dialog, and remember "remind me later" or "skip this version" decisions.

---

## Step 7 — Tray Mode (Background Operation)

Once configured, close the main window. HistorySync minimises to the **system tray** and continues syncing and backing up silently.

Right-click the tray icon to:

- **Open HistorySync** — bring the main window back.
- **Sync Now** — trigger an immediate sync.
- **Backup Now** — trigger an immediate WebDAV backup.
- **Quit** — stop the application completely.

---

## Next Steps

| What you want to do | Where to go |
|---|---|
| Automate syncs from the terminal | [CLI Reference](cli-reference.md) |
| Check for new releases from the terminal | [CLI Reference](cli-reference.md#update-check-for-updates) |
| Configure a specific WebDAV provider | [WebDAV Setup](webdav-setup.md) |
| Customise keyboard shortcuts | [Keyboard Shortcuts](keyboard-shortcuts.md) |
| Export your history to CSV / JSON / HTML | [CLI Reference — Export History](cli-reference.md#export) |
| Understand the security model | [Security Architecture](../dev/security.md) |
