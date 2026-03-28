# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest

# ── Path setup ────────────────────────────────────────────────
_HERE = Path(__file__).parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models.history_record import HistoryRecord
from src.services.local_db import LocalDatabase

# ══════════════════════════════════════════════════════════════
# Temporary directory / file fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Return a temporary directory (pytest-managed)."""
    return tmp_path


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary SQLite database file."""
    return tmp_path / "test.db"


# ══════════════════════════════════════════════════════════════
# LocalDatabase fixture
# ══════════════════════════════════════════════════════════════


@pytest.fixture()
def local_db(db_path: Path) -> LocalDatabase:
    """Provide an open LocalDatabase; close automatically after the test."""
    db = LocalDatabase(db_path)
    yield db
    db.close()


# ══════════════════════════════════════════════════════════════
# HistoryRecord factory
# ══════════════════════════════════════════════════════════════


def make_record(
    url: str = "https://example.com",
    title: str = "Example",
    visit_time: int = 1_704_067_200,
    visit_count: int = 1,
    browser_type: str = "chrome",
    profile_name: str = "Default",
    metadata: str = "",
) -> HistoryRecord:
    """Construct a ``HistoryRecord`` with convenient defaults."""
    return HistoryRecord(
        url=url,
        title=title,
        visit_time=visit_time,
        visit_count=visit_count,
        browser_type=browser_type,
        profile_name=profile_name,
        metadata=metadata,
    )


@pytest.fixture()
def make_rec():
    """Expose the ``make_record`` factory as a pytest fixture."""
    return make_record


# ══════════════════════════════════════════════════════════════
# SQLite helper utilities
# ══════════════════════════════════════════════════════════════


def create_chromium_db(path: Path, rows: list[tuple]) -> None:
    """
    Create a minimal Chromium *History* SQLite database.

    *rows* - list of ``(url, title, last_visit_time_chromium_us, visit_count)``.
    Drops and recreates the ``urls`` table so the helper is idempotent within
    a single test.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TABLE IF EXISTS urls")
    conn.execute(
        """
        CREATE TABLE urls (
            id              INTEGER PRIMARY KEY,
            url             TEXT,
            title           TEXT,
            last_visit_time INTEGER,
            visit_count     INTEGER,
            typed_count     INTEGER DEFAULT 0
        )
        """
    )
    conn.executemany(
        "INSERT INTO urls (url, title, last_visit_time, visit_count) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def create_firefox_db(path: Path, rows: list[tuple]) -> None:
    """
    Create a minimal Firefox *places.sqlite* database.

    *rows* - list of
    ``(url, title, last_visit_date_prtime, visit_count, description)``.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE moz_places (
            id              INTEGER PRIMARY KEY,
            url             TEXT,
            title           TEXT,
            last_visit_date INTEGER,
            visit_count     INTEGER,
            hidden          INTEGER DEFAULT 0,
            description     TEXT,
            typed           INTEGER DEFAULT 0
        )
        """
    )
    conn.executemany(
        "INSERT INTO moz_places (url, title, last_visit_date, visit_count, description) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def chromium_db_factory(tmp_path: Path):
    """
    Return a callable ``(rows) -> Path`` that creates a fresh Chromium
    *History* DB inside the test's temp directory.
    """
    counter = {"n": 0}

    def _factory(rows: list[tuple] | None = None, name: str = "History") -> Path:
        counter["n"] += 1
        path = tmp_path / f"{name}_{counter['n']}"
        create_chromium_db(path, rows or [])
        return path

    return _factory


@pytest.fixture()
def firefox_db_factory(tmp_path: Path):
    """
    Return a callable ``(rows) -> Path`` that creates a fresh Firefox
    *places.sqlite* inside a dedicated sub-directory.
    """
    counter = {"n": 0}

    def _factory(rows: list[tuple] | None = None) -> Path:
        counter["n"] += 1
        profile_dir = tmp_path / f"ff_profile_{counter['n']}"
        profile_dir.mkdir()
        path = profile_dir / "places.sqlite"
        create_firefox_db(path, rows or [])
        return path

    return _factory
