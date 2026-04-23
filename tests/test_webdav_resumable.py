# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for resumable WebDAV transfers.
"""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

import pytest

from src.services.webdav_resumable import (
    ResumableDownloadState,
    ResumableTransfer,
    ResumableUploadState,
)


class TestResumableDownloadState:
    """Test download state serialization."""

    def test_state_serialization(self):
        """Test state can be serialized and deserialized."""
        state = ResumableDownloadState("/path/to/file.zip", Path("/tmp/file.zip"), 1024 * 1024)
        state.downloaded_bytes = 512 * 1024
        state.chunks = {0: 512 * 1024}

        data = state.to_dict()
        restored = ResumableDownloadState.from_dict(data)

        assert restored.remote_path == "/path/to/file.zip"
        assert str(Path(restored.local_path)) == str(Path("/tmp/file.zip"))
        assert restored.file_size == 1024 * 1024
        assert restored.downloaded_bytes == 512 * 1024
        assert restored.chunks == {0: 512 * 1024}

    def test_state_checkpoint_path(self):
        """Test checkpoint path generation."""
        transfer = ResumableTransfer()
        path1 = transfer._get_checkpoint_path("/path/to/file1.zip", "download")
        path2 = transfer._get_checkpoint_path("/path/to/file2.zip", "download")
        path3 = transfer._get_checkpoint_path("/path/to/file1.zip", "upload")

        # Same remote path and operation should give same checkpoint
        assert path1 == transfer._get_checkpoint_path("/path/to/file1.zip", "download")
        # Different remote path should give different checkpoint
        assert path1 != path2
        # Different operation should give different checkpoint
        assert path1 != path3


class TestResumableUploadState:
    """Test upload state serialization."""

    def test_state_serialization(self):
        """Test upload state can be serialized and deserialized."""
        state = ResumableUploadState("/remote/file.zip", Path("/local/file.zip"), 1024 * 1024)
        state.uploaded_bytes = 256 * 1024
        state.chunk_hashes = {0: "abcd1234"}

        data = state.to_dict()
        restored = ResumableUploadState.from_dict(data)

        assert restored.remote_path == "/remote/file.zip"
        assert str(Path(restored.local_path)) == str(Path("/local/file.zip"))
        assert restored.file_size == 1024 * 1024
        assert restored.uploaded_bytes == 256 * 1024
        assert restored.chunk_hashes == {0: "abcd1234"}


class TestResumableTransfer:
    """Test resumable transfer coordination."""

    def test_checkpoint_save_and_load(self):
        """Test checkpoint can be saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            state = ResumableDownloadState("/test/file.zip", Path("file.zip"), 1024 * 1024)
            state.downloaded_bytes = 512 * 1024

            transfer._save_checkpoint(state, "download")

            loaded_data = transfer._load_checkpoint("/test/file.zip", "download", ResumableDownloadState)
            assert loaded_data is not None
            assert loaded_data["downloaded_bytes"] == 512 * 1024
            assert loaded_data["file_size"] == 1024 * 1024

    def test_checkpoint_cleanup(self):
        """Test checkpoint cleanup on successful transfer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            state = ResumableDownloadState("/test/file.zip", Path("file.zip"), 1024)

            transfer._save_checkpoint(state, "download")
            checkpoint_path = transfer._get_checkpoint_path("/test/file.zip", "download")
            assert checkpoint_path.exists()

            transfer._delete_checkpoint("/test/file.zip", "download")
            assert not checkpoint_path.exists()

    def test_checkpoint_expiry(self):
        """Test old checkpoints are not loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            state = ResumableDownloadState("/test/file.zip", Path("file.zip"), 1024)
            state.last_updated = 0  # Set to ancient time

            transfer._save_checkpoint(state, "download")
            loaded_data = transfer._load_checkpoint("/test/file.zip", "download", ResumableDownloadState)

            # Should be None because checkpoint is too old
            assert loaded_data is None

    def test_chunk_size_minimum(self):
        """Test chunk size has a reasonable minimum."""
        transfer = ResumableTransfer(chunk_size=100)  # Try to set too small
        assert transfer._chunk_size >= 1024 * 1024  # Should be at least 1 MB

    def test_cleanup_old_checkpoints(self):
        """Test cleanup of old checkpoint files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))

            # Create some old checkpoint files
            old_checkpoint = transfer._checkpoint_dir / "download_abc123.json"
            old_data = {
                "remote_path": "/old/file.zip",
                "local_path": "/tmp/file.zip",
                "file_size": 1024,
                "downloaded_bytes": 512,
                "chunks": {},
                "created_at": 0,
                "last_updated": 0,  # Very old
            }
            with old_checkpoint.open("w") as f:
                json.dump(old_data, f)

            assert old_checkpoint.exists()
            transfer.cleanup_old_checkpoints(max_age_hours=1)
            assert not old_checkpoint.exists()  # Should be deleted


class TestResumableDownload:
    """Test resumable download functionality."""

    def test_download_file_not_found(self):
        """Test download fails gracefully when remote file doesn't exist."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "file.zip"

            # Mock server error
            client.info.side_effect = OSError("File not found")

            with pytest.raises(IOError, match="Failed to get remote file size"):
                transfer.download_resumable(client, "/remote/file.zip", local_path)

    def test_download_invalid_file_size(self):
        """Test download fails with invalid file size."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "file.zip"

            # Mock server returning invalid size
            client.info.return_value = {"size": "0"}

            with pytest.raises(IOError, match="Invalid file size"):
                transfer.download_resumable(client, "/remote/file.zip", local_path)

    def test_download_uses_execute_request_for_authenticated_range_request(self):
        """Test resumable download uses the client's authenticated request path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "file.zip"
            client.info.return_value = {"size": "4"}

            response = MagicMock()
            response.status_code = 200
            response.iter_content.return_value = [b"data"]
            client.execute_request.return_value = response

            transfer.download_resumable(client, "/remote/file.zip", local_path)

            client.execute_request.assert_called_once_with(
                "download",
                "/remote/file.zip",
                headers_ext=["Range: bytes=0-3"],
            )
            assert local_path.read_bytes() == b"data"

    def test_download_rejects_resume_when_server_ignores_range(self):
        """Test resumed downloads fail instead of corrupting the file when the server ignores Range."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "file.zip"
            local_path.write_bytes(b"part")
            client.info.return_value = {"size": "8"}
            state = ResumableDownloadState("/remote/file.zip", local_path, 8)
            state.downloaded_bytes = 4
            transfer._save_checkpoint(state, "download")

            response = MagicMock()
            response.status_code = 200
            response.iter_content.return_value = [b"rest"]
            client.execute_request.return_value = response

            with pytest.raises(OSError, match="Server did not honor Range request"):
                transfer.download_resumable(client, "/remote/file.zip", local_path)


class TestResumableUpload:
    """Test resumable upload functionality."""

    def test_upload_with_file_missing(self):
        """Test upload fails gracefully when local file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "nonexistent.zip"

            with pytest.raises(IOError, match="Local file not found"):
                transfer.upload_resumable(client, local_path, "/remote/file.zip")

    def test_upload_uses_temp_remote_file_and_moves_on_success(self):
        """Test upload uses a temp remote path before atomically moving into place."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "upload.zip"
            local_path.write_bytes(b"payload")
            temp_remote_path = transfer._temporary_remote_path("/remote/file.zip")
            progress_calls: list[tuple[int, int]] = []

            def _upload_file(remote_path, local_path_arg, progress=None, force=False):
                assert remote_path == temp_remote_path
                assert local_path_arg == str(local_path)
                assert force is True
                assert callable(progress)
                progress(0, 7)
                progress(3, 7)

            client.upload_file.side_effect = _upload_file

            transfer.upload_resumable(
                client,
                local_path,
                "/remote/file.zip",
                progress_callback=lambda uploaded, total: progress_calls.append((uploaded, total)),
            )

            client.move.assert_called_once_with(temp_remote_path, "/remote/file.zip", overwrite=True)
            client.clean.assert_not_called()
            assert progress_calls[0] == (0, 7)
            assert progress_calls[-1] == (7, 7)

    def test_upload_cleans_temp_remote_file_on_failure(self):
        """Test failed upload cleans the temporary remote file when present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transfer = ResumableTransfer(checkpoint_dir=Path(tmpdir))
            client = MagicMock()
            local_path = Path(tmpdir) / "upload.zip"
            local_path.write_bytes(b"payload")
            temp_remote_path = transfer._temporary_remote_path("/remote/file.zip")
            client.upload_file.side_effect = RuntimeError("boom")
            client.check.return_value = True

            with pytest.raises(IOError, match="Upload failed: boom"):
                transfer.upload_resumable(client, local_path, "/remote/file.zip")

            client.clean.assert_called_once_with(temp_remote_path)
            client.move.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
