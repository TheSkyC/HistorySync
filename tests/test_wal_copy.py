# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for SQLite WAL-safe copy (``copy_db_with_wal``) and ``_close_quietly``.

Covers:
  - Main file copied successfully
  - Copied DB is fully readable
  - Missing -wal / -shm files do not raise
  - WAL file is copied when present
  - _close_quietly handles None and already-closed connections
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from src.services.extractors.base_extractor import _close_quietly, copy_db_with_wal

# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════


def _create_db(path: Path, n_rows: int = 50) -> Path:
    """Create a minimal SQLite DB with *n_rows* rows."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"val{i}") for i in range(n_rows)])
    conn.commit()
    conn.close()
    return path


# ══════════════════════════════════════════════════════════════
# copy_db_with_wal
# ══════════════════════════════════════════════════════════════


class TestCopyDbWithWal:
    def test_copy_main_file_exists(self, tmp_path: Path):
        src = _create_db(tmp_path / "src.db")
        dst = tmp_path / "dst.db"
        copy_db_with_wal(src, dst)
        assert dst.exists()

    def test_copied_db_is_readable(self, tmp_path: Path):
        src = _create_db(tmp_path / "src.db")
        dst = tmp_path / "dst.db"
        copy_db_with_wal(src, dst)
        conn = sqlite3.connect(str(dst))
        count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        conn.close()
        assert count == 50

    def test_missing_wal_and_shm_do_not_raise(self, tmp_path: Path):
        src = _create_db(tmp_path / "src.db")
        # Ensure no side-car files exist.
        for suffix in ("-wal", "-shm"):
            side = src.with_name(src.name + suffix)
            if side.exists():
                side.unlink()
        dst = tmp_path / "dst.db"
        copy_db_with_wal(src, dst)  # must not raise
        assert dst.exists()

    def test_wal_file_copied_when_present(self, tmp_path: Path):
        src = _create_db(tmp_path / "src.db")
        wal = src.with_name(src.name + "-wal")
        wal.write_bytes(b"WAL_CONTENT")
        dst = tmp_path / "dst.db"
        copy_db_with_wal(src, dst)
        dst_wal = dst.with_name(dst.name + "-wal")
        assert dst_wal.exists()
        assert dst_wal.read_bytes() == b"WAL_CONTENT"


# ══════════════════════════════════════════════════════════════
# _close_quietly
# ══════════════════════════════════════════════════════════════


class TestCloseQuietly:
    def test_none_does_not_raise(self):
        _close_quietly(None)

    def test_already_closed_does_not_raise(self):
        conn = sqlite3.connect(":memory:")
        conn.close()
        _close_quietly(conn)  # second close must be silent
