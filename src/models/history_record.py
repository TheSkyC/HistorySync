# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field


@dataclass(slots=True)
class HistoryRecord:
    # --- Core fields ---
    url: str
    title: str
    visit_time: int  # Unix timestamp in seconds (10 digits)
    visit_count: int
    browser_type: str  # Browser type identifier, e.g. 'chrome', 'edge', 'firefox'
    profile_name: str  # Profile name, e.g. 'Default', 'default-release'

    # --- Extended fields ---
    # Pre-computed display domain (e.g. "github.com") — derived from url at load time.
    # Stored here so data() and get_pixmap() never call urlparse on the hot render path.
    domain: str = field(default="", compare=False)

    metadata: str = ""  # Page summary/description; may be empty

    # Number of times the URL was manually typed in the address bar.
    # Chromium-only; None for all other browsers.
    typed_count: int | None = field(default=None, compare=False)

    # Timestamp (seconds) of the first ever visit, derived via MIN() over the visits table.
    first_visit_time: int | None = field(default=None, compare=False)

    # Navigation source type:
    #   Chromium: 0=LINK, 1=TYPED, 2=AUTO_BOOKMARK, 7=FORM_SUBMIT, 8=RELOAD, etc.
    #   Firefox:  1=LINK, 2=TYPED, 3=BOOKMARK
    #   Safari:   None
    transition_type: int | None = field(default=None, compare=False)

    # Time spent on page during the most recent visit, in seconds.
    # Chromium-only (from visits.visit_duration); None for all other browsers.
    visit_duration: float | None = field(default=None, compare=False)

    # Auto-incremented database row ID; populated when reading from DB.
    id: int | None = field(default=None, compare=False)

    # ID of the device that produced this record (references devices.id).
    # None means the origin is unknown.
    device_id: int | None = field(default=None, compare=False)

    def dedup_key(self) -> str:
        """Deduplication key: same browser + same URL + same timestamp = duplicate.

        Handles the edge case where Edge imports Chrome's history.
        """
        return f"{self.browser_type}|{self.url}|{self.visit_time}"


@dataclass(slots=True)
class BookmarkRecord:
    """A bookmarked history entry with optional tags."""

    url: str
    title: str
    bookmarked_at: int  # Unix timestamp (seconds)
    tags: list[str] = field(default_factory=list)  # e.g. ["work", "ref"]
    history_id: int | None = field(default=None, compare=False)
    id: int | None = field(default=None, compare=False)

    def tags_str(self) -> str:
        return ", ".join(self.tags)


@dataclass(slots=True)
class AnnotationRecord:
    """A user note attached to a history URL."""

    url: str
    note: str  # free-form text
    created_at: int  # Unix timestamp (seconds)
    updated_at: int  # Unix timestamp (seconds)
    history_id: int | None = field(default=None, compare=False)
    id: int | None = field(default=None, compare=False)


@dataclass
class BackupStats:
    """Backup statistics metadata per browser/profile."""

    browser_type: str
    profile_name: str
    first_backup_time: int  # Timestamp of the first backup
    last_backup_time: int  # Timestamp of the last successful backup
    total_records_synced: int  # Cumulative number of records synced

    id: int | None = field(default=None, compare=False)
