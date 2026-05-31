# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QDialog

from src.services.update_models import ReleaseInfo, UpdateAsset, UpdateInfo
from src.views.dialogs.update_dialog import UpdateDialog


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_update_info(version: str = "1.4.0") -> UpdateInfo:
    release = ReleaseInfo(
        version=version,
        tag=f"v{version}",
        channel="stable",
        published_at="2026-05-30",
        summary="Great update",
        notes_url="https://example.com/release",
        min_supported_version="",
    )
    asset = UpdateAsset(
        asset_id="test-asset",
        platform="windows",
        arch="x64",
        kind="installer",
        fmt="exe",
        filename="setup.exe",
        label="Test",
        size_bytes=1000,
        sha256="a" * 64,
        sha256_status="verified",
        url_download="https://example.com/setup.exe",
        url_direct="https://example.com/setup.exe",
        url_github="https://example.com/release",
        url_mirrors=(),
        rollout=100,
    )
    return UpdateInfo(release=release, asset=asset, source="dl", current_version="1.3.2")


def test_skip_closes_dialog(qapp):
    dlg = UpdateDialog(_make_update_info())
    skipped: list[str] = []
    dlg.skip_requested.connect(skipped.append)

    dlg._skip_btn.click()

    assert skipped == ["1.4.0"]
    assert dlg.result() == QDialog.Accepted


def test_remind_later_emits_and_closes_dialog(qapp):
    dlg = UpdateDialog(_make_update_info())
    reminded: list[bool] = []
    dlg.remind_later.connect(lambda: reminded.append(True))

    dlg._later_btn.click()

    assert reminded == [True]
    assert dlg.result() == QDialog.Accepted
