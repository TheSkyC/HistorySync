---
title: CLI Reference
description: Complete reference for the hsync command-line tool — all flags, subcommands, and the advanced query DSL.
---

# CLI Reference — `hsync`

`hsync` is the **headless CLI** for HistorySync. It provides the full power of the application without a GUI, making it ideal for scheduled tasks, scripts, and CI environments.

---

## Global Options

These options are available on every command and subcommand.

| Flag | Short | Description |
|---|---|---|
| `--version` | | Print version and exit |
| `--config-dir PATH` | | Use a custom config/data directory |
| `--portable` | | Store all data next to the `hsync` binary |
| `--verbose` | `-v` | Enable debug-level logging |
| `--quiet` | `-q` | Suppress progress output; only print errors to stderr |
| `--no-color` | | Disable ANSI colour (also `NO_COLOR` env var) |
| `--dry-run` | | Discover/validate without writing anything |

---

## Classic Action Flags

Quick one-shot actions via flags (no subcommand required).

### `-s` / `--sync` — Extract Browser History

Import browser history into the local database.

```bash
hsync -s
hsync --sync

# Sync only specific browsers
hsync -s --browsers chrome,firefox

# Sync every 30 minutes (watch mode)
hsync -s -w 30
```

**Sync options:**

| Flag | Description |
|---|---|
| `--browsers LIST` | Comma-separated browser types (default: all detected). E.g. `chrome,firefox,edge` |
| `-w MINUTES` / `--watch MINUTES` | Repeat sync every `MINUTES` minutes. Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop. |

### `-b` / `--backup` — WebDAV Backup

Upload a compressed snapshot of the local database to WebDAV.

```bash
hsync -b
hsync --backup

# Sync then backup in one shot
hsync -sb
```

!!! note "WebDAV must be configured first"
    Run `hsync config set webdav.enabled true` and set the URL, username, and password before using `--backup`.

<a id="export"></a>

### `-e FILE` / `--export FILE` — Export History

Export browsing history to a file. Format is inferred from the file extension.

```bash
# Basic export to CSV
hsync -e history.csv

# Export to JSON with filters
hsync -e history.json --keyword python --after 2024-01-01

# HTML report with embedded favicons
hsync -e report.html --format html --embed-icons

# Filter by domain(s)
hsync -e out.csv --domain github.com --domain stackoverflow.com

# Custom columns
hsync -e out.csv --columns title,url,visit_time,browser_type

# Regex keyword filter
hsync -e out.json --keyword "^https://github" --regex

# Date range
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**Export options:**

| Flag | Description |
|---|---|
| `--format FMT` | `csv` \| `json` \| `html` (default: inferred from extension) |
| `--columns COLS` | Comma-separated columns. Available: `id`, `title`, `url`, `visit_time`, `visit_count`, `browser_type`, `profile_name`, `domain`, `metadata`, `typed_count`, `first_visit_time`, `transition_type`, `visit_duration` |
| `--embed-icons` | Embed favicons as Base64 data-URIs (HTML export only) |
| `--keyword TEXT` | Full-text keyword filter |
| `--regex` | Treat `--keyword` as a Python regular expression |
| `--browser TYPE` | Filter by browser type (e.g. `chrome`, `firefox`, `edge`) |
| `--after DATE` | Include records on or after `YYYY-MM-DD` |
| `--before DATE` | Include records on or before `YYYY-MM-DD` |
| `--domain HOST` | Filter to a domain. Repeatable: `--domain a.com --domain b.com` |

### `-S` / `--status` — Database Statistics

Print database statistics.

```bash
hsync -S
hsync --status

# Machine-readable JSON
hsync -S --json

# Quiet one-liner (for scripts)
hsync -S -q
```

**Example output:**
```
Database Status
──────────────────────────────────────────────
     Path          :  /home/user/.config/HistorySync/history.db
     Size          :  124.3 MB
     Records       :  1,482,037
     Domains       :  8,421
     FTS index     :  31.2 MB
     Browsers      :  chrome, firefox, edge, brave
     Last sync     :  2026-05-09 14:32:07
     Last backup   :  2026-05-09 12:00:00
```

### `-i` / `--interactive` — Guided Menu

Launch an interactive terminal menu — great for first-time use.

```bash
hsync -i
hsync --interactive
```

---

## Subcommands

### `search` — Search History

Search history records with structured query syntax.

```bash
# Browse recent 20 records
hsync search

# Browse latest 100
hsync search --limit 100

# Simple keyword search
hsync search python

# Interactive mode with keyboard navigation
hsync search -i

# Structured queries
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--limit N` | `20` | Maximum number of results |
| `--format FMT` | `table` | Output format: `table` \| `json` \| `tsv` \| `csv` |
| `--columns COLS` | `title,url,visit_time,browser_type` | Columns to display |
| `--open` | | Open the first result URL in the default browser |
| `-i` / `--interactive` | | Interactive keyboard navigation mode |

---

<a id="query-dsl"></a>

### Query DSL

The search subcommand and the GUI search bar both support a rich query language.

#### Keyword Search

Plain words search across titles and URLs:
```
python async
"exact phrase"
react -tutorial         # exclude a term
```

#### Token Filters

| Token | Example | Description |
|---|---|---|
| `domain:` | `domain:github.com` | Filter by domain |
| `title:` | `title:python` | Search in page title only |
| `url:` | `url:github` | Search in URL only |
| `after:` | `after:2024-01-01` | Date range start (inclusive) |
| `before:` | `before:2024-12-31` | Date range end (inclusive) |
| `browser:` | `browser:chrome` | Filter by browser type |
| `device:` | `device:laptop` | Filter by device name or UUID |
| `is:bookmarked` | `is:bookmarked` | Only bookmarked records |
| `has:note` | `has:note` | Only records with annotations |
| `tag:` | `tag:work` | Filter bookmarks by tag |

#### Combining Tokens

Tokens and keywords can be combined freely:
```
domain:arxiv.org after:2024-01-01 deep learning
is:bookmarked tag:work project management
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — Restore from WebDAV

Restore the database from a WebDAV backup.

```bash
# List backups and choose interactively
hsync restore

# Automatically restore the latest backup (merge)
hsync restore --latest

# List available backups as JSON
hsync restore --list

# Replace mode: completely overwrite local database
hsync restore --replace

# Also restore the favicon cache
hsync restore --latest --restore-favicons
```

**Options:**

| Flag | Description |
|---|---|
| `--latest` | Automatically use the most recent backup without prompting |
| `--list` | List available backups in JSON format and exit |
| `--replace` | Replace mode: overwrite local database instead of merging |
| `--restore-favicons` | Also restore the favicon cache from backup |

!!! info "Merge vs Replace"
    The default behaviour **merges** backup records with your local database — records from both sides are kept and deduplicated. Use `--replace` only when you want to completely overwrite local data with the backup.

---

### `db` — Database Maintenance

```bash
# VACUUM + ANALYZE (reclaim fragmented space)
hsync db vacuum

# Rebuild the full-text search index
hsync db rebuild-fts

# Normalise domain names in all records
hsync db normalize

# Show database statistics
hsync db stats
hsync db stats --json
```

**Subcommands:**

| Subcommand | Description |
|---|---|
| `vacuum` | Run `VACUUM` and `ANALYZE` — reclaims fragmented space, updates query planner statistics |
| `rebuild-fts` | Rebuild the FTS5 full-text search index — use if search feels slow or results are missing |
| `normalize` | Re-compute domain names for all records (useful after importing raw databases) |
| `stats` | Alias for `hsync -S` |

---

### `config` — Manage Configuration

Read and write configuration values without opening the GUI.

```bash
# List all keys and their current values
hsync config list

# Read a single value
hsync config get webdav.url

# Write a value
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language zh_CN
```

**Settable keys:**

| Key | Type | Description |
|---|---|---|
| `webdav.enabled` | bool | Enable WebDAV backup |
| `webdav.url` | string | WebDAV server URL |
| `webdav.username` | string | WebDAV username |
| `webdav.remote_path` | string | Remote path for backups (default: `/HistorySync/`) |
| `webdav.max_backups` | int | Number of backups to keep (default: `10`) |
| `webdav.verify_ssl` | bool | Verify SSL certificate (default: `true`) |
| `webdav.auto_backup` | bool | Enable scheduled auto-backup |
| `webdav.backup_favicons` | bool | Include favicon cache in backup |
| `scheduler.auto_sync_enabled` | bool | Enable automatic browser sync |
| `scheduler.sync_interval_hours` | int | Sync interval in hours |
| `scheduler.auto_backup_enabled` | bool | Enable scheduled WebDAV backup |
| `scheduler.auto_backup_interval_hours` | int | Backup interval in hours |
| `scheduler.launch_on_startup` | bool | Start HistorySync at login |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | UI language code (e.g. `zh_CN`). Empty = auto-detect. |

---

## Shell Completion

`hsync` supports shell completion via `argcomplete`.

=== "Bash"
    ```bash
    # One-time global setup
    activate-global-python-argcomplete --user

    # Or add to ~/.bashrc:
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # Add to ~/.zshrc:
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## Scripting & CI Examples

```bash
# Sync, then check result
hsync -s -q && echo "sync ok" || echo "sync failed"

# Pipe status JSON to jq
hsync -S --json | jq .record_count

# Tee log to file
hsync -s --no-color 2>&1 | tee sync.log

# Scheduled sync + backup (cron-friendly)
hsync -sb -q

# Export last week's GitHub pages to JSON
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"

# Headless sync from Python's main module (for scheduled tasks)
python -m src.main --headless --sync
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (details printed to stderr) |
