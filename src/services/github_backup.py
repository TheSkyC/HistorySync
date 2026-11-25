# Copyright (c) 2026, HistorySync contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import requests

from src.services.backup_archive import export_zip, import_zip
from src.services.local_db import LocalDatabase
from src.utils.i18n_core import _

_MAX_BYTES = 100 * 1024 * 1024
_BACKUP_PATH = "HistorySync/history.zip"


def github_backup(db: LocalDatabase, repository: str, token: str, *, restore: bool = False) -> None:
    """Back up or merge a ZIP from the default branch of a private GitHub repository."""
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository) or repository.split("/")[1] in {".", ".."}:
        raise ValueError(_("Enter a GitHub repository as owner/name."))
    if not token.strip():
        raise ValueError(_("Enter a GitHub access token."))

    with requests.Session() as session, TemporaryDirectory() as tmp:
        session.headers.update({"Authorization": f"Bearer {token.strip()}", "Accept": "application/vnd.github+json"})
        url = f"https://api.github.com/repos/{repository}"
        meta = session.get(url, timeout=30, allow_redirects=False)
        if meta.is_redirect:
            raise ValueError(_("The repository moved. Enter its current owner/name."))
        meta.raise_for_status()
        repo = meta.json()
        if repo.get("private") is not True:
            raise ValueError(_("Choose a private repository for your browsing history."))
        branch = repo["default_branch"]
        endpoint = f"https://api.github.com/repositories/{int(repo['id'])}/contents/{_BACKUP_PATH}"
        archive = Path(tmp) / "history.zip"
        if restore:
            with session.get(
                endpoint,
                params={"ref": branch},
                headers={"Accept": "application/vnd.github.raw+json"},
                timeout=120,
                stream=True,
                allow_redirects=False,
            ) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(_("GitHub did not return the backup file."))
                with archive.open("wb") as dst:
                    for chunk in response.iter_content(1024 * 1024):
                        if dst.tell() + len(chunk) > _MAX_BYTES:
                            raise ValueError(_("GitHub backups are limited to 100 MiB. Use a local ZIP instead."))
                        dst.write(chunk)
            import_zip(db, archive)
            return

        # Capture the starting revision so concurrent writers cannot overwrite each other silently.
        current = session.get(endpoint, params={"ref": branch}, timeout=30, allow_redirects=False)
        payload = {"message": "Back up HistorySync database", "branch": branch}
        if current.status_code != 404:
            current.raise_for_status()
            payload["sha"] = current.json()["sha"]
        export_zip(db, archive)
        if archive.stat().st_size > _MAX_BYTES:
            raise ValueError(_("GitHub backups are limited to 100 MiB. Use a local ZIP instead."))
        payload["content"] = base64.b64encode(archive.read_bytes()).decode("ascii")
        result = session.put(endpoint, json=payload, timeout=120, allow_redirects=False)
        if result.status_code == 409:
            raise ValueError(_("The remote backup changed. Restore it before uploading again."))
        result.raise_for_status()
        if result.status_code not in (200, 201):
            raise ValueError(_("GitHub did not confirm the upload."))
