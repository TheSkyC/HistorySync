# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
import zipfile

from webdav3.urn import Urn

from src.models.app_config import WebDavConfig
from src.services import webdav_sync
from src.services.webdav_sync import SyncStatus, WebDavSyncService


class _FakeWebDavClient:
    def __init__(self, files: dict[str, bytes] | None = None, dirs: set[str] | None = None):
        self.files = files or {}
        self.dirs = dirs or {"/HistorySync/"}

    def check(self, path: str) -> bool:
        return path in self.dirs

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def list(self, remote_dir: str) -> list[str]:
        prefix = remote_dir.rstrip("/") + "/"
        names = []
        for key in self.files:
            if key.startswith(prefix):
                names.append(key[len(prefix) :])
        return names

    def upload_sync(self, remote_path: str, local_path: str) -> None:
        self.files[remote_path] = Path(local_path).read_bytes()

    def upload_file(
        self,
        remote_path: str,
        local_path: str,
        progress=None,
        progress_args=(),
        force: bool = False,
    ) -> None:
        data = Path(local_path).read_bytes()
        if force:
            self.dirs.add(Urn(remote_path).parent())
        if callable(progress):
            progress(0, len(data), *progress_args)
        self.files[remote_path] = data
        if callable(progress):
            progress(len(data), len(data), *progress_args)

    def download_sync(self, remote_path: str, local_path: str) -> None:
        if remote_path not in self.files:
            raise FileNotFoundError(remote_path)
        Path(local_path).write_bytes(self.files[remote_path])

    def execute_request(self, action: str, path: str, data=None, headers_ext=None):
        if action != "download":
            raise NotImplementedError(action)
        if path not in self.files:
            raise FileNotFoundError(path)

        payload = self.files[path]
        range_start = 0
        range_end = len(payload) - 1
        status_code = 200

        for header in headers_ext or []:
            if not header.lower().startswith("range:"):
                continue
            value = header.split(":", 1)[1].strip()
            if not value.startswith("bytes="):
                continue
            start_str, end_str = value[len("bytes=") :].split("-", 1)
            range_start = int(start_str)
            range_end = int(end_str)
            status_code = 206
            break

        chunk = payload[range_start : range_end + 1]

        class _FakeResponse:
            def __init__(self, body: bytes, code: int):
                self.status_code = code
                self._body = body

            def iter_content(self, chunk_size: int = 8192):
                for index in range(0, len(self._body), chunk_size):
                    yield self._body[index : index + chunk_size]

        return _FakeResponse(chunk, status_code)

    def clean(self, remote_path: str) -> None:
        self.files.pop(remote_path, None)

    def move(self, remote_path_from: str, remote_path_to: str, overwrite: bool = False) -> None:
        if not overwrite and remote_path_to in self.files:
            raise FileExistsError(remote_path_to)
        self.files[remote_path_to] = self.files.pop(remote_path_from)

    def info(self, remote_path: str) -> dict:
        return {"size": len(self.files.get(remote_path, b""))}


def _configured_webdav() -> WebDavConfig:
    return WebDavConfig(
        enabled=True,
        url="https://dav.example.com",
        username="user",
        password="secret",
        remote_path="/HistorySync/",
        max_backups=2,
        verify_ssl=True,
        auto_backup=True,
        backup_favicons=False,
    )


def _make_zip_with_db(path: Path, db_bytes: bytes) -> bytes:
    db_hash = webdav_sync._sha256_bytes(db_bytes)
    manifest = {"history.db": db_hash}

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("history.db", db_bytes)
        zf.writestr("manifest.sha256.json", json.dumps(manifest))
    return path.read_bytes()


class TestWebDavServiceContracts:
    def test_progress_callback_suppresses_duplicate_percent_messages(self, tmp_path: Path):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        svc = WebDavSyncService(_configured_webdav(), db_path)
        messages: list[str] = []
        progress = svc._make_percent_progress_callback(
            messages.append,
            lambda done, total: f"Downloading: {int((done * 100) / total)}% ({done} / {total})",
        )

        progress(980, 1000)
        progress(989, 1000)
        progress(990, 1000)
        progress(999, 1000)
        progress(1000, 1000)

        assert messages == [
            "Downloading: 98% (980 / 1000)",
            "Downloading: 99% (990 / 1000)",
            "Downloading: 100% (1000 / 1000)",
        ]

    def test_is_configured_requires_enabled_url_and_username(self, tmp_path: Path):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)
        assert svc.is_configured() is True

        cfg.enabled = False
        assert svc.is_configured() is False
        cfg.enabled = True

        cfg.url = ""
        assert svc.is_configured() is False
        cfg.url = "https://dav.example.com"

        cfg.username = ""
        assert svc.is_configured() is False

    def test_normalise_path_contract(self):
        assert WebDavSyncService._normalise_path("HistorySync") == "/HistorySync/"
        assert WebDavSyncService._normalise_path("/HistorySync") == "/HistorySync/"
        assert WebDavSyncService._normalise_path("/HistorySync/") == "/HistorySync/"

    def test_sync_fails_fast_when_not_configured(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        cfg.enabled = False
        svc = WebDavSyncService(cfg, db_path)

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        result = svc.sync()

        assert result.success is False
        # Current contract: sync marks DISABLED first, then _fail finalizes status as FAILED.
        assert svc.status == SyncStatus.FAILED

    def test_sync_fails_when_db_file_missing(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        result = svc.sync()

        assert result.success is False
        assert "Database file not found" in result.message

    def test_sync_uploads_backup_and_manifest_and_cleans_old_backups(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"local-db-bytes")

        cfg = _configured_webdav()
        cfg.max_backups = 2
        svc = WebDavSyncService(cfg, db_path)

        remote_dir = "/HistorySync/"
        old1 = remote_dir + "history_1700000000.zip"
        old2 = remote_dir + "history_1700000001.zip"
        fake = _FakeWebDavClient(
            files={
                old1: b"old-a",
                old2: b"old-b",
            },
            dirs={remote_dir},
        )

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.sync()

        assert result.success is True
        assert svc.status == SyncStatus.SUCCESS
        assert result.hash_info is not None
        assert "history.db" in result.hash_info

        names = fake.list(remote_dir)
        # keep max_backups=2 zip files total after upload + cleanup
        zip_names = [n for n in names if n.startswith("history_") and n.endswith(".zip")]
        assert len(zip_names) == 2
        assert "sync_manifest.json" in names

    def test_restore_rejects_unsafe_backup_filename(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        fake = _FakeWebDavClient(files={"/HistorySync/history_bad.zip": b"irrelevant"}, dirs={"/HistorySync/"})

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "Unsafe backup filename rejected" in result.message

    def test_restore_fails_on_hash_mismatch(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        zpath = tmp_path / "bad.zip"
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("history.db", b"payload")
            zf.writestr("manifest.sha256.json", json.dumps({"history.db": "0" * 64}))

        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": zpath.read_bytes()},
            dirs={"/HistorySync/"},
        )

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "Hash verification FAILED" in result.message

    def test_restore_success_returns_downloaded_db_path(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        zip_path = tmp_path / "ok.zip"
        zip_bytes = _make_zip_with_db(zip_path, b"restored-db-content")

        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": zip_bytes},
            dirs={"/HistorySync/"},
        )

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is True
        assert result.downloaded_path is not None
        assert result.downloaded_path.exists()
        assert result.downloaded_path.read_bytes() == b"restored-db-content"
        result.downloaded_path.unlink(missing_ok=True)

    def test_fetch_manifest_returns_dict(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        manifest = {"schema_version": 1, "latest_backup": "history_1700000000.zip"}
        fake = _FakeWebDavClient(
            files={"/HistorySync/sync_manifest.json": json.dumps(manifest).encode("utf-8")},
            dirs={"/HistorySync/"},
        )

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        got = svc.fetch_manifest()

        assert got == manifest

    def test_list_backups_returns_metadata(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"db")

        cfg = _configured_webdav()
        svc = WebDavSyncService(cfg, db_path)

        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": b"a",
                "/HistorySync/history_1700000001.zip": b"bb",
                "/HistorySync/not-a-backup.txt": b"x",
            },
            dirs={"/HistorySync/"},
        )

        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        backups = svc.list_backups()

        assert len(backups) == 2
        assert backups[0]["filename"] == "history_1700000001.zip"
        assert backups[0]["size_bytes"] == 2
        assert backups[1]["filename"] == "history_1700000000.zip"
