# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""End-to-end tests for ``src.services.webdav_sync.WebDavSyncService``.

The existing :mod:`tests.test_webdav_sync_contract` covers a small surface
with a minimal fake client.  This module fills in the deeper scenarios:

* Sync end-to-end with snapshot_info, manifest ordering, favicon backup,
  and the device ``last_sync_at`` update path.
* Restore end-to-end — latest by timestamp, explicit selection, malformed
  archives, missing ``history.db``, no remote backups, favicon hash
  mismatch (non-fatal) vs OK, and remote listing failure.
* ``_webdav_retry`` retry / exhaustion.
* SHA-256 helpers, ``_backup_timestamp`` parsing, and ``_normalise_path``
  edge cases.
* ``update_config`` / ``_make_client`` snapshot-under-lock contract.
* ``_cleanup_old_backups`` with partial failure, list failure, and
  under-limit cases.
* ``list_backups`` / ``fetch_manifest`` / ``test_connection`` happy paths
  and disabled-config short-circuits.

The :class:`_FakeWebDavClient` is a richer drop-in for the production
``webdav3.client.Client``.  Files are kept as in-memory bytes keyed on
their remote path.  ``info``, ``execute_request``, and ``upload_file``
emulate just enough of the real protocol to satisfy
:class:`ResumableTransfer`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest
from webdav3.urn import Urn

from src.models.app_config import WebDavConfig
from src.services import webdav_sync
from src.services.webdav_sync import (
    SyncResult,
    SyncStatus,
    WebDavSyncService,
    _backup_timestamp,
    _sha256_bytes,
    _sha256_file,
    _webdav_retry,
)
from src.utils.constants import DB_FILENAME, FAVICON_DB_FILENAME


def test_resolve_password_does_not_double_query_when_resolver_present(monkeypatch):
    from src.utils.secret_store import get_secret_store

    store = get_secret_store()
    store_call_count = {"n": 0}

    def _counted_get(_key):
        store_call_count["n"] += 1

    monkeypatch.setattr(store, "get", _counted_get)
    result = WebDavSyncService._resolve_password(resolver=lambda: "")
    assert result == ""
    assert store_call_count["n"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Fake WebDAV client
# ──────────────────────────────────────────────────────────────────────────


class _FakeWebDavClient:
    """In-memory stand-in for the real WebDAV client.

    Files are stored in ``self.files`` as ``{remote_path: bytes}``.  The
    methods reproduce the slice of the real API that ``WebDavSyncService``
    and :class:`ResumableTransfer` actually call.  Optional ``raise_on``
    / ``fail_on_clean`` knobs let individual tests inject failure modes.
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        dirs: set[str] | None = None,
        *,
        fail_on_clean: set[str] | None = None,
        list_raises: bool = False,
    ) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.dirs: set[str] = set(dirs or {"/HistorySync/"})
        self.fail_on_clean: set[str] = set(fail_on_clean or set())
        self.list_raises = list_raises
        # Call recorders for assertions in tests.
        self.upload_calls: list[tuple[str, str]] = []
        self.move_calls: list[tuple[str, str]] = []
        self.clean_calls: list[str] = []
        self.list_calls: list[str] = []

    # --- directory ops ---------------------------------------------------

    def check(self, path: str) -> bool:
        return path in self.dirs or path in self.files

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def list(self, remote_dir: str) -> list[str]:
        if self.list_raises:
            raise RuntimeError("listing failed")
        self.list_calls.append(remote_dir)
        prefix = remote_dir.rstrip("/") + "/"
        names: list[str] = []
        for key in self.files:
            if key.startswith(prefix) and "/" not in key[len(prefix) :]:
                names.append(key[len(prefix) :])
        return names

    # --- upload ----------------------------------------------------------

    def upload_sync(self, remote_path: str, local_path: str) -> None:
        self.upload_calls.append((remote_path, local_path))
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
        self.upload_calls.append((remote_path, local_path))
        if callable(progress):
            progress(len(data), len(data), *progress_args)

    # --- download --------------------------------------------------------

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

    # --- delete / move ---------------------------------------------------

    def clean(self, remote_path: str) -> None:
        self.clean_calls.append(remote_path)
        if remote_path in self.fail_on_clean:
            raise RuntimeError(f"forced clean failure for {remote_path}")
        self.files.pop(remote_path, None)

    def move(self, remote_path_from: str, remote_path_to: str, overwrite: bool = False) -> None:
        self.move_calls.append((remote_path_from, remote_path_to))
        if not overwrite and remote_path_to in self.files:
            raise FileExistsError(remote_path_to)
        self.files[remote_path_to] = self.files.pop(remote_path_from)

    def info(self, remote_path: str) -> dict[str, int]:
        return {"size": len(self.files.get(remote_path, b""))}


# ──────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────


def _make_config(**overrides) -> WebDavConfig:
    cfg = WebDavConfig(
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
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _create_db_with_tables(
    path: Path,
    *,
    history_count: int = 0,
    bookmark_count: int = 0,
    annotation_count: int = 0,
    hidden_count: int = 0,
) -> None:
    """Create a minimal SQLite DB with the four tables the snapshot_info reads."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE history (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE annotations (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE hidden_records (id INTEGER PRIMARY KEY)")
        for _ in range(history_count):
            conn.execute("INSERT INTO history DEFAULT VALUES")
        for _ in range(bookmark_count):
            conn.execute("INSERT INTO bookmarks DEFAULT VALUES")
        for _ in range(annotation_count):
            conn.execute("INSERT INTO annotations DEFAULT VALUES")
        for _ in range(hidden_count):
            conn.execute("INSERT INTO hidden_records DEFAULT VALUES")
        conn.commit()
    finally:
        conn.close()


def _make_zip_with_db(path: Path, db_bytes: bytes) -> bytes:
    """Build a backup ZIP containing ``history.db`` plus a matching manifest."""
    db_hash = _sha256_bytes(db_bytes)
    manifest = {"history.db": db_hash}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("history.db", db_bytes)
        zf.writestr("manifest.sha256.json", json.dumps(manifest))
    return path.read_bytes()


def _make_zip_with_db_and_favicon(
    path: Path,
    db_bytes: bytes,
    fav_bytes: bytes,
    *,
    favicon_hash_mismatch: bool = False,
) -> bytes:
    """Build a backup ZIP with both ``history.db`` and a favicon DB."""
    db_hash = _sha256_bytes(db_bytes)
    fav_hash_recorded = "deadbeef" * 8 if favicon_hash_mismatch else _sha256_bytes(fav_bytes)
    manifest = {DB_FILENAME: db_hash, FAVICON_DB_FILENAME: fav_hash_recorded}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(DB_FILENAME, db_bytes)
        zf.writestr(FAVICON_DB_FILENAME, fav_bytes)
        zf.writestr("manifest.sha256.json", json.dumps(manifest))
    return path.read_bytes()


class _FakeLocalDb:
    """Stand-in for :class:`LocalDatabase` exposing only what sync uses."""

    def __init__(self, source_db: Path) -> None:
        self.source_db = source_db
        self.export_calls: list[Path] = []
        self.update_device_last_sync_calls: list[int] = []
        self.update_device_last_sync_raises: bool = False

    def export_without_fts(self, dest_path: Path) -> None:
        import shutil

        self.export_calls.append(Path(dest_path))
        shutil.copy2(self.source_db, dest_path)

    def update_device_last_sync(self, device_id: int) -> None:
        if self.update_device_last_sync_raises:
            raise RuntimeError("device update failed")
        self.update_device_last_sync_calls.append(device_id)


@pytest.fixture()
def configured_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Default service with a minimal DB file and ``_WEBDAV3_AVAILABLE`` forced on."""
    db_path = tmp_path / "history.db"
    _create_db_with_tables(db_path)
    cfg = _make_config()
    svc = WebDavSyncService(cfg, db_path)
    monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
    return svc, db_path, cfg


# ──────────────────────────────────────────────────────────────────────────
# SHA-256 / timestamp / path helpers
# ──────────────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_sha256_file_matches_sha256_bytes(self, tmp_path: Path) -> None:
        payload = b"hello world\n" * 100
        file = tmp_path / "blob.bin"
        file.write_bytes(payload)
        assert _sha256_file(file) == _sha256_bytes(payload)
        assert _sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()

    def test_sha256_file_streams_large_files(self, tmp_path: Path) -> None:
        # 256 KiB of varying data so hashing more than one read chunk is exercised.
        payload = bytes(range(256)) * 1024
        file = tmp_path / "big.bin"
        file.write_bytes(payload)
        assert _sha256_file(file) == hashlib.sha256(payload).hexdigest()

    def test_backup_timestamp_extracts_unix_seconds(self) -> None:
        assert _backup_timestamp("history_1700000000.zip") == 1700000000

    def test_backup_timestamp_returns_zero_for_malformed(self) -> None:
        assert _backup_timestamp("history_abc.zip") == 0
        assert _backup_timestamp("not-a-backup.txt") == 0
        assert _backup_timestamp("") == 0

    def test_normalise_path_idempotent(self) -> None:
        assert WebDavSyncService._normalise_path("HistorySync") == "/HistorySync/"
        assert WebDavSyncService._normalise_path("/HistorySync") == "/HistorySync/"
        assert WebDavSyncService._normalise_path("/HistorySync/") == "/HistorySync/"
        assert WebDavSyncService._normalise_path("  /pad/  ") == "/pad/"


class TestSyncResultDefaults:
    def test_failure_default(self) -> None:
        r = SyncResult(False, "boom")
        assert r.success is False
        assert r.message == "boom"
        assert r.timestamp > 0
        assert r.downloaded_path is None
        assert r.hash_info is None

    def test_repr_indicates_status(self) -> None:
        ok = SyncResult(True, "done")
        bad = SyncResult(False, "no")
        assert "OK" in repr(ok)
        assert "FAIL" in repr(bad)

    def test_explicit_timestamp_preserved(self) -> None:
        assert SyncResult(True, "x", timestamp=1234).timestamp == 1234


# ──────────────────────────────────────────────────────────────────────────
# _webdav_retry — exponential backoff + exhaustion
# ──────────────────────────────────────────────────────────────────────────


class TestWebdavRetry:
    def test_first_try_success_no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(webdav_sync.time, "sleep", slept.append)

        calls = []
        _webdav_retry(lambda: calls.append("ok"), attempts=3)

        assert calls == ["ok"]
        assert slept == []

    def test_succeeds_on_second_try_with_one_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(webdav_sync.time, "sleep", slept.append)

        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("transient")

        _webdav_retry(flaky, attempts=3, base_delay=0.5)

        assert len(attempts) == 2
        assert len(slept) == 1
        # First retry delay is base_delay * 2^0 + jitter ∈ [0, 1)
        assert 0.5 <= slept[0] < 1.5

    def test_exhausts_attempts_and_reraises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(webdav_sync.time, "sleep", slept.append)

        def boom():
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            _webdav_retry(boom, attempts=3, base_delay=0.1)

        # Last attempt does NOT sleep, so sleep count = attempts - 1.
        assert len(slept) == 2


# ──────────────────────────────────────────────────────────────────────────
# Status / configuration / make_client
# ──────────────────────────────────────────────────────────────────────────


class TestStatusAndConfig:
    def test_status_starts_idle(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        assert svc.status == SyncStatus.IDLE
        assert svc.last_result is None

    def test_auto_backup_property_reflects_config(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        cfg = _make_config(auto_backup=False)
        svc = WebDavSyncService(cfg, db)
        assert svc.auto_backup_enabled is False
        cfg.auto_backup = True
        assert svc.auto_backup_enabled is True

    def test_update_config_swaps_creds_and_resets_status(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        # Force a non-IDLE status so we can verify it resets.
        svc._set_status(SyncStatus.FAILED)
        new_cfg = _make_config(username="other", password="new")
        svc.update_config(new_cfg)
        assert svc.status == SyncStatus.IDLE
        assert svc._config is new_cfg

    def test_set_local_db_and_set_device_id(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        fake_db = _FakeLocalDb(db)
        svc.set_local_db(fake_db)
        svc.set_device_id(123)
        assert svc._local_db is fake_db
        assert svc._device_id == 123

    def test_make_client_snapshots_config_under_lock(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)

        captured: dict[str, object] = {}

        class _Client:
            def __init__(self, options: dict) -> None:
                captured["options"] = dict(options)
                self.verify = True

        monkeypatch.setattr(webdav_sync, "_WdavClient", _Client)

        client = svc._make_client()

        assert captured["options"]["webdav_hostname"] == "https://dav.example.com"
        assert captured["options"]["webdav_login"] == "user"
        assert captured["options"]["webdav_password"] == "secret"
        # Trailing slashes are stripped from the URL.
        assert not captured["options"]["webdav_hostname"].endswith("/")
        assert client.verify is True

    def test_make_client_disables_verify_when_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        cfg = _make_config(verify_ssl=False)
        svc = WebDavSyncService(cfg, db)

        class _Client:
            def __init__(self, options: dict) -> None:
                self.verify = True

        monkeypatch.setattr(webdav_sync, "_WdavClient", _Client)

        client = svc._make_client()

        assert client.verify is False


class TestProgressCallback:
    def test_total_zero_always_emits(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)

        msgs: list[str] = []
        cb = svc._make_percent_progress_callback(msgs.append, lambda d, t: f"{d}/{t}")
        cb(0, 0)
        cb(0, 0)
        assert msgs == ["0/0", "0/0"]

    def test_clamps_overshoot_to_one_hundred(self, tmp_path: Path) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        msgs: list[str] = []
        cb = svc._make_percent_progress_callback(msgs.append, lambda d, t: f"{int((d / t) * 100) if t else 0}")
        # First a full message, then an overshoot — the percent stays at 100 so the dedupe drops it.
        cb(100, 100)
        cb(150, 100)
        assert msgs == ["100"]


# ──────────────────────────────────────────────────────────────────────────
# test_connection
# ──────────────────────────────────────────────────────────────────────────


class TestConnection:
    def test_returns_failure_when_not_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        cfg = _make_config(enabled=False)
        svc = WebDavSyncService(cfg, db)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        result = svc.test_connection()

        assert result.success is False
        assert "not configured" in result.message.lower()

    def test_returns_failure_when_webdav3_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", False)

        result = svc.test_connection()

        assert result.success is False
        assert "not installed" in result.message.lower()

    def test_creates_remote_dir_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        fake = _FakeWebDavClient(dirs=set())  # no /HistorySync/ yet
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.test_connection()

        assert result.success is True
        assert "/HistorySync/" in fake.dirs
        assert svc.status == SyncStatus.IDLE

    def test_returns_failure_on_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "h.db"
        db.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        class _Boom:
            def check(self, _p):
                raise RuntimeError("server down")

        monkeypatch.setattr(svc, "_make_client", _Boom)

        result = svc.test_connection()

        assert result.success is False
        assert "server down" in result.message
        assert svc.status == SyncStatus.FAILED


# ──────────────────────────────────────────────────────────────────────────
# Sync end-to-end
# ──────────────────────────────────────────────────────────────────────────


class TestSyncEndToEnd:
    def test_uploads_zip_with_snapshot_info_and_manifest(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path, history_count=3, bookmark_count=1, annotation_count=2, hidden_count=0)

        cfg = _make_config()
        svc = WebDavSyncService(cfg, db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        fake = _FakeWebDavClient(dirs={"/HistorySync/"})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.sync()

        assert result.success is True
        assert svc.status == SyncStatus.SUCCESS
        # Backup ZIP and manifest both uploaded.
        names = fake.list("/HistorySync/")
        assert any(n.startswith("history_") and n.endswith(".zip") for n in names)
        assert "sync_manifest.json" in names

        # The ZIP must contain manifest, snapshot_info, and history.db.
        zip_path = next(p for p in fake.files if p.startswith("/HistorySync/history_") and p.endswith(".zip"))
        with zipfile.ZipFile(io_bytes(fake.files[zip_path])) as zf:
            entries = zf.namelist()
            assert "history.db" in entries
            assert "manifest.sha256.json" in entries
            assert "snapshot_info.json" in entries
            snap = json.loads(zf.read("snapshot_info.json"))
            assert snap["history_count"] == 3
            assert snap["bookmark_count"] == 1
            assert snap["annotation_count"] == 2
            assert snap["hidden_record_count"] == 0
            assert "db_sha256" in snap
            assert snap["schema_version"] == 1

        # And the sync_manifest.json mirrors those counts.
        manifest = json.loads(fake.files["/HistorySync/sync_manifest.json"])
        assert manifest["history_count"] == 3
        assert manifest["bookmark_count"] == 1
        assert manifest["latest_backup"].endswith(".zip")
        assert manifest["latest_backup_ts"] > 0

    def test_sync_records_hash_info_and_last_result(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: _FakeWebDavClient(dirs={"/HistorySync/"}))

        result = svc.sync()

        assert result.hash_info is not None
        assert "history.db" in result.hash_info
        assert svc.last_result is result

    def test_sync_invokes_export_without_fts_when_local_db_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        local_db = _FakeLocalDb(db_path)
        svc.set_local_db(local_db)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: _FakeWebDavClient(dirs={"/HistorySync/"}))

        result = svc.sync()

        assert result.success is True
        assert len(local_db.export_calls) == 1
        # Helper writes a fresh tempfile path; just verify it was a Path.
        assert isinstance(local_db.export_calls[0], Path)

    def test_sync_falls_back_to_shutil_copy_when_no_local_db(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No set_local_db call → shutil.copy2 path.  We can verify success and
        # that the uploaded DB bytes match the source bytes.
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path, history_count=1)
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        fake = _FakeWebDavClient(dirs={"/HistorySync/"})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.sync()

        assert result.success is True
        zip_path = next(p for p in fake.files if p.startswith("/HistorySync/history_") and p.endswith(".zip"))
        with zipfile.ZipFile(io_bytes(fake.files[zip_path])) as zf:
            assert "history.db" in zf.namelist()

    def test_sync_updates_device_last_sync_when_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        local_db = _FakeLocalDb(db_path)
        svc.set_local_db(local_db)
        svc.set_device_id(42)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: _FakeWebDavClient(dirs={"/HistorySync/"}))

        result = svc.sync()

        assert result.success is True
        assert local_db.update_device_last_sync_calls == [42]

    def test_sync_swallows_device_update_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # update_device_last_sync raising must NOT fail the overall sync.
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        local_db = _FakeLocalDb(db_path)
        local_db.update_device_last_sync_raises = True
        svc.set_local_db(local_db)
        svc.set_device_id(7)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: _FakeWebDavClient(dirs={"/HistorySync/"}))

        result = svc.sync()

        assert result.success is True

    def test_sync_includes_favicon_when_enabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        cfg = _make_config(backup_favicons=True)
        svc = WebDavSyncService(cfg, db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        fake = _FakeWebDavClient(dirs={"/HistorySync/"})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        favicon_dir = tmp_path / "favs"
        favicon_dir.mkdir()
        (favicon_dir / FAVICON_DB_FILENAME).write_bytes(b"fav-bytes")

        result = svc.sync(favicon_cache_dir=favicon_dir)

        assert result.success is True
        zip_path = next(p for p in fake.files if p.startswith("/HistorySync/history_") and p.endswith(".zip"))
        with zipfile.ZipFile(io_bytes(fake.files[zip_path])) as zf:
            assert FAVICON_DB_FILENAME in zf.namelist()
        assert FAVICON_DB_FILENAME in result.hash_info

    def test_sync_progress_callback_invoked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        monkeypatch.setattr(svc, "_make_client", lambda: _FakeWebDavClient(dirs={"/HistorySync/"}))

        msgs: list[str] = []
        result = svc.sync(progress_callback=msgs.append)

        assert result.success is True
        # Several stage messages are emitted; just verify at least one.
        assert msgs

    def test_sync_cleanup_failure_appends_warning_to_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-populate three old backups so cleanup must delete one with max_backups=1.
        # Stub the failing clean for the oldest file — backup must still succeed but
        # the message must include the warning prefix.
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        cfg = _make_config(max_backups=1)
        svc = WebDavSyncService(cfg, db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        oldest = "/HistorySync/history_1700000000.zip"
        middle = "/HistorySync/history_1700000001.zip"
        files = {oldest: b"a", middle: b"b"}
        fake = _FakeWebDavClient(files=files, dirs={"/HistorySync/"}, fail_on_clean={oldest, middle})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.sync()

        assert result.success is True
        assert "could not delete" in result.message.lower()

    def test_sync_fails_when_make_client_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        _create_db_with_tables(db_path)
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        def _boom() -> _FakeWebDavClient:
            raise RuntimeError("dns fail")

        monkeypatch.setattr(svc, "_make_client", _boom)

        result = svc.sync()

        assert result.success is False
        assert "dns fail" in result.message
        assert svc.status == SyncStatus.FAILED


# ──────────────────────────────────────────────────────────────────────────
# Restore end-to-end
# ──────────────────────────────────────────────────────────────────────────


class TestRestoreEndToEnd:
    def test_picks_latest_by_timestamp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        old_zip = tmp_path / "old.zip"
        new_zip = tmp_path / "new.zip"
        _make_zip_with_db(old_zip, b"old-payload")
        _make_zip_with_db(new_zip, b"new-payload")

        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": old_zip.read_bytes(),
                "/HistorySync/history_1700000050.zip": new_zip.read_bytes(),
            },
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is True
        # The newer (1700000050) payload must win.
        assert result.downloaded_path is not None
        assert result.downloaded_path.read_bytes() == b"new-payload"
        result.downloaded_path.unlink(missing_ok=True)

    def test_select_specific_backup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        old_zip = tmp_path / "old.zip"
        new_zip = tmp_path / "new.zip"
        _make_zip_with_db(old_zip, b"OLD")
        _make_zip_with_db(new_zip, b"NEW")

        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": old_zip.read_bytes(),
                "/HistorySync/history_1700000050.zip": new_zip.read_bytes(),
            },
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore(backup_filename="history_1700000000.zip")

        assert result.success is True
        assert result.downloaded_path is not None
        assert result.downloaded_path.read_bytes() == b"OLD"
        result.downloaded_path.unlink(missing_ok=True)

    def test_select_unknown_backup_returns_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        # Ensure at least one safe-named backup exists so the early "no backups"
        # branch is bypassed and the requested filename is rejected.
        zip_path = tmp_path / "ok.zip"
        _make_zip_with_db(zip_path, b"present")
        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": zip_path.read_bytes()},
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore(backup_filename="history_9999999999.zip")

        assert result.success is False
        assert "Selected backup not found" in result.message

    def test_reports_failure_when_no_backups(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        fake = _FakeWebDavClient(files={}, dirs={"/HistorySync/"})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "no backups" in result.message.lower()

    def test_handles_remote_listing_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        fake = _FakeWebDavClient(dirs={"/HistorySync/"}, list_raises=True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "Remote directory not found" in result.message

    def test_returns_failure_for_bad_zip(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": b"this-is-not-a-zip"},
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "Bad zip archive" in result.message

    def test_returns_failure_when_zip_missing_history_db(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        # Build a ZIP that contains the manifest but NO history.db.
        bad_zip = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.sha256.json", json.dumps({}))
            zf.writestr("README.txt", "no db here")

        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": bad_zip.read_bytes()},
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        result = svc.restore()

        assert result.success is False
        assert "missing history.db" in result.message

    def test_restore_with_favicon_writes_to_disk(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        zip_path = tmp_path / "withfav.zip"
        _make_zip_with_db_and_favicon(zip_path, b"the-db", b"favicons-blob")

        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": zip_path.read_bytes()},
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        favicon_dir = tmp_path / "favicons"
        result = svc.restore(restore_favicons=True, favicon_cache_dir=favicon_dir)

        assert result.success is True
        assert (favicon_dir / FAVICON_DB_FILENAME).exists()
        assert (favicon_dir / FAVICON_DB_FILENAME).read_bytes() == b"favicons-blob"
        if result.downloaded_path:
            result.downloaded_path.unlink(missing_ok=True)

    def test_restore_with_favicon_hash_mismatch_skips_favicon_writes_db(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        zip_path = tmp_path / "mismatch.zip"
        _make_zip_with_db_and_favicon(zip_path, b"the-db", b"favicons-blob", favicon_hash_mismatch=True)
        fake = _FakeWebDavClient(
            files={"/HistorySync/history_1700000000.zip": zip_path.read_bytes()},
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        favicon_dir = tmp_path / "favicons"
        result = svc.restore(restore_favicons=True, favicon_cache_dir=favicon_dir)

        # DB restore still succeeds — favicon mismatch is non-fatal.
        assert result.success is True
        # Favicon must NOT have been written when the hash didn't match.
        assert not (favicon_dir / FAVICON_DB_FILENAME).exists()
        if result.downloaded_path:
            result.downloaded_path.unlink(missing_ok=True)

    def test_restore_fails_fast_when_not_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "history.db"
        db_path.write_bytes(b"x")
        cfg = _make_config(enabled=False)
        svc = WebDavSyncService(cfg, db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)

        result = svc.restore()

        assert result.success is False


# ──────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────


class TestCleanupOldBackups:
    def test_keeps_only_max_backups(self, tmp_path: Path) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        cfg = _make_config(max_backups=2)
        svc = WebDavSyncService(cfg, db_path)

        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": b"a",
                "/HistorySync/history_1700000001.zip": b"b",
                "/HistorySync/history_1700000002.zip": b"c",
                "/HistorySync/history_1700000003.zip": b"d",
            },
            dirs={"/HistorySync/"},
        )

        failed = svc._cleanup_old_backups(fake, "/HistorySync/")

        assert failed == []
        # Only the two most recent (002, 003) remain.
        names = sorted(fake.list("/HistorySync/"))
        assert names == [
            "history_1700000002.zip",
            "history_1700000003.zip",
        ]

    def test_under_limit_deletes_nothing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(max_backups=5), db_path)

        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": b"a",
                "/HistorySync/history_1700000001.zip": b"b",
            },
            dirs={"/HistorySync/"},
        )

        failed = svc._cleanup_old_backups(fake, "/HistorySync/")

        assert failed == []
        assert fake.clean_calls == []

    def test_max_backups_zero_clamped_to_one(self, tmp_path: Path) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        # max_backups=0 must be clamped up to 1 — we keep at least one backup.
        svc = WebDavSyncService(_make_config(max_backups=0), db_path)
        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": b"a",
                "/HistorySync/history_1700000001.zip": b"b",
            },
            dirs={"/HistorySync/"},
        )

        svc._cleanup_old_backups(fake, "/HistorySync/")

        assert sorted(fake.list("/HistorySync/")) == ["history_1700000001.zip"]

    def test_returns_failed_filenames_when_partial_clean_fails(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(max_backups=1), db_path)

        oldest = "/HistorySync/history_1700000000.zip"
        middle = "/HistorySync/history_1700000001.zip"
        latest = "/HistorySync/history_1700000002.zip"
        fake = _FakeWebDavClient(
            files={oldest: b"a", middle: b"b", latest: b"c"},
            dirs={"/HistorySync/"},
            fail_on_clean={oldest},
        )

        failed = svc._cleanup_old_backups(fake, "/HistorySync/")

        assert "history_1700000000.zip" in failed
        # Middle was successfully removed; latest stays.
        names = sorted(fake.list("/HistorySync/"))
        assert "history_1700000002.zip" in names
        assert "history_1700000001.zip" not in names

    def test_reports_listing_failure(self, tmp_path: Path) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        fake = _FakeWebDavClient(dirs={"/HistorySync/"}, list_raises=True)

        failed = svc._cleanup_old_backups(fake, "/HistorySync/")

        assert failed == ["(listing failed)"]


# ──────────────────────────────────────────────────────────────────────────
# fetch_manifest / list_backups disabled-config short-circuits
# ──────────────────────────────────────────────────────────────────────────


class TestQueryWhenDisabled:
    def test_fetch_manifest_returns_none_when_not_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        cfg = _make_config(enabled=False)
        svc = WebDavSyncService(cfg, db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        assert svc.fetch_manifest() is None

    def test_fetch_manifest_returns_none_when_webdav3_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", False)
        assert svc.fetch_manifest() is None

    def test_fetch_manifest_returns_none_on_missing_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        # No sync_manifest.json on the server.
        fake = _FakeWebDavClient(dirs={"/HistorySync/"})
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        # download_sync inside _webdav_retry will exhaust attempts → None returned.
        # Avoid waiting on real backoff sleeps.
        monkeypatch.setattr(webdav_sync.time, "sleep", lambda _s: None)

        assert svc.fetch_manifest() is None

    def test_list_backups_returns_empty_when_not_configured(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(enabled=False), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        assert svc.list_backups() == []

    def test_list_backups_filters_non_backup_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        fake = _FakeWebDavClient(
            files={
                "/HistorySync/history_1700000000.zip": b"a",
                "/HistorySync/sync_manifest.json": b"{}",
                "/HistorySync/notes.txt": b"x",
                "/HistorySync/history_corrupt.zip": b"y",  # malformed name
            },
            dirs={"/HistorySync/"},
        )
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        backups = svc.list_backups()

        assert len(backups) == 2  # the valid + the malformed history_*.zip
        assert {b["filename"] for b in backups} == {
            "history_1700000000.zip",
            "history_corrupt.zip",
        }

    def test_list_backups_handles_listing_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "h.db"
        db_path.write_bytes(b"x")
        svc = WebDavSyncService(_make_config(), db_path)
        monkeypatch.setattr(webdav_sync, "_WEBDAV3_AVAILABLE", True)
        fake = _FakeWebDavClient(list_raises=True)
        monkeypatch.setattr(svc, "_make_client", lambda: fake)

        assert svc.list_backups() == []


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers used by the tests above
# ──────────────────────────────────────────────────────────────────────────


def io_bytes(data: bytes):
    """Return a binary file-like for ``zipfile.ZipFile`` to read in-memory."""
    import io

    return io.BytesIO(data)
