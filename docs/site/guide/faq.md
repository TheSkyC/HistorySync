---
title: FAQ
description: Frequently asked questions about HistorySync — installation, sync, privacy, WebDAV, and more.
---

# Frequently Asked Questions

---

## General

### Does HistorySync upload my browsing data to any third party?

**No.** HistorySync is entirely local-first. All history data is stored in a SQLite database **on your own machine**. The only network traffic is the optional WebDAV backup — which goes to a server *you* control (or a self-hosted service). No analytics, telemetry, or external calls are ever made.

### Which browsers are supported?

HistorySync natively supports **30+ browsers**, including:

**Chromium-based:** Chrome, Edge, Brave, Vivaldi, Arc, Chromium, Opera, Opera GX, Yandex Browser, CentBrowser, Thorium, and many more.

**Firefox-based:** Firefox, Firefox ESR, LibreWolf, Waterfox, Pale Moon, SeaMonkey, Basilisk.

**Safari:** macOS only.

**Regional browsers (Windows/macOS/Linux):** QQ Browser, Sogou, UC Browser, Liebao, Maxthon, Twinkstar, and others.

If your browser is not listed, use **Settings → Browsers → Add Custom Path** to add it manually, or try the smart scan feature.

### Can I use HistorySync on multiple computers?

Yes! Install HistorySync on each machine, configure the same WebDAV server on all of them, and enable auto-sync. When you restore (or when HistorySync auto-merges from the cloud), records from all devices are **intelligently deduplicated** based on browser type, URL, and visit timestamp.

---

## Sync & Extraction

### Does HistorySync work while my browser is open?

Yes. HistorySync uses **SQLite WAL (Write-Ahead Log) snapshots** — it copies the WAL file before reading, so there is never any conflict with a running browser. Your browser is never locked or paused.

### Why are some records missing after a sync?

A few possible reasons:

- **Private/Incognito browsing** — browsers do not write incognito history to disk; HistorySync cannot see it.
- **Browser profile disabled** — check **Settings → Browsers** and confirm the profile is not disabled.
- **URL is filtered** — HistorySync ignores internal browser URLs (`chrome://`, `about:`, `file://`, etc.) and any domains on your blacklist.
- **First sync was incremental** — try **Settings → Maintenance → Full Resync**, or use the GUI startup entry point `python -m src.main --resync`, to re-read all historical records.

### What is a "full resync"?

A normal sync is **incremental** — it only reads records newer than the last sync timestamp. A full resync ignores the watermark and re-reads every record from every browser, back-filling fields like `visit_count` that may have changed. It is safe to run at any time — records are upserted, not duplicated.

```bash
# GUI startup entry point (not the hsync CLI)
python -m src.main --resync

# From GUI: Settings → Maintenance → Full Resync
```

---

## Privacy & Security

### Where is my data stored?

| Platform | Default Location |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

Use `--config-dir PATH` to override, or `--portable` to store everything next to the executable.

### How are WebDAV credentials protected?

Credentials are **never stored in plain text**. HistorySync derives independent encryption and authentication sub-keys from a master key stored in the OS keychain (via `keyring`), using HKDF. See [Security Architecture](../dev/security.md) for full details.

### What is "soft-hide" / hidden records?

Soft-hiding marks a record (or all records for a domain) as hidden — they disappear from the main History view but remain in the database. You can view them in **History → Show Hidden**. This is useful for hiding sensitive pages without permanently deleting them.

### What is the domain blacklist?

Domains on the blacklist are **never imported**, and any existing records for those domains are **permanently deleted**. Right-click a record → **Blacklist Domain**, or manage the list in **Settings → Privacy → Domain Blacklist**.

---

## WebDAV & Cloud Backup

### What WebDAV providers work with HistorySync?

Any standard WebDAV server. Tested with: Nextcloud, Synology DSM, ownCloud, AList, Nginx WebDAV, Apache mod_dav, Caddy WebDAV. See the [WebDAV Setup guide](webdav-setup.md) for provider-specific instructions.

### How many backups are kept?

By default, **10 backups** are retained on the server. Older ones are pruned automatically after each successful upload. Change this with `hsync config set webdav.max_backups N`.

### Backup failed with "Connection refused" — what do I check?

1. Verify the WebDAV URL (protocol, hostname, port, path).
2. Check username and password — for Nextcloud, use an **App Password**.
3. Test connectivity: `curl -u user:pass https://your-server/dav/`.
4. If using a self-signed certificate, set `hsync config set webdav.verify_ssl false`.

---

## Performance

### HistorySync is slow with millions of records — what can I do?

Try these steps in order:

1. **Run `hsync db vacuum`** — reclaims fragmented space and refreshes query planner statistics.
2. **Run `hsync db rebuild-fts`** — rebuilds the full-text search index.
3. Ensure your database is on a fast local SSD, not a network share or USB drive.
4. If you use a regex search, consider switching to a plain keyword search — regex is faster via SQL pushdown, but very complex patterns can still be slow.

### How much disk space does the database use?

It depends on the number of records and how much page metadata is stored. A rough guideline:

| Records | Approximate size |
|---|---|
| 100,000 | ~20–40 MB |
| 500,000 | ~80–150 MB |
| 1,000,000 | ~150–300 MB |
| 5,000,000 | ~600 MB – 1.2 GB |

Run `hsync db vacuum` periodically to keep the file compact.

---

## CLI (`hsync`)

### How do I install `hsync` as a system command?

If you run from source:
```bash
# Linux / macOS
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

If you use the pre-built package, the installer typically places `hsync` on your `PATH` automatically.

### Can I use `hsync` in a Docker container / CI pipeline?

Yes. Use `--headless` mode to avoid any GUI dependency:

```bash
python -m src.main --headless --sync --config-dir /data/config
```

Or use `hsync` directly:

```bash
hsync -s --config-dir /data/config -q
```

Set `QT_QPA_PLATFORM=offscreen` if Qt complains about a missing display.

---

## Contributing & Development

### How do I report a bug?

Use the **[GitHub Bug Report template](https://github.com/TheSkyC/HistorySync/issues/new?template=bug_report.yml)**. Include your OS, HistorySync version, the browsers involved, and steps to reproduce.

### I found a security vulnerability — what should I do?

**Do not open a public issue.** Email **security@historysync.app** with a description, reproduction steps, and potential impact. You will receive a response within 72 hours.

### How do I add support for a new browser?

See the [Contributing guide](../dev/contributing.md). Browser extractors live in `src/services/extractors/`. Most new Chromium forks can be added with just a few lines by subclassing `ChromiumExtractor`.
