# Copyright (c) 2026, HistorySync contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import time
import zipfile

from src.services.local_db import LocalDatabase
from src.utils.constants import DB_FILENAME, FAVICON_DB_FILENAME, SNAPSHOT_INFO_FILENAME
from src.utils.i18n_core import _


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_archive(destination: Path, snapshot: Path, favicon_db: Path | None = None) -> tuple[dict, dict]:
    """Package a consistent SQLite snapshot using the existing WebDAV archive format."""
    conn = sqlite3.connect(snapshot)
    try:
        counts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("history", "bookmarks", "annotations", "hidden_records")
        ]
    except sqlite3.Error:
        counts = [0] * 4
    finally:
        conn.close()

    hashes = {}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in ((DB_FILENAME, snapshot), (FAVICON_DB_FILENAME, favicon_db)):
            if path is not None and path.is_file():
                hashes[name] = sha256_file(path)
                archive.write(path, name)
        info = dict(
            zip(("history_count", "bookmark_count", "annotation_count", "hidden_record_count"), counts, strict=True)
        )
        info.update(schema_version=1, db_sha256=hashes[DB_FILENAME])
        archive.writestr("manifest.sha256.json", json.dumps(hashes, indent=2))
        archive.writestr(SNAPSHOT_INFO_FILENAME, json.dumps({**info, "created_at": int(time.time())}, indent=2))
    return hashes, info


def export_zip(db: LocalDatabase, destination: Path) -> None:
    if destination.suffix.lower() != ".zip":
        raise ValueError(_("Choose a file with the .zip extension."))
    with TemporaryDirectory(dir=destination.parent) as tmp:
        snapshot = Path(tmp) / DB_FILENAME
        db.export_without_fts(snapshot)
        archive = Path(tmp) / "backup.zip"
        write_archive(archive, snapshot)
        archive.replace(destination)


def import_zip(db: LocalDatabase, source: Path) -> int:
    with TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / DB_FILENAME
        with zipfile.ZipFile(source) as archive:
            if archive.namelist().count(DB_FILENAME) != 1:
                raise ValueError(_("Expected one history.db in the backup."))
            manifest = "manifest.sha256.json"
            if archive.namelist().count(manifest) != 1 or archive.getinfo(manifest).file_size > 65536:
                raise ValueError(_("Invalid backup manifest."))
            expected = json.loads(archive.read(manifest))[DB_FILENAME]
            if archive.getinfo(DB_FILENAME).file_size >= shutil.disk_usage(tmp).free:
                raise ValueError(_("Insufficient disk space for the uncompressed backup."))
            with archive.open(DB_FILENAME) as src, snapshot.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        if sha256_file(snapshot) != expected:
            raise ValueError(_("Backup checksum mismatch."))
        return db.merge_from_db(snapshot)
