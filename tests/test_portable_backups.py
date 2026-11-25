# Copyright (c) 2026, HistorySync contributors
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock
import zipfile

import pytest

from src.services.backup_archive import export_zip, import_zip
from src.services.github_backup import github_backup
from src.services.local_db import LocalDatabase


def test_zip_round_trip_and_repeat(local_db, make_rec, tmp_path):
    local_db.upsert_records([make_rec()])
    path = tmp_path / "transfer.zip"
    export_zip(local_db, path)
    target = LocalDatabase(tmp_path / "target.db")
    try:
        target.upsert_records([make_rec(url="https://other.example")])
        import_zip(target, path)
        import_zip(target, path)
        assert target.get_total_count() == 2
    finally:
        target.close()


def test_new_installation_can_export_an_empty_snapshot(local_db, tmp_path):
    path = tmp_path / "empty.zip"
    export_zip(local_db, path)
    assert import_zip(local_db, path) == 0


def test_corrupt_zip_leaves_database_intact(local_db, tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("history.db", b"broken")
        archive.writestr("manifest.sha256.json", '{"history.db":"incorrect"}')
    with pytest.raises(ValueError, match="checksum"):
        import_zip(local_db, path)
    assert local_db.get_total_count() == 0


def test_export_error_preserves_previous_file(local_db, tmp_path, monkeypatch):
    path = tmp_path / "history.zip"
    path.write_bytes(b"previous")
    monkeypatch.setattr(local_db, "export_without_fts", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        export_zip(local_db, path)
    assert path.read_bytes() == b"previous"


@pytest.fixture
def session(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("src.services.github_backup.requests.Session", lambda: mock)
    return mock.__enter__.return_value


def metadata(private=True):
    response = MagicMock()
    response.is_redirect = False
    response.json.return_value = {"private": private, "default_branch": "main", "id": 123}
    return response


def test_public_repository_rejected_before_transfer(session, local_db):
    session.get.return_value = metadata(False)
    with pytest.raises(ValueError, match="private"):
        github_backup(local_db, "owner/repo", "test")
    session.put.assert_not_called()
    assert session.get.call_count == 1


@pytest.mark.parametrize("existing", [False, True])
def test_github_upload_and_restore(session, local_db, make_rec, tmp_path, existing):
    import base64

    local_db.upsert_records([make_rec()])
    current = MagicMock(status_code=200 if existing else 404)
    current.json.return_value = {"sha": "original"}
    session.get.side_effect = [metadata(), current]
    session.put.return_value.status_code = 200 if existing else 201
    github_backup(local_db, "owner/repo", "test")
    endpoint = session.put.call_args.args[0]
    assert endpoint.endswith("/contents/HistorySync/history.zip")
    payload = session.put.call_args.kwargs["json"]
    assert payload.get("sha") == ("original" if existing else None)
    assert payload["branch"] == "main"
    response = MagicMock()
    response.__enter__.return_value.status_code = 200
    response.__enter__.return_value.iter_content.return_value = [base64.b64decode(payload["content"])]
    session.get.side_effect = [metadata(), response]
    target = LocalDatabase(tmp_path / "target.db")
    try:
        github_backup(target, "owner/repo", "test", restore=True)
        assert target.get_total_count() == 1
    finally:
        target.close()
