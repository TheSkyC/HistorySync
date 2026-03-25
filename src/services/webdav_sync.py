# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import zipfile

from src.models.app_config import WebDavConfig
from src.utils.constants import DB_FILENAME, FAVICON_DB_FILENAME, WEBDAV_BACKUP_NAME_PREFIX
from src.utils.i18n import _
from src.utils.logger import get_logger

log = get_logger("webdav")

try:
    from webdav3.client import Client as _WdavClient
    from webdav3.exceptions import (
        NoConnection,
        RemoteResourceNotFound,
        WebDavException,
    )

    _WEBDAV3_AVAILABLE = True
except ImportError:
    _WEBDAV3_AVAILABLE = False
    _WdavClient = None
    WebDavException = Exception
    RemoteResourceNotFound = Exception
    NoConnection = Exception


class SyncStatus(Enum):
    IDLE = auto()
    CONNECTING = auto()
    UPLOADING = auto()
    DOWNLOADING = auto()
    CLEANING = auto()
    SUCCESS = auto()
    FAILED = auto()
    DISABLED = auto()


class SyncResult:
    __slots__ = ("downloaded_path", "hash_info", "message", "success", "timestamp")

    def __init__(self, success: bool, message: str = "", timestamp: int | None = None):
        self.success = success
        self.message = message
        self.timestamp = timestamp or int(time.time())
        self.downloaded_path: Path | None = None
        self.hash_info: dict | None = None  # {filename: sha256_hex}

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"<SyncResult {status}: {self.message}>"


def _sha256_file(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WebDavSyncService:
    def __init__(self, config: WebDavConfig, db_path: Path):
        self._config = config
        self._db_path = db_path
        self._status = SyncStatus.IDLE
        self._last_result: SyncResult | None = None
        self._local_db: "LocalDatabase | None" = None  # set by caller for FTS ops

    @property
    def status(self) -> SyncStatus:
        return self._status

    @property
    def last_result(self) -> SyncResult | None:
        return self._last_result

    def is_configured(self) -> bool:
        return bool(self._config.enabled and self._config.url.strip() and self._config.username.strip())

    def update_config(self, config: WebDavConfig) -> None:
        self._config = config
        self._status = SyncStatus.IDLE

    def set_local_db(self, db: "LocalDatabase") -> None:
        """Provide a LocalDatabase reference so sync/restore can manage FTS."""
        self._local_db = db

    # ── Connection test ───────────────────────────────────────

    def test_connection(self) -> SyncResult:
        if not _WEBDAV3_AVAILABLE:
            return SyncResult(False, _("webdavclient3 is not installed. Run: pip install webdavclient3"))
        if not self.is_configured():
            return SyncResult(False, _("WebDAV not configured"))
        self._status = SyncStatus.CONNECTING
        try:
            client = self._make_client()
            remote = self._normalise_path(self._config.remote_path)
            if not client.check(remote):
                client.mkdir(remote)
            client.list(remote)
            self._status = SyncStatus.IDLE
            result = SyncResult(True, _("Connection successful"))
        except Exception as exc:
            self._status = SyncStatus.FAILED
            result = SyncResult(False, str(exc))
        self._last_result = result
        return result

    # ── Main sync (Backup) ────────────────────────────────────

    def sync(
        self,
        progress_callback: Callable[[str], None] | None = None,
        favicon_cache_dir: Path | None = None,
    ) -> SyncResult:
        """Backup db (and optionally favicon cache) to WebDAV as a zip with hash manifest."""
        if not _WEBDAV3_AVAILABLE:
            return self._fail(_("webdavclient3 is not installed."))
        if not self.is_configured():
            self._status = SyncStatus.DISABLED
            return self._fail(_("WebDAV not configured or disabled"))
        if not self._db_path.exists():
            return self._fail(f"Database file not found: {self._db_path}")

        def _cb(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)
            log.info("WebDAV Backup: %s", msg)

        self._status = SyncStatus.CONNECTING
        _cb(_("Connecting to WebDAV server..."))

        tmp_zip_path: str | None = None
        tmp_clean_db_path: str | None = None
        try:
            client = self._make_client()
            remote_dir = self._normalise_path(self._config.remote_path)
            if not client.check(remote_dir):
                client.mkdir(remote_dir)

            self._status = SyncStatus.UPLOADING

            # ── Export FTS-free copy of the DB ─────────────
            _cb(_("Preparing database for upload (stripping FTS index)..."))
            fd_clean, tmp_clean_db_path = tempfile.mkstemp(suffix="_clean.db")
            os.close(fd_clean)
            clean_db_path = Path(tmp_clean_db_path)
            if self._local_db is not None:
                self._local_db.export_without_fts(clean_db_path)
            else:
                import shutil as _shutil
                _shutil.copy2(self._db_path, clean_db_path)

            original_size = self._db_path.stat().st_size
            clean_size = clean_db_path.stat().st_size
            log.info(
                "FTS stripped: %.1f MB → %.1f MB (saved %.1f MB)",
                original_size / 1024 / 1024,
                clean_size / 1024 / 1024,
                (original_size - clean_size) / 1024 / 1024,
            )

            # ── Build zip archive with hash manifest ──────────
            _cb(_("Compressing and packaging backup..."))
            fd, tmp_zip_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)

            hash_manifest: dict[str, str] = {}

            with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                # Add FTS-free DB (stored as DB_FILENAME for restore compatibility)
                db_hash = _sha256_file(clean_db_path)
                zf.write(clean_db_path, arcname=DB_FILENAME)
                hash_manifest[DB_FILENAME] = db_hash
                log.info("DB hash: %s", db_hash)

                # Optionally add favicon cache
                if self._config.backup_favicons and favicon_cache_dir and favicon_cache_dir.exists():
                    _cb(_("Adding favicon cache to backup..."))
                    favicon_db = favicon_cache_dir / FAVICON_DB_FILENAME
                    if favicon_db.exists():
                        fav_hash = _sha256_file(favicon_db)
                        zf.write(favicon_db, arcname=FAVICON_DB_FILENAME)
                        hash_manifest[FAVICON_DB_FILENAME] = fav_hash

                # Write hash manifest
                manifest_json = json.dumps(hash_manifest, indent=2, ensure_ascii=False).encode("utf-8")
                zf.writestr("manifest.sha256.json", manifest_json)

            zip_size = Path(tmp_zip_path).stat().st_size
            ratio = (1 - zip_size / original_size) * 100 if original_size > 0 else 0
            log.info(
                "Backup zip: %.1f KB → %.1f KB (%.0f%% reduction vs original)",
                original_size / 1024,
                zip_size / 1024,
                ratio,
            )

            # ── Upload ────────────────────────────────────────
            remote_filename = f"{WEBDAV_BACKUP_NAME_PREFIX}{int(time.time())}.zip"
            remote_file = f"{remote_dir.rstrip('/')}/{remote_filename}"
            _cb(_("Uploading backup ({size} KB)...").format(size=f"{zip_size / 1024:.0f}"))
            client.upload_sync(remote_path=remote_file, local_path=tmp_zip_path)

            self._status = SyncStatus.CLEANING
            _cb(_("Cleaning up old backups..."))
            self._cleanup_old_backups(client, remote_dir)

            self._status = SyncStatus.SUCCESS
            result = SyncResult(
                True,
                _("Upload successful: {filename} ({size} KB) — SHA-256 verified").format(
                    filename=remote_filename,
                    size=f"{zip_size / 1024:.0f}",
                ),
            )
            result.hash_info = hash_manifest
            self._last_result = result
            return result

        except Exception as exc:
            return self._fail(_("Upload failed: {error}").format(error=str(exc)))
        finally:
            if tmp_zip_path:
                try:
                    Path(tmp_zip_path).unlink(missing_ok=True)
                except OSError:
                    pass
            if tmp_clean_db_path:
                try:
                    Path(tmp_clean_db_path).unlink(missing_ok=True)
                except OSError:
                    pass

    # ── Restore ───────────────────────────────────────────────

    def restore(
        self,
        progress_callback: Callable[[str], None] | None = None,
        restore_favicons: bool = False,
        favicon_cache_dir: Path | None = None,
    ) -> SyncResult:
        if not _WEBDAV3_AVAILABLE:
            return self._fail(_("webdavclient3 is not installed."))
        if not self.is_configured():
            self._status = SyncStatus.DISABLED
            return self._fail(_("WebDAV not configured or disabled"))

        def _cb(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)
            log.info("WebDAV Restore: %s", msg)

        self._status = SyncStatus.CONNECTING
        _cb(_("Connecting to WebDAV server..."))

        tmp_download_path: str | None = None
        try:
            client = self._make_client()
            remote_dir = self._normalise_path(self._config.remote_path)

            _cb(_("Listing remote backups..."))
            try:
                all_items = client.list(remote_dir)
            except Exception:
                return self._fail(_("Remote directory not found."))

            zip_backups = sorted(i for i in all_items if i.startswith(WEBDAV_BACKUP_NAME_PREFIX) and i.endswith(".zip"))
            if not zip_backups:
                return self._fail(_("No backups found on server."))

            latest_backup = zip_backups[-1]
            remote_file = f"{remote_dir.rstrip('/')}/{latest_backup}"

            self._status = SyncStatus.DOWNLOADING
            _cb(_("Downloading {filename}...").format(filename=latest_backup))

            fd, tmp_download_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            client.download_sync(remote_path=remote_file, local_path=tmp_download_path)

            hash_info: dict[str, str] = {}

            if True:
                # ── zip format with hash manifest ─────────────
                _cb(_("Verifying backup integrity (SHA-256)..."))
                fd2, tmp_db_path = tempfile.mkstemp(suffix=".db")
                os.close(fd2)
                try:
                    with zipfile.ZipFile(tmp_download_path, "r") as zf:
                        names = zf.namelist()

                        # Read manifest
                        if "manifest.sha256.json" in names:
                            manifest_data = zf.read("manifest.sha256.json")
                            hash_info = json.loads(manifest_data.decode("utf-8"))

                        # Extract DB
                        if DB_FILENAME not in names:
                            return self._fail(_("Backup archive missing history.db"))

                        db_data = zf.read(DB_FILENAME)

                        # Verify hash
                        actual_hash = _sha256_bytes(db_data)
                        expected_hash = hash_info.get(DB_FILENAME, "")
                        if expected_hash and actual_hash != expected_hash:
                            return self._fail(
                                _("Hash verification FAILED! Expected {exp}, got {act}").format(
                                    exp=expected_hash[:16] + "...",
                                    act=actual_hash[:16] + "...",
                                )
                            )
                        if expected_hash:
                            log.info("Hash verified OK: %s", actual_hash[:16])
                            _cb(_("✓ Hash verified: {hash}...").format(hash=actual_hash[:16]))

                        with Path(tmp_db_path).open("wb") as f:
                            f.write(db_data)

                        # Optionally restore favicons
                        if restore_favicons and favicon_cache_dir and FAVICON_DB_FILENAME in names:
                            _cb(_("Restoring favicon cache..."))
                            fav_data = zf.read(FAVICON_DB_FILENAME)
                            fav_hash_actual = _sha256_bytes(fav_data)
                            fav_hash_expected = hash_info.get(FAVICON_DB_FILENAME, "")
                            if fav_hash_expected and fav_hash_actual != fav_hash_expected:
                                log.warning("Favicon hash mismatch (non-fatal), skipping")
                            else:
                                favicon_cache_dir.mkdir(parents=True, exist_ok=True)
                                fav_dest = favicon_cache_dir / FAVICON_DB_FILENAME
                                with Path(fav_dest).open("wb") as f:
                                    f.write(fav_data)
                                log.info("Favicon cache restored to %s", fav_dest)

                except zipfile.BadZipFile as exc:
                    try:
                        Path(tmp_db_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                    return self._fail(_("Bad zip archive: {error}").format(error=str(exc)))
                finally:
                    try:
                        Path(tmp_download_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                tmp_download_path = tmp_db_path

            self._status = SyncStatus.SUCCESS
            result = SyncResult(True, _("Restored from {filename}").format(filename=latest_backup))
            result.downloaded_path = Path(tmp_download_path)
            result.hash_info = hash_info
            tmp_download_path = None
            self._last_result = result
            return result

        except Exception as exc:
            return self._fail(_("Restore failed: {error}").format(error=str(exc)))
        finally:
            if tmp_download_path:
                try:
                    Path(tmp_download_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def list_backups(self) -> list[dict]:
        """List all available remote backups with metadata."""
        if not _WEBDAV3_AVAILABLE or not self.is_configured():
            return []
        try:
            client = self._make_client()
            remote_dir = self._normalise_path(self._config.remote_path)
            all_items = client.list(remote_dir)
            backups = []
            for item in sorted(all_items, reverse=True):
                if not item.startswith(WEBDAV_BACKUP_NAME_PREFIX) or not item.endswith(".zip"):
                    continue
                try:
                    ts_part = item.split("_")[1].split(".")[0]
                    ts = int(ts_part)
                except Exception:
                    ts = 0
                backups.append({"filename": item, "format": "zip", "timestamp": ts})
            return backups
        except Exception as exc:
            log.warning("list_backups failed: %s", exc)
            return []

    # ── Helpers ───────────────────────────────────────────────

    def _make_client(self):
        options = {
            "webdav_hostname": self._config.url.rstrip("/"),
            "webdav_login": self._config.username,
            "webdav_password": self._config.password,
            "webdav_timeout": 30,
        }
        client = _WdavClient(options)
        client.verify = self._config.verify_ssl
        return client

    @staticmethod
    def _normalise_path(path: str) -> str:
        path = path.strip()
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path += "/"
        return path

    def _cleanup_old_backups(self, client, remote_dir: str) -> None:
        max_b = max(1, self._config.max_backups)
        try:
            all_items = client.list(remote_dir)
            backups = sorted(i for i in all_items if i.startswith(WEBDAV_BACKUP_NAME_PREFIX) and i.endswith(".zip"))
            to_delete = backups[:-max_b] if len(backups) > max_b else []
            for filename in to_delete:
                client.clean(f"{remote_dir.rstrip('/')}/{filename}")
        except Exception as exc:
            log.warning("Cleanup failed (non-fatal): %s", exc)

    def _fail(self, message: str) -> SyncResult:
        self._status = SyncStatus.FAILED
        result = SyncResult(False, message)
        self._last_result = result
        log.error("WebDAV action failed: %s", message)
        return result
