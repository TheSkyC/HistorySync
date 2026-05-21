# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import time

from src.utils.logger import get_logger

from ._helpers import _escape_like

log = get_logger("local_db")


class _DevicesMixin:
    """Registry of remote devices that have written to this database."""

    def upsert_device(
        self,
        uuid: str,
        name: str,
        plat: str | None = None,
        app_version: str | None = None,
    ) -> int:
        """Insert or update a device row by UUID. Returns devices.id."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                INSERT INTO devices(uuid, name, platform, app_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    name        = excluded.name,
                    platform    = COALESCE(excluded.platform, platform),
                    app_version = COALESCE(excluded.app_version, app_version)
                """,
                (uuid, name, plat, app_version),
            )
            row = conn.execute("SELECT id FROM devices WHERE uuid = ?", (uuid,)).fetchone()
        return row[0]

    def get_all_devices(self) -> list[dict]:
        """Return all device rows as plain dicts, newest first."""
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at "
                "FROM devices ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_device_by_uuid(self, uuid: str) -> dict | None:
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at FROM devices WHERE uuid = ?",
                (uuid,),
            ).fetchone()
        return dict(row) if row else None

    def get_device_by_id(self, device_id: int) -> dict | None:
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT id, uuid, name, platform, app_version, last_sync_at, created_at FROM devices WHERE id = ?",
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_device(self, device_id: int, new_name: str) -> None:
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute("UPDATE devices SET name = ? WHERE id = ?", (new_name, device_id))

    def update_device_last_sync(self, device_id: int) -> None:
        with self._conn() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE devices SET last_sync_at = ? WHERE id = ?",
                (int(time.time()), device_id),
            )

    def merge_device_records(self, from_id: int, to_id: int) -> int:
        """Re-assign all history rows from *from_id* to *to_id*. Returns rows updated."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
            cur = conn.execute(
                "UPDATE history SET device_id = ? WHERE device_id = ?",
                (to_id, from_id),
            )
            return cur.rowcount

    def delete_device(self, device_id: int) -> None:
        """Remove a device row; history rows get device_id=NULL."""
        with self._conn() as conn:  # type: ignore[attr-defined]
            self._ensure_fts_triggers(conn)  # type: ignore[attr-defined]
            conn.execute("UPDATE history SET device_id = NULL WHERE device_id = ?", (device_id,))
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def get_device_name_map(self) -> dict[int, str]:
        """Return {device_id: device_name} for all known devices."""
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT id, name FROM devices").fetchall()
        return {r[0]: r[1] for r in rows}

    def resolve_device_ids(self, name_or_uuid: str) -> list[int]:
        """Return device.id values whose name contains or uuid starts with the given string."""
        if not name_or_uuid:
            return []
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT id FROM devices WHERE name LIKE ? ESCAPE '\\' OR uuid LIKE ? ESCAPE '\\'",
                (f"%{_escape_like(name_or_uuid)}%", f"{_escape_like(name_or_uuid)}%"),
            ).fetchall()
        return [r[0] for r in rows]
