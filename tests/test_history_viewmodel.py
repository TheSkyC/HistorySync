# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for ``src.viewmodels.history_viewmodel``.

Coverage targets:

* Pure helpers — ``_format_time``, ``_format_transition``,
  ``_browser_display_name``.
* DisplayRole getter dispatch table (``_DISPLAY_GETTERS``).
* :class:`HistoryTableModel` column configuration, ``data()`` role dispatch,
  page cache + LRU eviction, regex incremental load, badge invalidation,
  ``_on_favicons_updated`` range coalescing, and prefetch debounce.
* :class:`HistoryViewModel` public API (search / refresh / hidden ids).
* :class:`_ReloadWorker` and :class:`_RegexWorker` ``run()`` outcomes when
  driven synchronously (no QThread spin-up).

The fake :class:`_FakeDb` is a thin double that records calls and serves
canned responses for every LocalDatabase method the viewmodel touches.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

pytest.importorskip("PySide6.QtGui")

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import QPixmap

from src.models.history_record import HistoryRecord
from src.viewmodels.history_viewmodel import (
    _DISPLAY_GETTERS,
    ALL_COLUMNS,
    ANNOTATION_ROLE,
    BOOKMARK_ROLE,
    CACHE_PAGE_SIZE,
    DEFAULT_VISIBLE_COLUMNS,
    MAX_CACHED_PAGES,
    HistoryTableModel,
    HistoryViewModel,
    _browser_display_name,
    _format_time,
    _format_transition,
    _RegexWorker,
    _ReloadWorker,
)

# ──────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────


class _FakeDb:
    """Fake :class:`LocalDatabase` exposing only the surface the viewmodel uses.

    Callers can set canned responses via the ``_*_response`` attributes, or
    populate ``records`` and rely on default fall-through behaviour.  Every
    public method records its arguments in the corresponding ``*_calls`` list
    so the tests can assert call counts and parameters.
    """

    def __init__(self) -> None:
        self.records: list[HistoryRecord] = []
        self.bookmarked_urls: set[str] = set()
        self.annotated_urls: set[str] = set()
        self.device_name_map: dict[int, str] = {}
        self.browser_types: list[str] = []
        self.devices: list[dict[str, Any]] = []
        self.tags: list[str] = []
        self.top_domains: list[tuple[str, int]] = []
        self.domain_id_map: dict[str, int] = {}
        self.device_id_map: dict[str, int] = {}

        # Programmable responses (None = use default fall-through)
        self._filtered_count: int | None = None
        self._filtered_id_times: list[tuple[int, int]] | None = None
        self._records_by_call: list[list[HistoryRecord]] | None = None
        self._records_by_ids_response: list[HistoryRecord] | None = None
        self._visit_time_response: int | None = None
        self._raise_on: set[str] = set()

        # Call recorders
        self.get_records_calls: list[dict[str, Any]] = []
        self.get_records_by_ids_calls: list[list[int]] = []
        self.get_filtered_count_calls: list[dict[str, Any]] = []
        self.get_filtered_id_times_calls: list[dict[str, Any]] = []
        self.get_visit_time_calls: list[dict[str, Any]] = []
        self.get_bookmarked_urls_calls = 0
        self.get_annotated_urls_calls = 0
        self.get_device_name_map_calls = 0

    def _maybe_raise(self, name: str) -> None:
        if name in self._raise_on:
            raise RuntimeError(f"forced failure in {name}")

    def get_records(self, **kwargs: Any) -> list[HistoryRecord]:
        self._maybe_raise("get_records")
        self.get_records_calls.append(kwargs)
        if self._records_by_call is not None:
            idx = len(self.get_records_calls) - 1
            if idx < len(self._records_by_call):
                return list(self._records_by_call[idx])
            return []
        return list(self.records)

    def get_records_by_ids(self, ids: list[int]) -> list[HistoryRecord]:
        self._maybe_raise("get_records_by_ids")
        self.get_records_by_ids_calls.append(list(ids))
        if self._records_by_ids_response is not None:
            return list(self._records_by_ids_response)
        by_id = {r.id: r for r in self.records if r.id is not None}
        return [by_id[i] for i in ids if i in by_id]

    def get_filtered_count(self, **kwargs: Any) -> int:
        self._maybe_raise("get_filtered_count")
        self.get_filtered_count_calls.append(kwargs)
        if self._filtered_count is not None:
            return self._filtered_count
        return len(self.records)

    def get_filtered_id_times(self, **kwargs: Any) -> list[tuple[int, int]]:
        self._maybe_raise("get_filtered_id_times")
        self.get_filtered_id_times_calls.append(kwargs)
        if self._filtered_id_times is not None:
            return list(self._filtered_id_times)
        return [(r.id, r.visit_time) for r in self.records if r.id is not None]

    def get_visit_time_at_offset(self, **kwargs: Any) -> int | None:
        self._maybe_raise("get_visit_time_at_offset")
        self.get_visit_time_calls.append(kwargs)
        return self._visit_time_response

    def get_bookmarked_urls(self) -> set[str]:
        self._maybe_raise("get_bookmarked_urls")
        self.get_bookmarked_urls_calls += 1
        return set(self.bookmarked_urls)

    def get_annotated_urls(self) -> set[str]:
        self._maybe_raise("get_annotated_urls")
        self.get_annotated_urls_calls += 1
        return set(self.annotated_urls)

    def get_device_name_map(self) -> dict[int, str]:
        self._maybe_raise("get_device_name_map")
        self.get_device_name_map_calls += 1
        return dict(self.device_name_map)

    def get_browser_types(self) -> list[str]:
        return list(self.browser_types)

    def get_all_devices(self) -> list[dict[str, Any]]:
        return list(self.devices)

    def get_all_bookmark_tags(self) -> list[str]:
        return list(self.tags)

    def get_top_domains(self, limit: int) -> list[tuple[str, int]]:
        return list(self.top_domains[:limit])

    def resolve_domain_ids(self, domains: list[str]) -> list[int]:
        return [self.domain_id_map[d] for d in domains if d in self.domain_id_map]

    def resolve_device_ids(self, name_or_uuid: str) -> list[int]:
        if name_or_uuid in self.device_id_map:
            return [self.device_id_map[name_or_uuid]]
        return []


class _FakeFaviconManager(QObject):
    """Real QObject with a ``favicons_updated`` signal so ``connect`` works."""

    favicons_updated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.prefetched: list[HistoryRecord] = []
        self.prefetch_calls = 0

    def get_pixmap(self, url: str, size: int = 16, domain: str | None = None) -> QPixmap:
        # Return a non-null 1×1 pixmap so callers that check ``isNull()`` see truthy.
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        return px

    def prefetch_pixmaps(self, records: list[HistoryRecord], size: int = 16) -> None:
        self.prefetch_calls += 1
        self.prefetched.extend(records)


def _rec(
    *,
    rid: int = 1,
    url: str | None = None,
    title: str = "Title",
    visit_time: int = 1_704_067_200,
    visit_count: int = 3,
    browser_type: str = "chrome",
    profile_name: str = "Default",
    metadata: str = "",
    domain: str | None = None,
    typed_count: int | None = None,
    first_visit_time: int | None = None,
    transition_type: int | None = None,
    visit_duration: float | None = None,
    device_id: int | None = None,
) -> HistoryRecord:
    """Compact factory for synthetic HistoryRecords used by these tests."""
    if url is None:
        url = f"https://example{rid}.com/"
    if domain is None:
        domain = f"example{rid}.com"
    return HistoryRecord(
        url=url,
        title=title,
        visit_time=visit_time,
        visit_count=visit_count,
        browser_type=browser_type,
        profile_name=profile_name,
        metadata=metadata,
        domain=domain,
        typed_count=typed_count,
        first_visit_time=first_visit_time,
        transition_type=transition_type,
        visit_duration=visit_duration,
        id=rid,
        device_id=device_id,
    )


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_db() -> _FakeDb:
    return _FakeDb()


@pytest.fixture()
def fake_favicon(qapp) -> _FakeFaviconManager:
    return _FakeFaviconManager()


@pytest.fixture()
def model(qapp, fake_db, fake_favicon) -> HistoryTableModel:
    return HistoryTableModel(fake_db, fake_favicon)


@pytest.fixture(autouse=True)
def _reset_format_time_cache():
    """Module-level ``_time_cache`` accumulates across tests; clear before each."""
    from src.viewmodels import history_viewmodel as hv

    hv._time_cache.clear()
    hv._tz_check_counter[0] = 0
    yield
    hv._time_cache.clear()


# ──────────────────────────────────────────────────────────────────────────
# Pure utility functions
# ──────────────────────────────────────────────────────────────────────────


class TestFormatTime:
    def test_zero_timestamp_returns_empty_string(self) -> None:
        assert _format_time(0) == ""

    def test_returns_yyyy_mm_dd_hh_mm_pattern(self) -> None:
        out = _format_time(1_704_067_200)  # 2024-01-01 UTC
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", out) is not None

    def test_caches_within_same_minute_bucket(self) -> None:
        from src.viewmodels import history_viewmodel as hv

        ts = 1_704_067_200
        first = _format_time(ts)
        # Same minute (within 60s) — must come from the cache, not recomputed.
        assert _format_time(ts + 30) == first
        assert ts // 60 in hv._time_cache

    def test_different_minutes_have_distinct_entries(self) -> None:
        a = _format_time(1_704_067_200)
        b = _format_time(1_704_067_200 + 120)  # +2 minutes
        assert a != b

    def test_invalid_timestamp_falls_back_to_str(self) -> None:
        # OverflowError → except clause returns str(ts) untouched
        out = _format_time(10**18)
        assert out == str(10**18) or re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", out)


class TestFormatTransition:
    def test_none_value_returns_empty_string(self) -> None:
        assert _format_transition(None, "chrome") == ""

    def test_chromium_known_value_uses_chromium_label(self) -> None:
        assert _format_transition(1, "chrome") == "Typed"
        assert _format_transition(0, "edge") == "Link"

    def test_firefox_uses_firefox_label_table(self) -> None:
        # Firefox: 2 = Typed (different mapping than Chromium where 2 = Auto Bookmark)
        assert _format_transition(2, "firefox") == "Typed"
        assert _format_transition(2, "chrome") == "Auto Bookmark"

    def test_firefox_family_browsers_use_firefox_table(self) -> None:
        for bt in ("firefox", "librewolf", "floorp", "waterfox"):
            assert _format_transition(3, bt) == "Bookmark"

    def test_unknown_value_falls_back_to_str(self) -> None:
        assert _format_transition(999, "chrome") == "999"
        assert _format_transition(999, "firefox") == "999"


class TestBrowserDisplayName:
    def test_known_browser_returns_brand_name(self) -> None:
        assert _browser_display_name("chrome") == "Google Chrome"
        assert _browser_display_name("firefox") == "Mozilla Firefox"

    def test_unknown_browser_titlecases(self) -> None:
        assert _browser_display_name("custom_browser") == "Custom_Browser"

    def test_empty_browser_returns_empty(self) -> None:
        # str.title() on "" is "" — the fallback degrades gracefully.
        assert _browser_display_name("") == ""


# ──────────────────────────────────────────────────────────────────────────
# Display getter dispatch table (_DISPLAY_GETTERS)
# ──────────────────────────────────────────────────────────────────────────


class TestDisplayGetters:
    def test_title_uses_title_when_present(self) -> None:
        getter = _DISPLAY_GETTERS["title"]
        rec = _rec(title="My Title", url="https://x")
        assert getter(rec, None) == "My Title"

    def test_title_falls_back_to_url_when_blank(self) -> None:
        getter = _DISPLAY_GETTERS["title"]
        rec = _rec(title="", url="https://fallback")
        assert getter(rec, None) == "https://fallback"

    def test_url_returns_url(self) -> None:
        rec = _rec(url="https://abc/")
        assert _DISPLAY_GETTERS["url"](rec, None) == "https://abc/"

    def test_domain_returns_domain(self) -> None:
        rec = _rec(domain="abc.com")
        assert _DISPLAY_GETTERS["domain"](rec, None) == "abc.com"

    def test_browser_column_returns_empty_string(self) -> None:
        # Column displays an icon, no text.
        rec = _rec(browser_type="chrome")
        assert _DISPLAY_GETTERS["browser"](rec, None) == ""

    def test_visit_count_stringifies(self) -> None:
        rec = _rec(visit_count=42)
        assert _DISPLAY_GETTERS["visit_count"](rec, None) == "42"

    def test_typed_count_none_is_empty_string(self) -> None:
        rec = _rec(typed_count=None)
        assert _DISPLAY_GETTERS["typed_count"](rec, None) == ""

    def test_typed_count_zero_is_string_zero(self) -> None:
        rec = _rec(typed_count=0)
        # str(0) == "0" — *not* falsy-coerced to empty.
        assert _DISPLAY_GETTERS["typed_count"](rec, None) == "0"

    def test_first_visit_time_zero_is_empty_string(self) -> None:
        rec = _rec(first_visit_time=0)
        assert _DISPLAY_GETTERS["first_visit_time"](rec, None) == ""

    def test_first_visit_time_formatted_when_present(self) -> None:
        rec = _rec(first_visit_time=1_704_067_200)
        out = _DISPLAY_GETTERS["first_visit_time"](rec, None)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", out)

    def test_transition_type_uses_browser_specific_table(self) -> None:
        rec = _rec(browser_type="firefox", transition_type=2)
        assert _DISPLAY_GETTERS["transition_type"](rec, None) == "Typed"

    def test_visit_duration_none_is_empty(self) -> None:
        rec = _rec(visit_duration=None)
        assert _DISPLAY_GETTERS["visit_duration"](rec, None) == ""

    def test_visit_duration_formats_one_decimal(self) -> None:
        rec = _rec(visit_duration=12.345)
        assert _DISPLAY_GETTERS["visit_duration"](rec, None) == "12.3s"

    def test_device_name_uses_vm_device_name_map(self, model: HistoryTableModel) -> None:
        model._device_name_map = {7: "Laptop"}
        rec = _rec(device_id=7)
        assert _DISPLAY_GETTERS["device_name"](rec, model) == "Laptop"

    def test_device_name_unknown_id_returns_empty(self, model: HistoryTableModel) -> None:
        rec = _rec(device_id=99)
        assert _DISPLAY_GETTERS["device_name"](rec, model) == ""

    def test_device_name_none_id_returns_empty(self, model: HistoryTableModel) -> None:
        rec = _rec(device_id=None)
        assert _DISPLAY_GETTERS["device_name"](rec, model) == ""


# ──────────────────────────────────────────────────────────────────────────
# Column configuration / row+col counts / header
# ──────────────────────────────────────────────────────────────────────────


class TestColumnConfiguration:
    def test_default_visible_columns_used_when_none(self, model: HistoryTableModel) -> None:
        assert model.get_visible_columns() == DEFAULT_VISIBLE_COLUMNS

    def test_get_visible_columns_returns_a_copy(self, model: HistoryTableModel) -> None:
        cols = model.get_visible_columns()
        cols.append("zzz")
        assert "zzz" not in model.get_visible_columns()

    def test_get_all_columns_is_a_copy(self, model: HistoryTableModel) -> None:
        all_cols = model.get_all_columns()
        all_cols["zzz"] = {}
        assert "zzz" not in model.get_all_columns()
        assert set(ALL_COLUMNS).issubset(set(model.get_all_columns()))

    def test_set_visible_columns_emits_columns_changed_signal(
        self,
        qapp,
        fake_db,
        fake_favicon,
    ) -> None:
        m = HistoryTableModel(fake_db, fake_favicon)
        events: list[bool] = []
        m.columns_changed.connect(lambda: events.append(True))
        m.set_visible_columns(["title", "url", "browser"])
        assert events == [True]
        assert m.get_visible_columns() == ["title", "url", "browser"]

    def test_set_visible_columns_updates_column_count(
        self,
        qapp,
        fake_db,
        fake_favicon,
    ) -> None:
        m = HistoryTableModel(fake_db, fake_favicon)
        m.set_visible_columns(["title", "url"])
        assert m.columnCount() == 2

    def test_custom_visible_columns_drive_column_count(
        self,
        qapp,
        fake_db,
        fake_favicon,
    ) -> None:
        m = HistoryTableModel(fake_db, fake_favicon, visible_columns=["title", "url"])
        assert m.columnCount() == 2
        assert m.get_visible_columns() == ["title", "url"]


class TestRowAndColumnCount:
    def test_row_count_matches_total_count(self, model: HistoryTableModel) -> None:
        assert model.rowCount() == 0
        model._total_count = 17
        assert model.rowCount() == 17

    def test_column_count_default(self, model: HistoryTableModel) -> None:
        assert model.columnCount() == len(DEFAULT_VISIBLE_COLUMNS)


class TestHeaderData:
    def test_display_role_returns_translated_label(self, model: HistoryTableModel) -> None:
        # Section 1 = "url" by default; label is "URL".
        out = model.headerData(1, Qt.Horizontal, Qt.DisplayRole)
        assert out == "URL"

    def test_browser_column_returns_blank_for_display_role(self, model: HistoryTableModel) -> None:
        # Index of browser column in default config:
        col = model.get_visible_columns().index("browser")
        out = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
        assert out == ""  # icon-only column

    def test_browser_column_returns_decoration(self, model: HistoryTableModel) -> None:
        col = model.get_visible_columns().index("browser")
        deco = model.headerData(col, Qt.Horizontal, Qt.DecorationRole)
        # get_browser_icon returns a QIcon (possibly empty if assets missing) — non-None.
        assert deco is not None

    def test_section_out_of_range_returns_none(self, model: HistoryTableModel) -> None:
        assert model.headerData(99, Qt.Horizontal, Qt.DisplayRole) is None

    def test_vertical_header_returns_none(self, model: HistoryTableModel) -> None:
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) is None


# ──────────────────────────────────────────────────────────────────────────
# _apply_reload_result — synchronous core of reload()
# ──────────────────────────────────────────────────────────────────────────


class TestApplyReloadResult:
    def test_count_path_sets_total_count_and_emits(self, model: HistoryTableModel) -> None:
        events: list[tuple[int, bool]] = []
        model.total_count_changed.connect(lambda c, more: events.append((c, more)))

        model._reload_generation = 3
        model._apply_reload_result(generation=3, keyword_index=[], total_count=42, keyword_materialized=False)

        assert model._total_count == 42
        assert model._keyword_materialized is False
        assert events == [(42, False)]

    def test_keyword_materialized_path_stores_index(self, model: HistoryTableModel) -> None:
        idx = [(1, 100), (2, 200), (3, 300)]
        model._reload_generation = 1
        model._apply_reload_result(generation=1, keyword_index=idx, total_count=3, keyword_materialized=True)

        assert model._keyword_materialized is True
        assert model._keyword_index == idx
        assert model._total_count == 3

    def test_zero_count_no_first_page_fetch_scheduled(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        model._reload_generation = 1
        model._apply_reload_result(generation=1, keyword_index=[], total_count=0, keyword_materialized=False)

        # No DB fetch should have fired (the timer would, but we don't pump the loop).
        assert fake_db.get_records_calls == []


# ──────────────────────────────────────────────────────────────────────────
# Reload generation (stale result rejection)
# ──────────────────────────────────────────────────────────────────────────


class TestReloadGeneration:
    def test_on_reload_done_with_stale_generation_is_dropped(self, model: HistoryTableModel) -> None:
        # Bump generation and feed an older generation result; total_count must not change.
        model._reload_generation = 5
        model._total_count = 10

        model._on_reload_done(
            generation=4,  # stale
            keyword_index=[],
            total_count=999,
            keyword_materialized=False,
            bookmarked_urls=set(),
            annotated_urls=set(),
            device_name_map={},
        )

        assert model._total_count == 10  # unchanged

    def test_on_regex_done_with_stale_generation_is_dropped(self, model: HistoryTableModel) -> None:
        model._reload_generation = 5
        model._total_count = 7

        model._on_regex_done(
            generation=4,
            keyword_index=[(1, 100)],
            has_more=False,
            bookmarked_urls=set(),
            annotated_urls=set(),
            device_name_map={},
        )

        assert model._total_count == 7
        assert model._keyword_materialized is False

    def test_on_reload_done_skip_badges_payload_does_not_overwrite_caches(
        self,
        model: HistoryTableModel,
    ) -> None:
        model._bookmarked_urls = {"https://kept/"}
        model._annotated_urls = {"https://also-kept/"}
        model._device_name_map = {1: "device-A"}
        model._reload_generation = 1

        model._on_reload_done(
            generation=1,
            keyword_index=[],
            total_count=0,
            keyword_materialized=False,
            # None payloads from skip_badges path
            bookmarked_urls=None,
            annotated_urls=None,
            device_name_map=None,
        )

        assert model._bookmarked_urls == {"https://kept/"}
        assert model._annotated_urls == {"https://also-kept/"}
        assert model._device_name_map == {1: "device-A"}


# ──────────────────────────────────────────────────────────────────────────
# set_filter / set_hidden_mode
# ──────────────────────────────────────────────────────────────────────────


class TestSetFilter:
    def test_set_filter_assigns_all_fields_and_calls_reload(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(model, "reload", lambda **k: seen.append(k))

        model.set_filter(
            keyword="abc",
            browser_type="firefox",
            date_from=100,
            date_to=200,
            domain_ids=[1, 2],
            excludes=["spam"],
            title_only=True,
            url_only=False,
            use_regex=True,
            bookmarked_only=True,
            has_annotation=True,
            bookmark_tag="work",
            device_ids=[7],
            skip_badges=True,
        )

        assert model._keyword == "abc"
        assert model._browser_type == "firefox"
        assert model._date_from == 100
        assert model._date_to == 200
        assert model._domain_ids == [1, 2]
        assert model._excludes == ["spam"]
        assert model._title_only is True
        assert model._url_only is False
        assert model._use_regex is True
        assert model._bookmarked_only is True
        assert model._has_annotation is True
        assert model._bookmark_tag == "work"
        assert model._device_ids == [7]
        assert seen == [{"skip_badges": True}]

    def test_set_filter_resets_search_state(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-populate state from a previous search.
        monkeypatch.setattr(model, "reload", lambda **k: None)
        model._keyword_materialized = True
        model._keyword_index = [(1, 100)]

        model.reload(skip_badges=False)
        # ``reload`` is patched out for this test; verify set_filter persists the keyword.
        model.set_filter(keyword="new")
        assert model._keyword == "new"


class TestSetHiddenMode:
    def test_no_op_when_unchanged(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = []
        monkeypatch.setattr(model, "reload", lambda **k: seen.append(k))
        model._hidden_mode = False
        model.set_hidden_mode(False)
        assert seen == []  # no reload triggered

    def test_changes_state_and_reloads_with_skip_badges(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(model, "reload", lambda **k: seen.append(k))
        model._hidden_mode = False
        model.set_hidden_mode(True)
        assert model._hidden_mode is True
        assert seen == [{"skip_badges": True}]

    def test_reload_false_skips_reload_call(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = []
        monkeypatch.setattr(model, "reload", lambda **k: seen.append(k))
        model._hidden_mode = False
        model.set_hidden_mode(True, reload=False)
        assert model._hidden_mode is True
        assert seen == []

    def test_set_hidden_ids_triggers_reload(
        self,
        model: HistoryTableModel,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(model, "reload", lambda **k: seen.append(k))
        model.set_hidden_ids({1, 2, 3})
        assert model._hidden_ids == {1, 2, 3}
        assert seen == [{"skip_badges": True}]


# ──────────────────────────────────────────────────────────────────────────
# Page cache + LRU + _fetch_page
# ──────────────────────────────────────────────────────────────────────────


class TestFetchPage:
    def test_fetch_page_zero_uses_offset_zero_no_cursor(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1)]]
        model._total_count = 1

        records = model._fetch_page(0)

        assert len(records) == 1
        assert records[0].id == 1
        assert len(fake_db.get_records_calls) == 1
        call = fake_db.get_records_calls[0]
        assert call["offset"] == 0
        assert call["cursor"] is None
        assert call["limit"] == CACHE_PAGE_SIZE

    def test_fetch_page_one_uses_keyset_cursor_when_prev_cached(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [
            [_rec(rid=10, visit_time=5000)],
            [_rec(rid=20, visit_time=4000)],
        ]
        model._total_count = 2 * CACHE_PAGE_SIZE

        model._fetch_page(0)
        model._fetch_page(1)

        assert len(fake_db.get_records_calls) == 2
        second = fake_db.get_records_calls[1]
        assert second["cursor"] == (5000, 10)
        # Offset is reset to 0 once a cursor is in play.
        assert second["offset"] == 0

    def test_fetch_page_keyword_mode_uses_get_records_by_ids(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        # Materialize the keyword index so _fetch_page picks the IN(ids) branch.
        model._keyword_materialized = True
        model._keyword_index = [(1, 100), (2, 200), (3, 300)]
        model._total_count = 3
        fake_db._records_by_ids_response = [_rec(rid=1), _rec(rid=2), _rec(rid=3)]

        records = model._fetch_page(0)

        assert [r.id for r in records] == [1, 2, 3]
        assert fake_db.get_records_by_ids_calls == [[1, 2, 3]]
        # Must NOT have used get_records in this branch.
        assert fake_db.get_records_calls == []

    def test_fetch_page_populates_vt_cache(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1, visit_time=1111), _rec(rid=2, visit_time=2222)]]
        model._total_count = 2

        model._fetch_page(0)

        assert model._vt_cache.get(0) == 1111
        assert model._vt_cache.get(1) == 2222

    def test_lru_evicts_oldest_page_beyond_max(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        # One record per page is enough to exercise eviction logic.
        fake_db._records_by_call = [[_rec(rid=i + 1)] for i in range(MAX_CACHED_PAGES + 2)]
        model._total_count = (MAX_CACHED_PAGES + 2) * CACHE_PAGE_SIZE

        for page in range(MAX_CACHED_PAGES + 1):
            model._fetch_page(page)

        # After fetching MAX_CACHED_PAGES+1 distinct pages, page 0 is evicted.
        assert 0 not in model._page_cache
        assert MAX_CACHED_PAGES in model._page_cache
        # Cache holds at most MAX_CACHED_PAGES entries.
        assert len(model._page_cache) == MAX_CACHED_PAGES

    def test_lru_move_to_end_on_repeat_access(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=i + 1)] for i in range(MAX_CACHED_PAGES + 1)]
        model._total_count = (MAX_CACHED_PAGES + 1) * CACHE_PAGE_SIZE

        # Fill the cache.
        for page in range(MAX_CACHED_PAGES):
            model._fetch_page(page)
        # Touch page 0 to refresh LRU position.
        model._get_or_fetch_page(0)
        # Fetch a new page → eviction targets the now-oldest (page 1), not page 0.
        model._fetch_page(MAX_CACHED_PAGES)

        assert 0 in model._page_cache
        assert 1 not in model._page_cache


class TestGetRecordAt:
    def test_out_of_range_returns_none(self, model: HistoryTableModel) -> None:
        model._total_count = 0
        assert model._get_record_at(0) is None
        model._total_count = 5
        assert model._get_record_at(-1) is None
        assert model._get_record_at(99) is None

    def test_returns_cached_record_via_fast_path_no_repeat_db_call(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=42)]]
        model._total_count = 1

        first = model._get_record_at(0)
        second = model._get_record_at(0)

        assert first is second
        # The single-row fast cache must short-circuit before touching the DB.
        assert len(fake_db.get_records_calls) == 1

    def test_keyword_mode_uses_records_by_ids(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        model._keyword_materialized = True
        model._keyword_index = [(7, 700)]
        model._total_count = 1
        fake_db._records_by_ids_response = [_rec(rid=7)]

        rec = model._get_record_at(0)

        assert rec is not None
        assert rec.id == 7
        assert fake_db.get_records_by_ids_calls == [[7]]


class TestPeekRecordAt:
    def test_returns_none_when_page_not_cached(self, model: HistoryTableModel) -> None:
        model._total_count = 1000
        # Page is not in cache → None, no DB fetch is triggered.
        assert model.peek_record_at(0) is None

    def test_returns_cached_record_when_page_cached(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=11), _rec(rid=12)]]
        model._total_count = 2
        model._fetch_page(0)
        # peek_record_at must NOT trigger another DB fetch.
        before = len(fake_db.get_records_calls)
        rec = model.peek_record_at(1)
        assert rec is not None
        assert rec.id == 12
        assert len(fake_db.get_records_calls) == before

    def test_out_of_range_returns_none(self, model: HistoryTableModel) -> None:
        model._total_count = 5
        assert model.peek_record_at(-1) is None
        assert model.peek_record_at(99) is None


# ──────────────────────────────────────────────────────────────────────────
# data() role dispatch
# ──────────────────────────────────────────────────────────────────────────


def _populate_one_record(model: HistoryTableModel, fake_db: _FakeDb, rec: HistoryRecord) -> None:
    """Helper: install a single record so ``data()`` can serve it."""
    fake_db._records_by_call = [[rec]]
    model._total_count = 1
    model._fetch_page(0)


class TestDataRoleDispatch:
    def test_invalid_index_returns_none(self, model: HistoryTableModel) -> None:
        assert model.data(QModelIndex(), Qt.DisplayRole) is None

    def test_display_role_title_column(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(title="Page Title"))
        idx = model.index(0, model.get_visible_columns().index("title"))
        assert model.data(idx, Qt.DisplayRole) == "Page Title"

    def test_display_role_visit_count_stringified(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(visit_count=99))
        idx = model.index(0, model.get_visible_columns().index("visit_count"))
        assert model.data(idx, Qt.DisplayRole) == "99"

    def test_user_role_returns_record_object(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        rec = _rec(rid=11, title="UR")
        _populate_one_record(model, fake_db, rec)
        idx = model.index(0, 0)
        assert model.data(idx, Qt.UserRole) is rec

    def test_unknown_role_returns_none(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec())
        # 0xFFFF is an unrecognized role → None.
        assert model.data(model.index(0, 0), 0xFFFF) is None

    def test_text_alignment_role(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec())
        idx = model.index(0, model.get_visible_columns().index("title"))
        align = model.data(idx, Qt.TextAlignmentRole)
        assert isinstance(align, int)
        assert align & int(Qt.AlignVCenter)

    def test_bookmark_role_true_when_url_in_set(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        rec = _rec(url="https://bm/")
        _populate_one_record(model, fake_db, rec)
        model._bookmarked_urls = {"https://bm/"}
        idx = model.index(0, 0)
        assert model.data(idx, BOOKMARK_ROLE) is True

    def test_bookmark_role_false_when_url_not_in_set(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(url="https://bm/"))
        model._bookmarked_urls = {"https://other/"}
        idx = model.index(0, 0)
        assert model.data(idx, BOOKMARK_ROLE) is False

    def test_annotation_role_true_when_url_in_set(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(url="https://ann/"))
        model._annotated_urls = {"https://ann/"}
        idx = model.index(0, 0)
        assert model.data(idx, ANNOTATION_ROLE) is True

    def test_tooltip_for_browser_column_uses_brand_name(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(browser_type="chrome"))
        col = model.get_visible_columns().index("browser")
        tooltip = model.data(model.index(0, col), Qt.ToolTipRole)
        assert tooltip == "Google Chrome"

    def test_tooltip_for_visit_count_includes_number(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(visit_count=7))
        col = model.get_visible_columns().index("visit_count")
        tooltip = model.data(model.index(0, col), Qt.ToolTipRole)
        assert "7" in tooltip

    def test_tooltip_for_url_column_returns_url(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(url="https://tt-url/"))
        col = model.get_visible_columns().index("url")
        assert model.data(model.index(0, col), Qt.ToolTipRole) == "https://tt-url/"

    def test_decoration_role_for_title_uses_favicon_manager(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
    ) -> None:
        _populate_one_record(model, fake_db, _rec(url="https://x/", domain="x.com"))
        col = model.get_visible_columns().index("title")
        deco = model.data(model.index(0, col), Qt.DecorationRole)
        assert isinstance(deco, QPixmap)

    def test_data_returns_none_when_record_missing(self, model: HistoryTableModel) -> None:
        # _total_count=1 but no page fetch source — _fetch_page returns []
        # via the default _records_by_call=None branch (db.records is empty).
        model._total_count = 1
        idx = model.index(0, 0)
        # Empty page → record None → data returns None.
        assert model.data(idx, Qt.DisplayRole) is None


# ──────────────────────────────────────────────────────────────────────────
# get_visit_time_at_row tiered lookup
# ──────────────────────────────────────────────────────────────────────────


class TestGetVisitTimeAtRow:
    def test_out_of_range_returns_none(self, model: HistoryTableModel) -> None:
        model._total_count = 0
        assert model.get_visit_time_at_row(0) is None
        model._total_count = 3
        assert model.get_visit_time_at_row(-1) is None
        assert model.get_visit_time_at_row(99) is None

    def test_keyword_materialized_reads_from_index(self, model: HistoryTableModel) -> None:
        model._keyword_materialized = True
        model._keyword_index = [(1, 100), (2, 200), (3, 300)]
        model._total_count = 3
        assert model.get_visit_time_at_row(1) == 200

    def test_falls_back_to_vt_cache(self, model: HistoryTableModel) -> None:
        model._total_count = 5
        model._vt_cache[3] = 4242
        assert model.get_visit_time_at_row(3) == 4242

    def test_falls_back_to_page_cache_record(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1, visit_time=8888)]]
        model._total_count = 1
        model._fetch_page(0)
        # Clear the lightweight vt_cache so the function must fall through to peek.
        model._vt_cache.clear()
        assert model.get_visit_time_at_row(0) == 8888

    def test_falls_back_to_db_when_uncached(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        model._total_count = 1000
        fake_db._visit_time_response = 12345

        out = model.get_visit_time_at_row(500)

        assert out == 12345
        assert len(fake_db.get_visit_time_calls) == 1
        assert fake_db.get_visit_time_calls[0]["offset"] == 500


# ──────────────────────────────────────────────────────────────────────────
# Regex incremental loading
# ──────────────────────────────────────────────────────────────────────────


class TestRegexLoadMore:
    def test_can_load_more_only_when_regex_active_with_more(self, model: HistoryTableModel) -> None:
        model._use_regex = False
        model._keyword = "abc"
        model._regex_has_more = True
        assert model.can_load_more is False

        model._use_regex = True
        model._keyword = ""
        assert model.can_load_more is False

        model._keyword = "abc"
        model._regex_has_more = False
        assert model.can_load_more is False

        model._regex_has_more = True
        assert model.can_load_more is True

    def test_load_more_appends_matches_and_emits_total_count(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        # Pre-populate state for can_load_more.
        model._use_regex = True
        model._keyword = "ALPHA"
        model._regex_has_more = True

        # Two candidates from DB; one matches "ALPHA" (case-insensitive).
        fake_db._records_by_call = [[_rec(rid=1, title="alpha thing"), _rec(rid=2, title="zzz")]]

        events: list[tuple[int, bool]] = []
        model.total_count_changed.connect(lambda c, more: events.append((c, more)))

        ok = model.load_more_regex()

        assert ok is True
        assert model._keyword_index == [(1, _rec(rid=1).visit_time)]
        assert events and events[-1][0] == 1

    def test_load_more_returns_false_when_no_more(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        model._use_regex = True
        model._keyword = "abc"
        model._regex_has_more = False
        assert model.load_more_regex() is False
        assert fake_db.get_records_calls == []

    def test_invalid_regex_disables_has_more(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        model._use_regex = True
        model._keyword = "(unclosed"
        model._regex_has_more = True
        # Should not raise; should leave the keyword index untouched and turn off has_more.
        ok = model.load_more_regex()
        assert ok is False
        assert model._regex_has_more is False

    def test_full_batch_keeps_has_more_true(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Avoid building 5000 records — patch the constant to a small ceiling.
        from src.viewmodels import history_viewmodel as hv

        monkeypatch.setattr(hv, "REGEX_SCAN_BATCH", 3)
        model._use_regex = True
        model._keyword = "ALPHA"
        model._regex_has_more = True
        fake_db._records_by_call = [[_rec(rid=i, title="alpha") for i in range(1, 4)]]

        ok = model.load_more_regex()

        assert ok is True
        assert model._regex_has_more is True


# ──────────────────────────────────────────────────────────────────────────
# Badges / icons / favicon updates
# ──────────────────────────────────────────────────────────────────────────


class TestBadgeAndIconRefresh:
    def test_invalidate_badge_cache_refreshes_url_sets(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db.bookmarked_urls = {"https://b/"}
        fake_db.annotated_urls = {"https://a/"}
        # Empty model → invalidate just refreshes caches and returns.
        model.invalidate_badge_cache()
        assert model._bookmarked_urls == {"https://b/"}
        assert model._annotated_urls == {"https://a/"}

    def test_invalidate_badge_cache_emits_data_changed_for_visible_rows(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1)]]
        model._total_count = 1
        model._fetch_page(0)

        events = []
        model.dataChanged.connect(lambda tl, br, roles: events.append((tl.row(), br.row(), list(roles))))
        model.invalidate_badge_cache()
        # At least one dataChanged emission with bookmark/annotation roles.
        assert events
        roles = events[-1][2]
        assert BOOKMARK_ROLE in roles
        assert ANNOTATION_ROLE in roles

    def test_refresh_icons_returns_silently_when_empty(self, model: HistoryTableModel) -> None:
        model._total_count = 0
        # Should not raise.
        model.refresh_icons()

    def test_refresh_icons_emits_decoration_role_for_visible_range(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1)]]
        model._total_count = 1
        model._fetch_page(0)
        events = []
        model.dataChanged.connect(lambda tl, br, roles: events.append(list(roles)))
        model.refresh_icons()
        assert events
        assert any(Qt.DecorationRole in roles for roles in events)


class TestOnFaviconsUpdated:
    def test_no_op_when_no_records(self, model: HistoryTableModel) -> None:
        events = []
        model.dataChanged.connect(lambda tl, br, roles: events.append(True))
        model._on_favicons_updated({"any.com"})
        assert events == []

    def test_no_op_when_empty_domain_set(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        fake_db._records_by_call = [[_rec(rid=1)]]
        model._total_count = 1
        model._fetch_page(0)
        events = []
        model.dataChanged.connect(lambda tl, br, roles: events.append(True))
        model._on_favicons_updated(set())
        assert events == []

    def test_emits_single_range_for_contiguous_affected_rows(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        records = [
            _rec(rid=1, domain="m.com"),
            _rec(rid=2, domain="m.com"),
            _rec(rid=3, domain="m.com"),
        ]
        fake_db._records_by_call = [records]
        model._total_count = 3
        model._fetch_page(0)

        ranges: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles: ranges.append((tl.row(), br.row())))
        model._on_favicons_updated({"m.com"})

        assert ranges == [(0, 2)]

    def test_emits_separate_ranges_for_disjoint_rows(
        self,
        model: HistoryTableModel,
        fake_db: _FakeDb,
    ) -> None:
        records = [
            _rec(rid=1, domain="hit.com"),
            _rec(rid=2, domain="miss.com"),
            _rec(rid=3, domain="hit.com"),
        ]
        fake_db._records_by_call = [records]
        model._total_count = 3
        model._fetch_page(0)

        ranges: list[tuple[int, int]] = []
        model.dataChanged.connect(lambda tl, br, roles: ranges.append((tl.row(), br.row())))
        model._on_favicons_updated({"hit.com"})

        assert ranges == [(0, 0), (2, 2)]


# ──────────────────────────────────────────────────────────────────────────
# Prefetch debounce
# ──────────────────────────────────────────────────────────────────────────


class TestPrefetchDebounce:
    def test_schedule_prefetch_starts_timer_and_buffers_records(
        self,
        model: HistoryTableModel,
    ) -> None:
        recs = [_rec(rid=1), _rec(rid=2)]
        model._schedule_prefetch(recs)
        assert model._prefetch_pending == recs
        assert model._prefetch_timer.isActive() is True

    def test_flush_prefetch_calls_favicon_manager(
        self,
        model: HistoryTableModel,
        fake_favicon: _FakeFaviconManager,
    ) -> None:
        recs = [_rec(rid=1), _rec(rid=2)]
        model._prefetch_pending = list(recs)
        model._flush_prefetch()
        assert fake_favicon.prefetched == recs
        assert model._prefetch_pending == []

    def test_flush_prefetch_no_op_when_empty(
        self,
        model: HistoryTableModel,
        fake_favicon: _FakeFaviconManager,
    ) -> None:
        model._prefetch_pending = []
        model._flush_prefetch()
        assert fake_favicon.prefetched == []
        assert fake_favicon.prefetch_calls == 0

    def test_schedule_prefetch_coalesces_multiple_calls(
        self,
        model: HistoryTableModel,
    ) -> None:
        model._schedule_prefetch([_rec(rid=1)])
        model._schedule_prefetch([_rec(rid=2)])
        assert [r.id for r in model._prefetch_pending] == [1, 2]
        # Timer is restarted on each call but remains a single pending fire.
        assert model._prefetch_timer.isActive() is True


# ──────────────────────────────────────────────────────────────────────────
# is_filtered / total_count properties
# ──────────────────────────────────────────────────────────────────────────


class TestModelProperties:
    def test_is_filtered_only_true_when_keyword_set(self, model: HistoryTableModel) -> None:
        assert model.is_filtered is False
        model._keyword = "x"
        assert model.is_filtered is True

    def test_total_count_reflects_internal_state(self, model: HistoryTableModel) -> None:
        model._total_count = 5
        assert model.total_count == 5


# ──────────────────────────────────────────────────────────────────────────
# HistoryViewModel public API
# ──────────────────────────────────────────────────────────────────────────


class TestHistoryViewModelAPI:
    def test_search_propagates_params_to_table_model(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vm = HistoryViewModel(fake_db, fake_favicon)
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(vm.table_model, "set_filter", lambda *a, **k: seen.append(k))

        vm.search(
            keyword="hello",
            browser_type="firefox",
            date_from=10,
            date_to=20,
            domain_ids=[1],
            excludes=["junk"],
            title_only=True,
            url_only=False,
            use_regex=True,
            bookmarked_only=False,
            has_annotation=False,
            bookmark_tag="",
            device_ids=None,
            skip_badges=False,
        )

        assert vm._use_regex is True
        assert seen[0]["use_regex"] is True
        assert seen[0]["domain_ids"] == [1]
        assert seen[0]["excludes"] == ["junk"]
        assert seen[0]["title_only"] is True

    def test_load_more_only_runs_in_regex_mode(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vm = HistoryViewModel(fake_db, fake_favicon)
        called = []
        monkeypatch.setattr(vm.table_model, "load_more_regex", lambda: called.append(True) or True)

        vm._use_regex = False
        assert vm.load_more() is False
        assert called == []

        vm._use_regex = True
        assert vm.load_more() is True
        assert called == [True]

    def test_set_hidden_ids_pre_init_writes_directly(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vm = HistoryViewModel(fake_db, fake_favicon)
        monkeypatch.setattr(
            vm.table_model,
            "set_hidden_ids",
            lambda *_a, **_k: pytest.fail("must not call set_hidden_ids before initialize"),
        )
        vm.set_hidden_ids({4, 5})
        assert vm.table_model._hidden_ids == {4, 5}

    def test_set_hidden_ids_post_init_calls_table_model(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vm = HistoryViewModel(fake_db, fake_favicon)
        vm._initialized = True  # simulate post-initialize state
        seen: list[set[int]] = []
        monkeypatch.setattr(vm.table_model, "set_hidden_ids", lambda ids: seen.append(set(ids)))
        vm.set_hidden_ids({1, 2})
        assert seen == [{1, 2}]

    def test_set_hidden_mode_delegates_to_table_model(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        vm = HistoryViewModel(fake_db, fake_favicon)
        seen: list[tuple[bool, bool]] = []
        monkeypatch.setattr(
            vm.table_model,
            "set_hidden_mode",
            lambda enabled, reload=True: seen.append((enabled, reload)),
        )
        vm.set_hidden_mode(True, reload=False)
        assert seen == [(True, False)]

    def test_resolve_passthrough(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
    ) -> None:
        fake_db.domain_id_map = {"example.com": 1, "site.com": 7}
        fake_db.device_id_map = {"laptop": 99}

        vm = HistoryViewModel(fake_db, fake_favicon)

        assert vm.resolve_domain_ids(["example.com", "site.com"]) == [1, 7]
        assert vm.resolve_device_ids("laptop") == [99]

    def test_refresh_emits_filter_signals(
        self,
        qapp,
        fake_db: _FakeDb,
        fake_favicon: _FakeFaviconManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_db.browser_types = ["chrome", "firefox"]
        fake_db.devices = [{"name": "Desktop"}, {"name": "Phone"}, {"name": ""}]
        fake_db.tags = ["work", "fun"]

        vm = HistoryViewModel(fake_db, fake_favicon)
        # Avoid spinning up a real reload thread.
        monkeypatch.setattr(vm.table_model, "reload", lambda *a, **k: None)

        browsers: list[list[str]] = []
        devices: list[list[str]] = []
        tags: list[list[str]] = []
        vm.browser_list_changed.connect(lambda x: browsers.append(list(x)))
        vm.device_list_changed.connect(lambda x: devices.append(list(x)))
        vm.tag_list_changed.connect(lambda x: tags.append(list(x)))

        vm.refresh()

        assert browsers == [["chrome", "firefox"]]
        # Empty-name device dropped from emission.
        assert devices == [["Desktop", "Phone"]]
        assert tags == [["work", "fun"]]


# ──────────────────────────────────────────────────────────────────────────
# _ReloadWorker (synchronous run)
# ──────────────────────────────────────────────────────────────────────────


def _capture_done(signal):
    """Connect a list-collector to a Qt ``done`` signal and return it."""
    captured = []
    signal.connect(lambda *args: captured.append(args))
    return captured


def _build_params(**overrides):
    """Return the ``params`` dict the workers expect, with sensible defaults."""
    p = {
        "keyword": "",
        "browser_type": "",
        "date_from": None,
        "date_to": None,
        "excluded_ids": frozenset(),
        "domain_ids": None,
        "excludes": None,
        "title_only": False,
        "url_only": False,
        "bookmarked_only": False,
        "has_annotation": False,
        "bookmark_tag": "",
        "device_ids": None,
        "hidden_only": False,
    }
    p.update(overrides)
    return p


class TestReloadWorker:
    def test_count_path_when_no_keyword(self, qapp, fake_db: _FakeDb) -> None:
        fake_db._filtered_count = 17
        worker = _ReloadWorker(fake_db, _build_params(), use_id_index=False, generation=2)
        captured = _capture_done(worker.done)

        worker.run()

        assert len(captured) == 1
        gen, idx, total, materialized, bm, ann, dev = captured[0]
        assert gen == 2
        assert idx == []
        assert total == 17
        assert materialized is False
        assert bm == set()
        assert ann == set()
        assert dev == {}

    def test_id_index_path_when_keyword(self, qapp, fake_db: _FakeDb) -> None:
        fake_db._filtered_id_times = [(1, 100), (2, 200)]
        worker = _ReloadWorker(
            fake_db,
            _build_params(keyword="abc"),
            use_id_index=True,
            generation=3,
        )
        captured = _capture_done(worker.done)

        worker.run()

        assert len(captured) == 1
        gen, idx, total, materialized, *_ = captured[0]
        assert gen == 3
        assert idx == [(1, 100), (2, 200)]
        assert total == 2
        assert materialized is True

    def test_skip_badges_emits_none_payloads(self, qapp, fake_db: _FakeDb) -> None:
        worker = _ReloadWorker(
            fake_db,
            _build_params(),
            use_id_index=False,
            generation=1,
            skip_badges=True,
        )
        captured = _capture_done(worker.done)

        worker.run()

        _gen, _idx, _total, _mat, bm, ann, dev = captured[0]
        # skip_badges → None placeholders so the slot leaves the existing caches alone.
        assert bm is None
        assert ann is None
        assert dev is None
        # And the helpers should NOT have been queried.
        assert fake_db.get_bookmarked_urls_calls == 0
        assert fake_db.get_annotated_urls_calls == 0
        assert fake_db.get_device_name_map_calls == 0

    def test_db_exception_emits_safe_empty_payload(self, qapp, fake_db: _FakeDb) -> None:
        fake_db._raise_on = {"get_filtered_count"}
        worker = _ReloadWorker(fake_db, _build_params(), use_id_index=False, generation=9)
        captured = _capture_done(worker.done)

        worker.run()

        gen, idx, total, materialized, bm, ann, dev = captured[0]
        assert gen == 9
        assert idx == []
        assert total == 0
        assert materialized is False
        assert bm == set()
        assert ann == set()
        assert dev == {}


class TestRegexWorker:
    def test_compiles_and_filters_matches(self, qapp, fake_db: _FakeDb) -> None:
        fake_db.records = [_rec(rid=1, title="alpha"), _rec(rid=2, title="zzz"), _rec(rid=3, url="https://alpha")]
        worker = _RegexWorker(fake_db, _build_params(keyword="ALPHA"), generation=1)
        captured = _capture_done(worker.done)

        worker.run()

        gen, idx, has_more, *_ = captured[0]
        assert gen == 1
        # Records 1 and 3 match (case-insensitive); record 2 does not.
        assert sorted(i for i, _t in idx) == [1, 3]
        # Two candidates < REGEX_SCAN_BATCH → no more.
        assert has_more is False

    def test_invalid_regex_emits_empty_index(self, qapp, fake_db: _FakeDb) -> None:
        worker = _RegexWorker(fake_db, _build_params(keyword="(broken"), generation=2)
        captured = _capture_done(worker.done)

        worker.run()

        _gen, idx, has_more, bm, ann, dev = captured[0]
        assert idx == []
        assert has_more is False
        # On the invalid-regex branch the worker returns *placeholder* set/dict — never None.
        assert bm == set()
        assert ann == set()
        assert dev == {}

    def test_title_only_filter_skips_url_matches(self, qapp, fake_db: _FakeDb) -> None:
        fake_db.records = [
            _rec(rid=1, title="ALPHA", url="https://x/"),
            _rec(rid=2, title="zzz", url="https://alpha-only-in-url/"),
        ]
        worker = _RegexWorker(fake_db, _build_params(keyword="ALPHA", title_only=True), generation=1)
        captured = _capture_done(worker.done)

        worker.run()

        _gen, idx, _has_more, *_ = captured[0]
        assert [i for i, _t in idx] == [1]

    def test_url_only_filter_skips_title_matches(self, qapp, fake_db: _FakeDb) -> None:
        fake_db.records = [
            _rec(rid=1, title="ALPHA", url="https://no-match/"),
            _rec(rid=2, title="zzz", url="https://alpha-only-in-url/"),
        ]
        worker = _RegexWorker(fake_db, _build_params(keyword="alpha", url_only=True), generation=1)
        captured = _capture_done(worker.done)

        worker.run()

        _gen, idx, *_ = captured[0]
        assert [i for i, _t in idx] == [2]

    def test_full_batch_signals_has_more(
        self,
        qapp,
        fake_db: _FakeDb,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.viewmodels import history_viewmodel as hv

        # Lower the batch ceiling so we can simulate "DB returned a full batch".
        monkeypatch.setattr(hv, "REGEX_SCAN_BATCH", 2)
        fake_db.records = [_rec(rid=1, title="alpha"), _rec(rid=2, title="alpha")]
        worker = _RegexWorker(fake_db, _build_params(keyword="alpha"), generation=1)
        captured = _capture_done(worker.done)

        worker.run()

        _gen, _idx, has_more, *_ = captured[0]
        assert has_more is True

    def test_db_exception_emits_safe_empty_payload(self, qapp, fake_db: _FakeDb) -> None:
        fake_db._raise_on = {"get_records"}
        worker = _RegexWorker(fake_db, _build_params(keyword="abc"), generation=1)
        captured = _capture_done(worker.done)

        worker.run()

        _gen, idx, has_more, bm, ann, dev = captured[0]
        assert idx == []
        assert has_more is False
        assert bm == set()
        assert ann == set()
        assert dev == {}
