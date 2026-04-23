# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Resumable WebDAV transfer module with checkpointing.

Implements HTTP Range-based resumable download and robust streamed upload.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING

from webdav3.urn import Urn

if TYPE_CHECKING:
    from webdav3.client import Client

from src.utils.logger import get_logger

log = get_logger("webdav_resumable")

# Chunk size for resumable transfers (5 MB)
DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024
# Checkpoint save interval (every 10 MB downloaded)
CHECKPOINT_INTERVAL = 10 * 1024 * 1024


class ResumableDownloadState:
    """Tracks resumable download progress."""

    __slots__ = ("chunks", "created_at", "downloaded_bytes", "file_size", "last_updated", "local_path", "remote_path")

    def __init__(self, remote_path: str, local_path: Path, file_size: int):
        self.remote_path = remote_path
        self.local_path = str(local_path)
        self.file_size = file_size
        self.downloaded_bytes = 0
        self.chunks: dict[int, int] = {}  # {chunk_id: bytes_written}
        self.created_at = int(time.time())
        self.last_updated = self.created_at

    def to_dict(self) -> dict:
        return {
            "remote_path": self.remote_path,
            "local_path": self.local_path,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "chunks": self.chunks,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResumableDownloadState:
        obj = cls(data["remote_path"], Path(data["local_path"]), data["file_size"])
        obj.downloaded_bytes = data.get("downloaded_bytes", 0)
        obj.chunks = data.get("chunks", {})
        obj.created_at = data.get("created_at", int(time.time()))
        obj.last_updated = data.get("last_updated", obj.created_at)
        return obj


class ResumableUploadState:
    """Tracks resumable upload progress."""

    __slots__ = (
        "chunk_hashes",
        "created_at",
        "file_size",
        "last_updated",
        "local_path",
        "remote_path",
        "uploaded_bytes",
    )

    def __init__(self, remote_path: str, local_path: Path, file_size: int):
        self.remote_path = remote_path
        self.local_path = str(local_path)
        self.file_size = file_size
        self.uploaded_bytes = 0
        self.chunk_hashes: dict[int, str] = {}  # {chunk_id: sha256}
        self.created_at = int(time.time())
        self.last_updated = self.created_at

    def to_dict(self) -> dict:
        return {
            "remote_path": self.remote_path,
            "local_path": self.local_path,
            "file_size": self.file_size,
            "uploaded_bytes": self.uploaded_bytes,
            "chunk_hashes": self.chunk_hashes,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResumableUploadState:
        obj = cls(data["remote_path"], Path(data["local_path"]), data["file_size"])
        obj.uploaded_bytes = data.get("uploaded_bytes", 0)
        obj.chunk_hashes = data.get("chunk_hashes", {})
        obj.created_at = data.get("created_at", int(time.time()))
        obj.last_updated = data.get("last_updated", obj.created_at)
        return obj


class ResumableTransfer:
    """High-level resumable transfer coordinator."""

    def __init__(self, checkpoint_dir: Path | None = None, chunk_size: int = DEFAULT_CHUNK_SIZE):
        """Initialize resumable transfer.

        Args:
            checkpoint_dir: Directory for storing transfer state. If None, uses a temp directory.
            chunk_size: Size of each chunk in bytes.
        """
        self._checkpoint_dir = checkpoint_dir or Path.home() / ".cache" / "historysync_transfers"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._chunk_size = max(1024 * 1024, chunk_size)  # At least 1 MB
        self._lock = threading.Lock()
        self._active_transfers: dict[str, ResumableDownloadState | ResumableUploadState] = {}

    def _get_checkpoint_path(self, remote_path: str, operation: str) -> Path:
        """Get checkpoint file path for a transfer."""
        # Create a deterministic filename from remote_path
        path_hash = hashlib.md5(remote_path.encode()).hexdigest()[:8]
        return self._checkpoint_dir / f"{operation}_{path_hash}.json"

    def _save_checkpoint(self, state: ResumableDownloadState | ResumableUploadState, operation: str) -> None:
        """Save checkpoint to disk."""
        try:
            checkpoint_path = self._get_checkpoint_path(state.remote_path, operation)
            with checkpoint_path.open("w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2)
            transferred_bytes = getattr(state, "downloaded_bytes", getattr(state, "uploaded_bytes", 0))
            log.debug(
                "Checkpoint saved: %s (%.1f%%)",
                checkpoint_path,
                transferred_bytes / (state.file_size or 1) * 100,
            )
        except Exception as exc:
            log.warning("Failed to save checkpoint: %s", exc)

    def _load_checkpoint(self, remote_path: str, operation: str, state_class: type) -> dict | None:
        """Load checkpoint from disk if it exists and is fresh."""
        checkpoint_path = self._get_checkpoint_path(remote_path, operation)
        if not checkpoint_path.exists():
            return None
        try:
            with checkpoint_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Only restore if less than 24 hours old
            age_seconds = int(time.time()) - data.get("last_updated", 0)
            if age_seconds > 86400:
                log.debug("Checkpoint expired (%.1f hours old), discarding", age_seconds / 3600)
                checkpoint_path.unlink(missing_ok=True)
                return None
            return data
        except Exception as exc:
            log.warning("Failed to load checkpoint: %s", exc)
            checkpoint_path.unlink(missing_ok=True)
            return None

    def _delete_checkpoint(self, remote_path: str, operation: str) -> None:
        """Delete checkpoint after successful transfer."""
        checkpoint_path = self._get_checkpoint_path(remote_path, operation)
        try:
            checkpoint_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _temporary_remote_path(remote_path: str) -> str:
        """Build a deterministic temporary remote file path for atomic upload."""
        suffix = hashlib.md5(remote_path.encode("utf-8")).hexdigest()[:8]
        return f"{remote_path}.uploading.{suffix}"

    def download_resumable(
        self,
        client: Client,
        remote_path: str,
        local_path: Path,
        progress_callback: Callable[[int, int], None] | None = None,
        force_restart: bool = False,
    ) -> None:
        """Download a file with resumable support.

        Uses HTTP Range requests to resume from the last checkpoint.

        Args:
            client: WebDAV client instance.
            remote_path: Remote file path on WebDAV server.
            local_path: Local destination path.
            progress_callback: Called with (downloaded_bytes, total_bytes) for progress updates.
            force_restart: Discard any existing checkpoint and start fresh.

        Raises:
            IOError: If download fails.
        """
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Get file size from server
        try:
            info = client.info(remote_path)
            file_size = int(info.get("size", 0))
            if file_size <= 0:
                raise ValueError("Invalid file size from server")
        except Exception as exc:
            raise OSError(f"Failed to get remote file size: {exc}") from exc

        # Try to restore from checkpoint
        state_data = None if force_restart else self._load_checkpoint(remote_path, "download", ResumableDownloadState)

        if state_data and state_data["file_size"] == file_size and Path(state_data["local_path"]).exists():
            # Resume from checkpoint
            state = ResumableDownloadState.from_dict(state_data)
            log.info(
                "Resuming download from %.1f MB (%.1f%%)",
                state.downloaded_bytes / 1024 / 1024,
                state.downloaded_bytes / file_size * 100,
            )
        else:
            # Start fresh
            state = ResumableDownloadState(remote_path, local_path, file_size)
            if local_path.exists():
                local_path.unlink()

        with self._lock:
            self._active_transfers[remote_path] = state

        try:
            urn = Urn(remote_path)

            # Download with Range support
            with local_path.open("ab") as dst:
                bytes_downloaded = state.downloaded_bytes
                last_checkpoint = bytes_downloaded

                while bytes_downloaded < file_size:
                    # Calculate range for this chunk
                    range_end = min(bytes_downloaded + self._chunk_size, file_size)
                    range_header = f"bytes={bytes_downloaded}-{range_end - 1}"

                    try:
                        response = client.execute_request(
                            "download",
                            urn.quote(),
                            headers_ext=[f"Range: {range_header}"],
                        )
                        if bytes_downloaded > 0 and response.status_code != 206:
                            raise OSError(f"Server did not honor Range request (status {response.status_code})")

                        # Write chunk
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                dst.write(chunk)
                                bytes_downloaded += len(chunk)
                                state.downloaded_bytes = bytes_downloaded

                                if progress_callback:
                                    progress_callback(bytes_downloaded, file_size)

                                # Save checkpoint periodically
                                if bytes_downloaded - last_checkpoint >= CHECKPOINT_INTERVAL:
                                    self._save_checkpoint(state, "download")
                                    last_checkpoint = bytes_downloaded

                    except Exception as exc:
                        log.warning("Chunk download failed at %.1f MB: %s", bytes_downloaded / 1024 / 1024, exc)
                        self._save_checkpoint(state, "download")
                        raise OSError(f"Download interrupted at {bytes_downloaded} bytes: {exc}") from exc

            # Download complete, verify and cleanup
            log.info("Download completed: %s (%.1f MB)", local_path, file_size / 1024 / 1024)
            self._delete_checkpoint(remote_path, "download")

        finally:
            with self._lock:
                self._active_transfers.pop(remote_path, None)

    def upload_resumable(
        self,
        client: Client,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Upload a file using a streamed PUT to a temporary remote path.

        Generic WebDAV resumable upload is not portable across servers. For the
        upload path we therefore favour the most reliable behaviour available in
        webdav3: stream the local file with progress reporting into a temporary
        remote object, then atomically move it into place on success.

        Args:
            client: WebDAV client instance.
            local_path: Local file path.
            remote_path: Remote destination path on WebDAV server.
            progress_callback: Called with (uploaded_bytes, total_bytes) for progress updates.

        Raises:
            IOError: If upload fails.
        """
        local_path = Path(local_path)
        if not local_path.exists():
            raise OSError(f"Local file not found: {local_path}")

        file_size = local_path.stat().st_size
        temp_remote_path = self._temporary_remote_path(remote_path)
        state = ResumableUploadState(remote_path, local_path, file_size)

        def _upload_progress(current: int, total: int, *_args) -> None:
            uploaded = min(total, max(current, state.uploaded_bytes))
            state.uploaded_bytes = uploaded
            if progress_callback:
                progress_callback(uploaded, total)

        with self._lock:
            self._active_transfers[remote_path] = state

        try:
            log.info(
                "Starting streamed upload: %s -> %s via %s (%.1f MB)",
                local_path,
                remote_path,
                temp_remote_path,
                file_size / 1024 / 1024,
            )
            client.upload_file(
                temp_remote_path,
                str(local_path),
                progress=_upload_progress,
                force=True,
            )
            state.uploaded_bytes = file_size
            if progress_callback:
                progress_callback(file_size, file_size)
            client.move(temp_remote_path, remote_path, overwrite=True)
            log.info("Upload completed: %s", remote_path)
        except Exception as exc:
            try:
                if client.check(temp_remote_path):
                    client.clean(temp_remote_path)
            except Exception as cleanup_exc:
                log.warning("Failed to clean temporary remote upload %s: %s", temp_remote_path, cleanup_exc)
            log.error("Upload failed: %s", exc)
            raise OSError(f"Upload failed: {exc}") from exc
        finally:
            with self._lock:
                self._active_transfers.pop(remote_path, None)

    def cleanup_old_checkpoints(self, max_age_hours: int = 24) -> None:
        """Clean up old checkpoint files."""
        max_age_seconds = max_age_hours * 3600
        now = int(time.time())
        try:
            for checkpoint_file in self._checkpoint_dir.glob("*.json"):
                try:
                    with checkpoint_file.open("r") as f:
                        data = json.load(f)
                    age = now - data.get("last_updated", 0)
                    if age > max_age_seconds:
                        checkpoint_file.unlink()
                        log.debug("Deleted old checkpoint: %s", checkpoint_file)
                except Exception as exc:
                    log.debug("Failed to check/delete checkpoint %s: %s", checkpoint_file, exc)
        except Exception as exc:
            log.warning("Cleanup failed: %s", exc)
