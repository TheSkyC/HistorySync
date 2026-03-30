# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from src.models.history_record import HistoryRecord
from src.services.favicon_cache import FaviconCache
from src.services.local_db import LocalDatabase
from src.utils.constants import APP_NAME, APP_VERSION
from src.utils.i18n_core import _
from src.utils.logger import get_logger
from src.utils.path_helper import get_templates_dir

log = get_logger("exporter")

# ── Column definitions ────────────────────────────────────────────────────────

ALL_COLUMNS: list[str] = [
    "id",
    "title",
    "url",
    "visit_time",
    "visit_count",
    "browser_type",
    "profile_name",
    "domain",
    "metadata",
    "typed_count",
    "first_visit_time",
    "transition_type",
    "visit_duration",
]

# Human-readable headers (CSV / HTML)
_COLUMN_HEADERS: dict[str, str] = {
    "id": "ID",
    "title": "Title",
    "url": "URL",
    "visit_time": "Visit Time",
    "visit_count": "Visit Count",
    "browser_type": "Browser",
    "profile_name": "Profile",
    "domain": "Domain",
    "metadata": "Metadata",
    "typed_count": "Typed Count",
    "first_visit_time": "First Visit Time",
    "transition_type": "Transition Type",
    "visit_duration": "Visit Duration (s)",
}


def _extract_domain(url: str) -> str:
    """Quick domain extractor — mirrors LocalDatabase._extract_url_host logic."""
    if not url:
        return ""
    try:
        s = url
        if "://" in s:
            s = s.split("://", 1)[1]
        host = s.split("/")[0].split("?")[0].split("#")[0]
        if ":" in host and not host.startswith("["):
            host = host.rsplit(":", 1)[0]
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _extract_root_domain(domain: str) -> str:
    """Extract root domain for favicon fallback."""
    if not domain:
        return ""
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    _SECOND_LEVEL_TLDS = {
        "com",
        "net",
        "org",
        "edu",
        "gov",
        "co",
        "ac",
        "or",
        "ne",
    }
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_TLDS and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _record_to_row(record: HistoryRecord, columns: list[str]) -> dict[str, Any]:
    """Convert a HistoryRecord to a dict keyed by selected columns."""
    # Format first_visit_time the same way as visit_time (UTC string)
    first_visit_str: str | None = None
    if record.first_visit_time:
        try:
            first_visit_str = datetime.fromtimestamp(record.first_visit_time, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OSError, ValueError):
            first_visit_str = str(record.first_visit_time)

    # Map numeric transition_type to a human-readable label
    _CHROMIUM_TRANSITIONS = {
        0: "Link",
        1: "Typed",
        2: "Auto Bookmark",
        3: "Auto Subframe",
        4: "Manual Subframe",
        5: "Generated",
        6: "Auto Toplevel",
        7: "Form Submit",
        8: "Reload",
        9: "Keyword",
        10: "Keyword Generated",
    }
    transition_str: str | None = None
    if record.transition_type is not None:
        transition_str = _CHROMIUM_TRANSITIONS.get(record.transition_type, str(record.transition_type))

    full: dict[str, Any] = {
        "id": record.id,
        "title": record.title or "",
        "url": record.url,
        "visit_time": datetime.fromtimestamp(record.visit_time, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "visit_count": record.visit_count,
        "browser_type": record.browser_type,
        "profile_name": record.profile_name,
        "domain": _extract_domain(record.url),
        "metadata": record.metadata or "",
        "typed_count": record.typed_count,
        "first_visit_time": first_visit_str,
        "transition_type": transition_str,
        "visit_duration": round(record.visit_duration, 2) if record.visit_duration is not None else None,
    }
    return {col: full[col] for col in columns if col in full}


def _batched(lst: list, n: int) -> Iterator[list]:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ── Core params dataclass ─────────────────────────────────────────────────────


@dataclass
class ResolvedExportParams:
    """
    All parameters needed for an export.

    Built from either the GUI (HistoryPage / SettingsPage)
    or the CLI argument parser — Exporter only consumes this.
    """

    # Output
    output_path: Path
    fmt: str  # 'csv' | 'json' | 'html'
    columns: list[str] = field(default_factory=list)  # empty → all
    embed_icons: bool = False  # HTML-only

    # Already-resolved DB-level query parameters
    keyword: str = ""
    browser_type: str = ""
    date_from: int | None = None  # unix timestamp seconds
    date_to: int | None = None  # unix timestamp seconds
    domain_ids: list[int] | None = None
    excludes: list[str] | None = None
    title_only: bool = False
    url_only: bool = False
    use_regex: bool = False

    # Bookmark / annotation filters
    bookmarked_only: bool = False
    has_annotation: bool = False
    bookmark_tag: str = ""


# ── Exporter ──────────────────────────────────────────────────────────────────


class Exporter:
    """
    Qt-free export engine.

    Thread-safe: can be called from any worker thread.
    """

    BATCH_SIZE = 1000

    def __init__(
        self,
        db: LocalDatabase,
        favicon_cache: FaviconCache | None = None,
    ) -> None:
        self._db = db
        self._favicon_cache = favicon_cache

    # ── Public API ────────────────────────────────────────────────────────────

    def export(
        self,
        params: ResolvedExportParams,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> int:
        """
        Run the export.

        Returns the number of rows actually written.
        Raises on IO / format errors.

        progress_callback(current, total)
        cancel_check() → True  ⇒ abort; partial .tmp file is deleted.
        """
        columns = params.columns if params.columns else ALL_COLUMNS[:]
        # Ensure only valid columns
        columns = [c for c in columns if c in ALL_COLUMNS]
        if not columns:
            columns = ALL_COLUMNS[:]

        fmt = params.fmt.lower()
        tmp_path = params.output_path.with_suffix(params.output_path.suffix + ".tmp")

        try:
            params.output_path.parent.mkdir(parents=True, exist_ok=True)

            if params.use_regex and params.keyword:
                records = self._collect_regex_records(params)
                total = len(records)
                exported = self._write_from_list(
                    records,
                    fmt,
                    columns,
                    tmp_path,
                    params,
                    total,
                    progress_callback,
                    cancel_check,
                )
            else:
                total = self._db.get_filtered_count(
                    keyword=params.keyword,
                    browser_type=params.browser_type,
                    date_from=params.date_from,
                    date_to=params.date_to,
                    domain_ids=params.domain_ids,
                    excludes=params.excludes,
                    title_only=params.title_only,
                    url_only=params.url_only,
                    use_regex=False,
                    bookmarked_only=params.bookmarked_only,
                    has_annotation=params.has_annotation,
                    bookmark_tag=params.bookmark_tag,
                )
                exported = self._write_batched(
                    params,
                    fmt,
                    columns,
                    tmp_path,
                    total,
                    progress_callback,
                    cancel_check,
                )

            if cancel_check and cancel_check():
                tmp_path.unlink(missing_ok=True)
                return 0

            tmp_path.replace(params.output_path)
            log.info("Export complete: %d rows → %s", exported, params.output_path)
            return exported

        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    # ── Regex path ────────────────────────────────────────────────────────────

    def _collect_regex_records(self, params: ResolvedExportParams) -> list[HistoryRecord]:
        """
        For regex mode: compile all matching IDs first, then fetch by ID in batches.
        Avoids the offset-pagination semantic error in regex mode.
        """
        try:
            prog = re.compile(params.keyword, re.IGNORECASE)
        except re.error as exc:
            log.warning("Invalid regex '%s': %s", params.keyword, exc)
            return []

        # Pull candidate pool without regex (DB level)
        candidates = self._db.get_records(
            keyword="",
            browser_type=params.browser_type,
            date_from=params.date_from,
            date_to=params.date_to,
            limit=100_000,
            offset=0,
            domain_ids=params.domain_ids,
            excludes=params.excludes,
            title_only=params.title_only,
            url_only=params.url_only,
            use_regex=False,
            bookmarked_only=params.bookmarked_only,
            has_annotation=params.has_annotation,
            bookmark_tag=params.bookmark_tag,
        )

        matched_ids: list[int] = []
        for r in candidates:
            if params.title_only:
                hit = prog.search(r.title or "")
            elif params.url_only:
                hit = prog.search(r.url)
            else:
                hit = prog.search(r.title or "") or prog.search(r.url)
            if hit and r.id is not None:
                matched_ids.append(r.id)

        # Fetch by IDs in batches to preserve order & avoid huge IN clauses
        results: list[HistoryRecord] = []
        for chunk in _batched(matched_ids, self.BATCH_SIZE):
            results.extend(self._db.get_records_by_ids(chunk))
        return results

    # ── Write dispatchers ─────────────────────────────────────────────────────

    def _write_batched(
        self,
        params: ResolvedExportParams,
        fmt: str,
        columns: list[str],
        tmp_path: Path,
        total: int,
        progress_callback: Callable[[int, int], None] | None,
        cancel_check: Callable[[], bool] | None,
    ) -> int:
        """Paginated write for normal (non-regex) mode."""
        written = 0
        with _FormatWriter(fmt, columns, tmp_path, params, self._favicon_cache, total, self._db) as writer:
            offset = 0
            while True:
                if cancel_check and cancel_check():
                    break
                batch = self._db.get_records(
                    keyword=params.keyword,
                    browser_type=params.browser_type,
                    date_from=params.date_from,
                    date_to=params.date_to,
                    limit=self.BATCH_SIZE,
                    offset=offset,
                    domain_ids=params.domain_ids,
                    excludes=params.excludes,
                    title_only=params.title_only,
                    url_only=params.url_only,
                    use_regex=False,
                    bookmarked_only=params.bookmarked_only,
                    has_annotation=params.has_annotation,
                    bookmark_tag=params.bookmark_tag,
                )
                if not batch:
                    break
                for record in batch:
                    writer.write_record(record)
                    written += 1
                offset += len(batch)
                if progress_callback:
                    progress_callback(written, total)
        return written

    def _write_from_list(
        self,
        records: list[HistoryRecord],
        fmt: str,
        columns: list[str],
        tmp_path: Path,
        params: ResolvedExportParams,
        total: int,
        progress_callback: Callable[[int, int], None] | None,
        cancel_check: Callable[[], bool] | None,
    ) -> int:
        written = 0
        with _FormatWriter(fmt, columns, tmp_path, params, self._favicon_cache, total, self._db) as writer:
            for record in records:
                if cancel_check and cancel_check():
                    break
                writer.write_record(record)
                written += 1
                if progress_callback and (written % 100 == 0 or written == total):
                    progress_callback(written, total)
        return written


# ── Format writers ────────────────────────────────────────────────────────────


class _FormatWriter:
    """Context manager that dispatches to CSV / JSON / HTML writers."""

    def __init__(
        self,
        fmt: str,
        columns: list[str],
        path: Path,
        params: ResolvedExportParams,
        favicon_cache: FaviconCache | None,
        total_count: int,
        db: LocalDatabase,
    ) -> None:
        self._fmt = fmt
        self._columns = columns
        self._path = path
        self._params = params
        self._favicon_cache = favicon_cache
        self._total_count = total_count
        self._db = db
        self._fh = None
        self._writer = None

    def __enter__(self):
        self._fh = self._path.open("w", encoding="utf-8", newline="")
        if self._fmt == "csv":
            self._writer = _CsvWriter(self._fh, self._columns)
        elif self._fmt == "json":
            self._writer = _JsonWriter(self._fh, self._columns)
        elif self._fmt == "html":
            self._writer = _HtmlWriter(
                self._fh, self._columns, self._params, self._favicon_cache, self._total_count, self._db
            )
        else:
            raise ValueError(f"Unknown export format: {self._fmt!r}")
        self._writer.begin()
        return self

    def write_record(self, record: HistoryRecord) -> None:
        self._writer.write(record)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._writer:
            try:
                self._writer.end()
            except Exception:
                pass
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
        return False


class _CsvWriter:
    def __init__(self, fh, columns: list[str]) -> None:
        self._csv = csv.DictWriter(
            fh,
            fieldnames=[_COLUMN_HEADERS.get(c, c) for c in columns],
            extrasaction="ignore",
            lineterminator="\n",
        )
        self._columns = columns

    def begin(self) -> None:
        self._csv.writeheader()

    def write(self, record: HistoryRecord) -> None:
        row = _record_to_row(record, self._columns)
        # Rename keys to human-readable headers
        renamed = {_COLUMN_HEADERS.get(k, k): v for k, v in row.items()}
        self._csv.writerow(renamed)

    def end(self) -> None:
        pass


class _JsonWriter:
    def __init__(self, fh, columns: list[str]) -> None:
        self._fh = fh
        self._columns = columns
        self._first = True

    def begin(self) -> None:
        self._fh.write("[\n")

    def write(self, record: HistoryRecord) -> None:
        row = _record_to_row(record, self._columns)
        if not self._first:
            self._fh.write(",\n")
        self._fh.write("  " + json.dumps(row, ensure_ascii=False))
        self._first = False

    def end(self) -> None:
        self._fh.write("\n]\n")


class _HtmlWriter:
    """HTML export with embedded data-driven template (Virtual Scrolling & Pagination)."""

    def __init__(
        self,
        fh,
        columns: list[str],
        params: ResolvedExportParams,
        favicon_cache: FaviconCache | None,
        total_count: int,
        db: LocalDatabase,
    ) -> None:
        self._fh = fh
        self._columns = columns
        self._params = params
        self._favicon_cache = favicon_cache
        self._total_count = total_count
        self._icon_cache: dict[str, str] = {}
        self._first = True
        self._footer_html = ""
        self._db = db

    def _get_icon_data_uri(self, domain: str) -> str:
        if not domain or not self._favicon_cache or not self._params.embed_icons:
            return ""
        if domain in self._icon_cache:
            return self._icon_cache[domain]

        record = self._favicon_cache.get(domain)
        if not record:
            root = _extract_root_domain(domain)
            if root and root != domain:
                record = self._favicon_cache.get(root)

        if record and record.data:
            try:
                mime = {
                    "png": "image/png",
                    "ico": "image/x-icon",
                    "svg": "image/svg+xml",
                    "webp": "image/webp",
                    "jpeg": "image/jpeg",
                    "gif": "image/gif",
                }.get(record.data_type, "image/png")
                b64 = base64.b64encode(record.data).decode("ascii")
                uri = f"data:{mime};base64,{b64}"
                self._icon_cache[domain] = uri
                return uri
            except Exception as exc:
                log.debug("Failed to encode favicon for %s: %s", domain, exc)

        self._icon_cache[domain] = ""
        return ""

    def begin(self) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        replacements = {
            "{app_name}": APP_NAME,
            "{app_version}": APP_VERSION,
            "{lbl_title}": _("History Report"),
            "{export_date}": now_str,
            "{total_items}": f"{self._total_count:,}",
            "{lbl_export_date}": _("Export Date"),
            "{lbl_total_items}": _("Total Items"),
            "{lbl_search_ph}": _("Search title, URL, or domain..."),
            "{lbl_all_browsers}": _("All Browsers"),
            "{lbl_date}": _("Date:"),
            "{lbl_browser}": _("Browser"),
            "{lbl_virtual}": _("Virtual"),
            "{lbl_pages}": _("Pages"),
            "{lbl_showing}": _("Showing"),
            "{lbl_of}": _("of"),
            "{lbl_entries}": _("entries"),
            "{lbl_no_entries}": _("No entries match the current filter."),
            "{lbl_prev}": _("Prev"),
            "{lbl_next}": _("Next"),
            "{lbl_rows}": _("Rows"),
            "{lbl_page}": _("page"),
            "{lbl_col_title}": _("Title & URL"),
            "{lbl_col_time}": _("Visit Time"),
            "{lbl_col_browser}": _("Browser & Profile"),
            "{lbl_toggle_theme}": _("Toggle Theme"),
            "{lbl_scroll_to_top}": _("Scroll to Top"),
        }

        template_path = get_templates_dir() / "history_export.html"
        if not template_path.exists():
            raise FileNotFoundError(f"HTML template not found: {template_path}")

        with template_path.open("r", encoding="utf-8") as f:
            html = f.read()

        for k, v in replacements.items():
            html = html.replace(k, str(v))

        parts = html.split("/*_DATA_INJECT_START_*/")
        if len(parts) != 2:
            raise ValueError("Invalid HTML template: missing /*_DATA_INJECT_START_*/ marker")

        header_html = parts[0]
        self._footer_html = parts[1].split("/*_DATA_INJECT_END_*/")[1]

        self._fh.write(header_html)
        browser_meta = self._get_browser_metadata()
        self._fh.write("\nwindow.BROWSER_META = ")
        json.dump(browser_meta, self._fh, ensure_ascii=False)
        self._fh.write(";\n")
        self._fh.write("window.REPORT_DATA = [\n")

    def _get_browser_metadata(self) -> dict[str, dict]:
        from src.utils.icon_helper import _find_browser_icon_path
        from src.viewmodels.history_viewmodel import _browser_display_name

        db = self._db
        if not db:
            log.warning("Database instance not available for browser metadata extraction.")
            return {}

        browser_types = db.get_browser_types()
        meta = {}
        for bt in browser_types:
            icon_path = _find_browser_icon_path(bt)
            svg_content = ""
            if icon_path and icon_path.suffix.lower() == ".svg":
                try:
                    with icon_path.open("r", encoding="utf-8") as f:
                        svg_content = f.read()
                except Exception as e:
                    log.debug(f"Could not read SVG for {bt}: {e}")

            meta[bt] = {"name": _browser_display_name(bt), "svg": svg_content}
        return meta

    def write(self, record: HistoryRecord) -> None:
        row = _record_to_row(record, self._columns)

        item = {}
        if "title" in row:
            item["t"] = row["title"]
        if "url" in row:
            item["u"] = row["url"]
        if "visit_time" in row:
            item["vt"] = row["visit_time"]
        if "browser_type" in row:
            item["b"] = row["browser_type"]
        if "profile_name" in row:
            item["p"] = row["profile_name"]
        if "domain" in row:
            item["d"] = row["domain"]
        if "metadata" in row:
            item["m"] = row["metadata"]
        if "typed_count" in row and row["typed_count"] is not None:
            item["tc"] = row["typed_count"]
        if "first_visit_time" in row and row["first_visit_time"] is not None:
            item["fvt"] = row["first_visit_time"]
        if "transition_type" in row and row["transition_type"] is not None:
            item["tt"] = row["transition_type"]
        if "visit_duration" in row and row["visit_duration"] is not None:
            item["vd"] = row["visit_duration"]

        if self._params.embed_icons:
            domain = row.get("domain", _extract_domain(record.url))
            self._get_icon_data_uri(domain)

        prefix = "  " if self._first else ",\n  "
        self._fh.write(prefix + json.dumps(item, ensure_ascii=False))
        self._first = False

    def end(self) -> None:
        self._fh.write("\n];\n")

        self._fh.write("window.FAVICON_DICT = ")
        clean_cache = {k: v for k, v in self._icon_cache.items() if v}
        json.dump(clean_cache, self._fh, ensure_ascii=False)
        self._fh.write(";\n")

        self._fh.write(self._footer_html)
