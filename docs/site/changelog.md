---
title: Changelog
description: Release history and notable changes for HistorySync.
---

# Changelog

All notable changes are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

*Changes on `main` not yet in a tagged release.*

---

## [1.4.0] - 2026-06-01

### Added
- Built-in online update support for the desktop app, including platform-aware package selection, release-channel support, and a GitHub fallback when the primary update API is unavailable.
- Update banners, release-detail dialogs, reminder preferences, and a dedicated Settings section for update policy, source preference, and channel selection.
- `hsync update` for headless update checks, with both human-readable and JSON output and optional channel override.
- A unified custom-browser runtime model so manually added browsers and deep-scan discoveries behave like first-class browser integrations across sync, monitoring, and UI surfaces.
- Automatic log tailing in the log viewer, with pause behaviour when the page is hidden or the window is minimised.

### Changed
- WebDAV settings were streamlined into a cleaner, less error-prone configuration flow.
- Bookmark rendering was virtualised, making the bookmarks page scale much better on large datasets.

### Fixed
- Browser-monitor state no longer flips to `NEEDS_SYNC` spuriously; sync freshness now compares against the database mtime captured during extraction.
- WebDAV credential access is now deferred and deduplicated, reducing unnecessary keyring traffic and avoiding repeated unlock prompts on some systems.
- Optional WebDAV imports now load only when a transfer actually starts, improving startup robustness on partially provisioned environments.
- Browsers added through custom paths are now registered at startup and immediately after saving settings, so they participate in sync and status monitoring without restart.
- `browser:` search filters are now case-insensitive, and domain matching now escapes SQL `LIKE` wildcards correctly to prevent false matches and accidental overreach.
- Disabled browsers are shown explicitly as `DISABLED` on the dashboard instead of disappearing from the status view.
- The history scroll bubble now prefers the right edge and falls back left near screen boundaries.
- Dashboard deep-scan cleanup no longer double-frees the scroll-area widget.
- Risky custom-browser removals now require confirmation before destructive actions.
- Statistics month labels no longer depend on the system locale and now use the app's i18n month names consistently.
- Tray behaviour is more consistent: single-click open works across platforms and the light-theme sync spinner is easier to see.
- Centered dialogs and StyledComboBox popups now clamp to screen bounds, improving behaviour on multi-monitor and edge-of-screen layouts.
- Dashboard stat cards are now responsive and keep a stable height across window sizes.
- Update checks now avoid blocking on GitHub throttling.

### Build
- Release packaging and validation workflows were expanded and hardened across platforms, including installer validation, ARM64 installer flag fixes, and dependency-install hardening in CI.

### Docs
- The documentation site was refreshed for 1.4.0 to cover online updates, update reminders, CLI update checks, and the revised install and upgrade flow.

---

## [1.3.2] - 2026-05-25

### Added
- Stable releases are now mirrored to R2 for more resilient distribution.

### Changed
- Auto-backup after sync is now disabled by default.

### Fixed
- Fixed a scheduler thread-cleanup race that could affect sync stability.
- `hsync db normalize` now requires explicit confirmation before applying changes.
- CLI sync now cleans up database resources more reliably.
- Single-instance IPC tokens are now isolated per user account.

### Docs
- Refreshed the documentation site branding, contact information, and localized pages.
- Added a dedicated security policy.

### Tests
- Expanded automated coverage for scheduler, viewmodel, and WebDAV flows.

---

## [1.3.1] - 2026-05-19

### Fixed
- Regex export no longer capped at 100 000 records; replaced with cursor pagination for complete large exports.
- UI no longer freezes during regex history search; scan moved to a background thread.
- Monthly time range calculations no longer skew around DST transitions.
- Hidden-domain filter now correctly escapes LIKE wildcard characters in domain names.
- URL prefix record counts no longer double-count overlapping prefixes.
- WebDAV cleanup failures now surfaced instead of silently swallowed; manifest timestamp aligned with upload time.
- HTML export now raises an error when the template is missing the injection marker instead of producing corrupt output.
- Config saves suppressed on shutdown to prevent corruption; failed config promotes now roll back cleanly.
- Config backup rotation fixed; migration false-positive detection guard added.
- Badge data loading now handles DB errors gracefully instead of crashing.
- Extractor backup thread no longer implicitly blocks the main process on shutdown.
- Potential deadlock during FTS-stripped database export resolved.

### Build
- WebDAV hidden import corrected from `webdav4` to `webdav3` in PyInstaller spec, fixing missing-module errors in packaged builds.

---

## [1.3.0] - 2026-05-14

### Added
- Default theme changed from Dark to System, so the app now follows OS appearance out of the box.
- Record count preview in blacklist and hidden-domain management dialogs, showing impact before confirming changes.
- Isolated recent search history for regex mode, keeping advanced search workflows cleaner.
- Redesigned app icon with an animated SVG-based tray renderer replacing static tray assets.
- Added a multilingual MkDocs documentation site.

### Fixed
- FTS triggers silently lost after a process crash are now recovered before all history write paths.
- `title:` and `url:` search tokens no longer overwrite each other; multi-word field queries now split into AND terms correctly.
- Hidden domains are now filtered correctly in overlay quick search.
- Safari incremental extraction time boundary condition corrected.
- Incorrect path filter in browser scanner that excluded non-standard installations removed.
- WebDAV password ciphertext now preserved when decryption fails on config load.
- Single-instance startup now falls back safely when token file write fails.
- History records correctly migrated when adopting a previous device identity.
- `sync_progress` signal guarded against wrong argument types emitted from worker thread.
- Real-time sync progress was restored, and the QThread wrapper lifetime was hardened against destroyed-while-running crashes.
- The backup thread lifecycle was fixed, and auto-backup exceptions are now isolated from the sync flow.
- Cross-thread signal emission races and QThread lifetime issues during sync were resolved.
- FTS triggers restored immediately on upsert exception to close the write window.
- `_ro_lock` held across both query stages in `get_records` to eliminate connection race.
- WebDAV sync manifest uploaded before cleaning old backups to prevent stale manifest on crash.
- Domain cache writes guarded with a lock to prevent TOCTOU race.
- Stale page cache evicted in regex load-more path to prevent blank rows.
- Dialog flash at top-left corner on first open eliminated.
- Autocomplete font size clamped to valid range on Linux.
- Tray minimization prevented when system tray is unavailable.

### Performance
- O(N) vt_cache trim replaced with page-granularity LRU eviction.
- Write lock released before `VACUUM INTO` in `export_without_fts`.
- Shared registry and filter sets in extractor manager guarded with a lock to prevent data races.

### Build
- Linux Qt platform fallback added; xcb dependencies packaged for out-of-box startup on Linux.
- Comprehensive `.gitattributes` rules added for line endings and binary files.

---

## [1.2.2] - 2026-04-29

### Fixed
- CLI `restore` always restored the latest backup instead of the user-selected one.
- CLI `restore` did not honor the favicon restore flag.
- CLI `restore --replace` used unsafe database replacement.
- Scheduler lead-in timers not cancelled, causing stale callbacks to fire after reschedule.
- Terminal size API usage corrected, fixing output formatting in all CLI commands.

---

## [1.2.1] - 2026-04-23

### Added
- "Locate in History" button on bookmark cards for quick navigation.
- Clicking the tag chip area or note area on a bookmark card now opens the editor directly.

### Fixed
- `Ctrl+F` / `Ctrl+R` global shortcut conflicts resolved; shortcuts now work reliably in history view.
- Date separator visit counts now respect current filters and hidden-record mode.

---

## [1.2.0] - 2026-04-23

### Added
- 14 configurable global and in-app keyboard shortcuts with a dedicated settings panel.
- Hidden Records viewing mode: a dedicated view for soft-hidden records.
- Soft hide-domain: hide all records from a domain without deleting them, with a standalone manager UI.
- Portable mode: auto-detects a `.portable` marker file in the app root and routes all data to `data/` subdirectory.
- "Search the Web" entry in the quick-access overlay and autocomplete dropdown, with configurable search engine presets.
- "Start minimized to tray" startup setting.
- Lazy-GUI minimize-to-tray mode: window and subsystems deferred until first open.
- Date separators now restored after column toggle or reorder.
- Real-time system Dark/Light mode following.

### Changed
- WebDAV uploads switched from chunked to atomic streamed, significantly improving reliability and eliminating temporary file descriptor leaks on Windows.
- Headless mode now skips GUI subsystems and uses a lower SQLite cache, reducing background memory footprint.
- Domain and icon cache eviction changed from full `clear()` to FIFO `popitem()` to eliminate periodic eviction spikes.
- Column visibility toggles moved into a submenu for a cleaner toolbar.

### Fixed
- WAL read-after-write inconsistencies resolved by unifying connection lifecycle lock order.
- VACUUM crash caused by `prune_tombstones` running while `_vacuuming=True` fixed.
- Tombstones pruned during VACUUM to prevent unbounded table growth.
- Scroll jitter after delete/hide/unhide fixed; scroll position preserved instead of jumping to top.
- Long titles no longer push action buttons off-screen in settings cards.
- Spurious horizontal scrollbar after theme switches eliminated.
- Bookmark and annotation reads now see fresh data immediately after a write (stale WAL snapshot fixed).
- Windows Junction points no longer traversed during BFS browser scan.
- QTimer interval clamped to `INT32_MAX` to prevent integer overflow on very long intervals.
- `BrowserMonitor` properly terminated on application exit.
- Multi-word CLI search queries now accepted without quoting.
- Long table output in CLI truncated with ellipsis to prevent line overflow.
- `encrypt_text` failures now propagated instead of silently discarding the WebDAV password.
- `get_bookmarked_urls` now uses `DISTINCT` to prevent duplicate URL results.

### Performance
- Two-step keyset pagination in `get_records` eliminates O(N) offset scan for large histories.
- Regex search pagination pushed to SQL layer, eliminating full-table O(N) scan.
- Fast-scroll lag reduced by optimizing paint, `data()`, URL parsing, and `eventFilter` hot paths.
- `DashboardPage` browser status updates skipped when window is hidden.

### Security
- Encryption upgraded to V2 format with independent HKDF encryption and authentication subkeys.
- Nonce-based authentication added to single-instance IPC to prevent replay attacks.
- XSS vulnerability in HTML export patched: SVG icons sanitized before embedding.
- Master password idle timeout now uses `time.time()` to correctly count time during system sleep.
- Master password bypass gaps closed; stale session UI fixed.

### Build
- macOS standalone `tar.gz` artifact added.
- Windows portable ZIP and setup installer added.
- Windows standalone Python runtime cached in CI to reduce build times.

---

## [1.1.1] - 2026-04-12

### Fixed
- Overlay (`Ctrl+Shift+H`) vertical drift when reopening fixed.
- Random horizontal scrollbar appearing in the history table fixed.
- Bookmarks page not refreshing after modifying bookmarks from the History page fixed.
- `bookmarked_at` timestamp not updating on conflict fixed.
- Potential race condition during WebDAV client initialization fixed.
- Stale filter hits from uncleared `_excl_cache` on connection reset fixed.

### Performance
- History queries and bookmark/annotation badge loading moved to a background thread to unblock the UI.
- Display domain resolved via JOIN on `domains` table instead of per-row URL parsing on the render path.
- Redundant second VACUUM removed from `export_without_fts`.
- `NOT IN` subquery on `hidden_records` replaced with more efficient `NOT EXISTS` correlated lookup.

---

## [1.1.0] - 2026-04-11

### Added
- Spotlight-style global quick-search overlay (`Ctrl+Shift+H`): instant search across history, bookmarks, and annotations from any app.
- Advanced search syntax: `domain:`, `after:`, `before:`, `title:`, `url:`, `browser:`, `device:`, `is:bookmarked`, `has:note`, `tag:`.
- Inline ghost-text autocomplete and fuzzy-matching dropdown suggestions in the search bar.
- Statistics page with a GitHub-style annual activity heatmap (with active-month contour highlight), browser usage pie chart, 24-hour activity bar chart, and one-click high-resolution image export.
- Bookmarks and annotations system: tag URLs and write rich-text notes to build a personal knowledge base.
- `hsync` headless CLI with `sync`, `backup`, `search`, `export`, `restore`, `config`, `db`, and watch-mode commands.
- Shell tab completion for `hsync` via `argcomplete` (Bash, Zsh, Fish).
- Device identity management: rename devices, delete obsolete ones, or adopt a previous identity after an OS reinstall.
- WebDAV restore now merges with local data instead of a destructive overwrite.
- Drag-and-drop URL export from the history table (`Alt`+drag or favicon drag) to desktop or editors.
- Scroll time bubble: shows date, top domain, and activity density bar while dragging the scrollbar.
- Native browser support added: QQ Browser, Sogou, Twinkstar, CentBrowser, 2345 Explorer, Liebao, UC Browser (Desktop), Quark.
- Firefox fork support added: Waterfox, LibreWolf, Pale Moon, Basilisk, SeaMonkey.
- Chrome, Edge, and Brave Canary/Dev/Beta channel support.
- BFS deep scan to automatically discover portable or non-standard browser installations.
- Overlay fade-in/fade-out animation.
- First-run wizard overhauled for simpler initial setup.
- Migration wizard for lossless migration from v1.0.x installations.
- Scrollbar context menu for time bubble display modes.
- Inertial smooth animation on the scroll time bubble.

### Fixed
- File-locking issues during WebDAV backup on Windows resolved.
- Scrollbar position jumping on Dark/Light theme switch fixed.
- FTS multi-word queries now use AND semantics for higher precision recall.
- `normalize_domains` UPDATE now processed in 5000-row chunks to avoid long write locks.
- Hidden records excluded from analytics stats and overlay quick search.
- `_ensure_conn` guarded with `_vacuuming` flag to prevent concurrent access during VACUUM.

### Performance
- SQLite extraction rewritten with batch inserts and pre-compiled regex, reducing memory usage and improving speed.
- Favicon rendering optimized with LRU cache and SVG recoloring, reducing stuttering during fast scrolling.
- History page initial load uses progressive initialization to reduce time to first paint.

---

## [1.0.0] - 2026-03-24

Initial stable release.

### Added
- Browser history aggregation from Chromium-based (Chrome, Edge, Brave, Opera, Vivaldi, Arc, and more), Firefox-based, and Safari browsers.
- Local SQLite database with FTS5 full-text search using a trigram tokenizer for millisecond-latency substring search.
- WebDAV cloud backup and restore with ZIP compression and SHA-256 integrity verification.
- Multi-browser, multi-profile support with WAL-safe database copying.
- Virtual scrolling for smooth browsing of million-row history lists.
- System tray integration with sync status notifications.
- Master password encryption for WebDAV credentials via HKDF-SHA256 and system keyring integration.
- Windows and macOS packages.

[Unreleased]: https://github.com/TheSkyC/HistorySync/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/TheSkyC/HistorySync/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/TheSkyC/HistorySync/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/TheSkyC/HistorySync/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/TheSkyC/HistorySync/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/TheSkyC/HistorySync/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/TheSkyC/HistorySync/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/TheSkyC/HistorySync/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/TheSkyC/HistorySync/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/TheSkyC/HistorySync/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/TheSkyC/HistorySync/commits/v1.0.0
