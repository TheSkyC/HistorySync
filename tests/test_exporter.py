# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json

import pytest

from src.models.history_record import HistoryRecord
from src.services.exporter import (
    ALL_COLUMNS,
    Exporter,
    ResolvedExportParams,
    _extract_root_domain,
    _record_to_row,
)
from tests.conftest import make_record


class TestRecordToRow:
    """Test _record_to_row pure function."""

    def test_all_columns_present(self):
        """All columns are present in output."""
        record = make_record()
        row = _record_to_row(record, ALL_COLUMNS)
        for col in ALL_COLUMNS:
            assert col in row

    def test_visit_time_formatted_as_utc_string(self):
        """visit_time is formatted as UTC string."""
        record = make_record(visit_time=1704067200)  # 2024-01-01 00:00:00 UTC
        row = _record_to_row(record, ["visit_time"])
        assert "2024-01-01" in row["visit_time"]
        assert "UTC" in row["visit_time"]

    def test_domain_extracted_from_url(self):
        """domain is extracted from URL."""
        record = make_record(url="https://www.github.com/foo")
        row = _record_to_row(record, ["domain"])
        assert row["domain"] == "github.com"

    def test_device_name_resolved_from_map(self):
        """device_name is resolved from device_name_map."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            device_id=1,
        )
        row = _record_to_row(record, ["device_name"], device_name_map={1: "MyPC"})
        assert row["device_name"] == "MyPC"

    def test_device_name_empty_when_no_map(self):
        """device_name is empty when no device_name_map provided."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            device_id=1,
        )
        row = _record_to_row(record, ["device_name"])
        assert row["device_name"] == ""

    def test_device_name_empty_when_device_id_none(self):
        """device_name is empty when device_id is None."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            device_id=None,
        )
        row = _record_to_row(record, ["device_name"])
        assert row["device_name"] == ""

    def test_column_subset_respected(self):
        """Only requested columns are in output."""
        record = make_record()
        row = _record_to_row(record, ["url", "title"])
        assert set(row.keys()) == {"url", "title"}

    def test_transition_type_mapped_to_label(self):
        """transition_type int is mapped to label."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            transition_type=1,
        )
        row = _record_to_row(record, ["transition_type"])
        assert row["transition_type"] == "Typed"

    def test_transition_type_unknown_int_as_string(self):
        """Unknown transition_type is converted to string."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            transition_type=99,
        )
        row = _record_to_row(record, ["transition_type"])
        assert row["transition_type"] == "99"

    def test_transition_type_none_is_none(self):
        """transition_type None stays None."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            transition_type=None,
        )
        row = _record_to_row(record, ["transition_type"])
        assert row["transition_type"] is None

    def test_first_visit_time_formatted(self):
        """first_visit_time is formatted as UTC string."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            first_visit_time=1704067200,
        )
        row = _record_to_row(record, ["first_visit_time"])
        assert "2024-01-01" in row["first_visit_time"]

    def test_first_visit_time_none_is_none(self):
        """first_visit_time None stays None."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            first_visit_time=None,
        )
        row = _record_to_row(record, ["first_visit_time"])
        assert row["first_visit_time"] is None

    def test_visit_duration_rounded(self):
        """visit_duration is rounded to 2 decimal places."""
        record = HistoryRecord(
            url="https://example.com",
            title="Example",
            visit_time=1704067200,
            visit_count=1,
            browser_type="chrome",
            profile_name="Default",
            visit_duration=3.14159,
        )
        row = _record_to_row(record, ["visit_duration"])
        assert row["visit_duration"] == 3.14


class TestExtractRootDomain:
    """Test _extract_root_domain function."""

    def test_simple_domain(self):
        """Simple domain is returned as-is."""
        assert _extract_root_domain("example.com") == "example.com"

    def test_subdomain_stripped(self):
        """Subdomain is stripped."""
        assert _extract_root_domain("blog.example.com") == "example.com"

    def test_second_level_tld_preserved(self):
        """Second-level TLD like co.uk is preserved."""
        assert _extract_root_domain("example.co.uk") == "example.co.uk"

    def test_empty_returns_empty(self):
        """Empty string returns empty string."""
        assert _extract_root_domain("") == ""


class TestCsvExport:
    """Test CSV export."""

    def test_csv_export_creates_file(self, local_db, tmp_path):
        """CSV export creates output file."""
        local_db.upsert_records([make_record(url="https://a.com", title="A")])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.csv"
        params = ResolvedExportParams(output_path=output_path, fmt="csv")
        count = exporter.export(params)
        assert output_path.exists()
        assert count == 1

    def test_csv_export_row_count(self, local_db, tmp_path):
        """CSV export returns correct row count."""
        for i in range(5):
            local_db.upsert_records([make_record(url=f"https://example{i}.com")])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.csv"
        params = ResolvedExportParams(output_path=output_path, fmt="csv")
        count = exporter.export(params)
        assert count == 5

    def test_csv_has_header_row(self, local_db, tmp_path):
        """CSV has header row."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.csv"
        params = ResolvedExportParams(output_path=output_path, fmt="csv")
        exporter.export(params)
        content = output_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) >= 2  # Header + at least 1 data row
        assert "url" in lines[0].lower() or "title" in lines[0].lower()

    def test_csv_column_subset(self, local_db, tmp_path):
        """CSV respects column subset."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.csv"
        params = ResolvedExportParams(output_path=output_path, fmt="csv", columns=["url", "title"])
        exporter.export(params)
        content = output_path.read_text()
        lines = content.strip().split("\n")
        # Header should only have url and title
        assert "url" in lines[0].lower()
        assert "title" in lines[0].lower()

    def test_csv_cancel_check_aborts(self, local_db, tmp_path):
        """cancel_check returning True aborts export."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.csv"
        params = ResolvedExportParams(output_path=output_path, fmt="csv")
        count = exporter.export(params, cancel_check=lambda: True)
        assert count == 0
        assert not output_path.exists()


class TestJsonExport:
    """Test JSON export."""

    def test_json_export_creates_file(self, local_db, tmp_path):
        """JSON export creates output file."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(output_path=output_path, fmt="json")
        exporter.export(params)
        assert output_path.exists()

    def test_json_export_is_valid_json(self, local_db, tmp_path):
        """JSON export is valid JSON."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(output_path=output_path, fmt="json")
        exporter.export(params)
        data = json.loads(output_path.read_text())
        assert isinstance(data, list)

    def test_json_export_row_count(self, local_db, tmp_path):
        """JSON export row count matches."""
        for i in range(5):
            local_db.upsert_records([make_record(url=f"https://example{i}.com")])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(output_path=output_path, fmt="json")
        count = exporter.export(params)
        data = json.loads(output_path.read_text())
        assert len(data) == 5
        assert count == 5

    def test_json_export_contains_expected_fields(self, local_db, tmp_path):
        """JSON export contains expected fields."""
        local_db.upsert_records([make_record(url="https://example.com")])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(output_path=output_path, fmt="json")
        exporter.export(params)
        data = json.loads(output_path.read_text())
        assert len(data) > 0
        assert "url" in data[0]


pytestmark_pyside6 = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)


class TestHtmlExport:
    """Test HTML export (requires PySide6 for icon_helper)."""

    @pytestmark_pyside6
    def test_html_export_creates_file(self, local_db, tmp_path):
        """HTML export creates output file."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.html"
        params = ResolvedExportParams(output_path=output_path, fmt="html")
        exporter.export(params)
        assert output_path.exists()

    @pytestmark_pyside6
    def test_html_export_contains_data_marker(self, local_db, tmp_path):
        """HTML export contains data injection marker."""
        local_db.upsert_records([make_record()])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.html"
        params = ResolvedExportParams(output_path=output_path, fmt="html")
        exporter.export(params)
        content = output_path.read_text(encoding="utf-8", errors="ignore")
        assert "window.REPORT_DATA" in content or "REPORT_DATA" in content


class TestRegexExport:
    """Test regex-based export."""

    def test_regex_export_filters_records(self, local_db, tmp_path):
        """Regex export filters records correctly."""
        local_db.upsert_records(
            [
                make_record(url="https://github.com/foo"),
                make_record(url="https://example.com/bar"),
            ]
        )
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(
            output_path=output_path,
            fmt="json",
            keyword="^https://github",
            use_regex=True,
        )
        count = exporter.export(params)
        data = json.loads(output_path.read_text())
        assert count == 1
        assert len(data) == 1
        assert "github.com" in data[0]["url"]


class TestExporterProgressCallback:
    """Test progress callback."""

    def test_progress_callback_called(self, local_db, tmp_path):
        """Progress callback is called during export."""
        for i in range(10):
            local_db.upsert_records([make_record(url=f"https://example{i}.com")])
        exporter = Exporter(local_db)
        output_path = tmp_path / "export.json"
        params = ResolvedExportParams(output_path=output_path, fmt="json")

        calls = []

        def progress_cb(current, total):
            calls.append((current, total))

        exporter.export(params, progress_callback=progress_cb)
        assert len(calls) > 0
