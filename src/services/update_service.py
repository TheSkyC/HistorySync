# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Qt orchestration for the online-update system.

:class:`UpdateService` is a long-lived ``QObject`` (owned by the main
view-model) that exposes a small signal surface to the GUI and runs all I/O on
background ``QThread`` workers, mirroring the canonical worker/cleanup pattern
used by :mod:`src.services.scheduler`.

Responsibilities:

* Decide whether/when to check (``should_auto_check``) and run the check off the
  UI thread via :class:`UpdateCheckWorker` (dl primary, GitHub fallback).
* Apply gating to *automatic* notifications only: skipped versions and gradual
  rollout (hashed on the stable ``device_uuid``).  Manual checks always report.
* Download the selected asset with HTTP ``Range`` resume and SHA-256
  verification via :class:`UpdateDownloadWorker`, trying mirror/dl/GitHub
  sources in a learned order.
* Land a verified artifact according to the detected install form
  (run installer / open disk-image / reveal file / open release page).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
import requests

from src.models.app_config import AppConfig
from src.services import update_debug
from src.services.update_fetch import (
    build_download_candidates,
    default_headers,
    download_token_order,
    fetch_latest,
    metadata_source_order,
)
from src.services.update_models import UpdateInfo, api_locale
from src.utils.constants import (
    APP_VERSION,
    UPDATE_CHECK_INTERVAL_SEC,
    UPDATE_DOWNLOAD_CHUNK_SIZE,
    UPDATE_DOWNLOAD_DIR_NAME,
    UPDATE_HTTP_CONNECT_TIMEOUT,
    UPDATE_HTTP_READ_TIMEOUT,
    UPDATE_POLICY_AUTO_INSTALL,
    UPDATE_POLICY_NOTIFY_DOWNLOAD,
    UPDATE_POLICY_NOTIFY_ONLY,
    UPDATE_RELEASES_PAGE,
)
from src.utils.i18n import _, lang_manager
from src.utils.install_context import (
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    detect_install_context,
)
from src.utils.logger import get_logger
from src.utils.path_helper import get_app_data_dir

log = get_logger("update.service")

_DOWNLOAD_TIMEOUT = (UPDATE_HTTP_CONNECT_TIMEOUT, UPDATE_HTTP_READ_TIMEOUT)
_REMIND_LATER_WEEK_SEC = 7 * 24 * 60 * 60
_AUTO_REMIND_WEEK_SEC = 7 * 24 * 60 * 60


def _update_identity(info: UpdateInfo | None) -> tuple[str, str]:
    """Stable identity for matching a downloaded artifact to an update."""
    if info is None:
        return ("", "")
    version = info.release.version or ""
    asset_id = info.asset.asset_id if info.asset is not None else ""
    return version, asset_id


class _CancelledError(Exception):
    """Internal sentinel raised inside the download loop on cancellation."""


def _download_headers() -> dict[str, str]:
    """Return headers for artifact download requests (no JSON Accept)."""
    h = default_headers().copy()
    h.pop("Accept", None)
    return h


# ── Workers ────────────────────────────────────────────────────────────────────


class UpdateCheckWorker(QObject):
    """Fetch the latest release metadata off the UI thread."""

    finished = Signal(object, str)  # UpdateInfo, source
    failed = Signal(str)

    def __init__(
        self,
        *,
        context,
        channel: str,
        locale: str,
        current_version: str,
        source_order: list[str],
    ):
        super().__init__()
        self._context = context
        self._channel = channel
        self._locale = locale
        self._current_version = current_version
        self._source_order = source_order
        self._session = requests.Session()
        self._session.headers.update(_download_headers())
        self._session.headers["Accept"] = "application/json"

    def cancel(self) -> None:
        """Close the underlying session to unblock any in-flight HTTP request."""
        try:
            self._session.close()
        except Exception:
            pass

    @Slot()
    def run(self) -> None:
        try:
            info, source, error = fetch_latest(
                self._context,
                self._channel,
                self._locale,
                self._current_version,
                self._source_order,
                session=self._session,
            )
        except Exception as exc:
            # A closed session (cancel) produces a low-level connection error;
            # surface a friendlier message so the user never sees raw internals.
            msg = str(exc)
            if any(kw in msg.lower() for kw in ("connection aborted", "connection broken", "closed", "pool closed")):
                self.failed.emit(_("The update check was cancelled."))
            else:
                self.failed.emit(msg)
            return
        if info is not None:
            self.finished.emit(info, source)
        else:
            self.failed.emit(error or _("No update source was reachable."))


class UpdateDownloadWorker(QObject):
    """Download + verify an asset, trying each candidate source in turn."""

    progress = Signal(int, int)  # received_bytes, total_bytes
    finished = Signal(str, str)  # local_path, source_token
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        candidates: list[tuple[str, str]],
        dest_path: Path,
        expected_sha256: str,
        expected_size: int,
        chunk_size: int = UPDATE_DOWNLOAD_CHUNK_SIZE,
    ):
        super().__init__()
        self._candidates = candidates
        self._dest = Path(dest_path)
        self._part = self._dest.with_suffix(self._dest.suffix + ".part")
        self._etag_path = self._dest.with_suffix(self._dest.suffix + ".etag")
        self._expected_sha256 = (expected_sha256 or "").lower()
        self._expected_size = expected_size or 0
        self._chunk = max(64 * 1024, int(chunk_size))
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        last_err = ""
        for token, url in self._candidates:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            try:
                self._download_one(url)
                if self._cancel.is_set():
                    self.cancelled.emit()
                    return
                verify_error = self._verify()
                if verify_error:
                    # A bad artifact from this source — discard and try the next.
                    last_err = verify_error
                    log.warning("Update artifact from %s failed verification: %s", token, verify_error)
                    self._safe_unlink(self._part)
                    self._safe_unlink(self._etag_path)
                    continue
                self._part.replace(self._dest)
                self._safe_unlink(self._etag_path)
                self.finished.emit(str(self._dest), token)
                return
            except _CancelledError:
                self.cancelled.emit()
                return
            except Exception as exc:
                last_err = str(exc)
                log.warning("Update download from %s (%s) failed: %s", token, url, exc)
                continue
        if self._cancel.is_set():
            self.cancelled.emit()
        else:
            self.failed.emit(last_err or _("Download failed."))

    def _download_one(self, url: str) -> None:
        resume_from = self._part.stat().st_size if self._part.exists() else 0
        headers = _download_headers()

        if resume_from > 0:
            # Validate that the .part file belongs to the same remote resource
            # by sending If-Range with the stored ETag (if available).
            stored_etag = self._read_etag()
            headers["Range"] = f"bytes={resume_from}-"
            if stored_etag:
                headers["If-Range"] = stored_etag

        with requests.get(url, headers=headers, stream=True, timeout=_DOWNLOAD_TIMEOUT, allow_redirects=True) as resp:
            if resp.status_code == 416:
                # Range not satisfiable — .part may already be complete.
                self._handle_416(resp, url)
                return
            if resp.status_code == 206 and resume_from > 0:
                mode = "ab"
            elif resp.status_code == 200:
                # Server ignored Range / If-Range invalidated the resume: full body.
                resume_from = 0
                mode = "wb"
                # Discard stale .part — the resource changed
                self._safe_unlink(self._part)
            else:
                resp.raise_for_status()
                raise OSError(f"unexpected status {resp.status_code}")

            # Store the ETag for future resume validation
            etag = resp.headers.get("ETag", "")
            if etag:
                self._write_etag(etag)

            total = self._resolve_total(resp, resume_from)
            received = resume_from
            self.progress.emit(received, total)
            with self._part.open(mode) as fh:
                for chunk in resp.iter_content(chunk_size=self._chunk):
                    if self._cancel.is_set():
                        raise _CancelledError
                    if not chunk:
                        continue
                    fh.write(chunk)
                    received += len(chunk)
                    self.progress.emit(received, total)

    def _handle_416(self, resp: requests.Response, url: str) -> None:
        """Handle HTTP 416 (Range Not Satisfiable).

        If the .part file size matches the expected asset size, assume it is
        complete and let verification proceed.  Otherwise discard and re-fetch.
        """
        part_size = self._part.stat().st_size if self._part.exists() else 0
        if self._expected_size and part_size == self._expected_size:
            log.info("HTTP 416 but .part size matches expected; treating as complete")
            return
        # Content-Range: */total can tell us the resource size
        content_range = resp.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                resource_size = int(content_range.rsplit("/", 1)[-1])
                if part_size == resource_size:
                    log.info("HTTP 416 and .part matches Content-Range total; treating as complete")
                    return
            except (ValueError, IndexError):
                pass
        # .part is stale or corrupt — discard and re-download from scratch
        log.warning("HTTP 416: discarding stale .part (%d bytes) and restarting download", part_size)
        self._safe_unlink(self._part)
        self._safe_unlink(self._etag_path)
        # Honour cancellation *before* the re-fetch so that a cancel() call
        # that arrived while we were processing the 416 response does not
        # result in a wasted HTTP request.
        if self._cancel.is_set():
            raise _CancelledError
        # Re-fetch without Range
        headers = _download_headers()
        with requests.get(url, headers=headers, stream=True, timeout=_DOWNLOAD_TIMEOUT, allow_redirects=True) as resp2:
            resp2.raise_for_status()
            etag = resp2.headers.get("ETag", "")
            if etag:
                self._write_etag(etag)
            total = self._resolve_total(resp2, 0)
            received = 0
            self.progress.emit(received, total)
            with self._part.open("wb") as fh:
                for chunk in resp2.iter_content(chunk_size=self._chunk):
                    if self._cancel.is_set():
                        raise _CancelledError
                    if not chunk:
                        continue
                    fh.write(chunk)
                    received += len(chunk)
                    self.progress.emit(received, total)

    def _read_etag(self) -> str:
        """Read the stored ETag for the current .part file, or ''."""
        try:
            return self._etag_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _write_etag(self, etag: str) -> None:
        """Persist the ETag alongside the .part file for resume validation."""
        try:
            self._etag_path.write_text(etag, encoding="utf-8")
        except OSError:
            pass

    def _resolve_total(self, resp: requests.Response, resume_from: int) -> int:
        content_range = resp.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                return int(content_range.rsplit("/", 1)[-1])
            except (ValueError, IndexError):
                pass
        try:
            length = int(resp.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length:
            return resume_from + length if resp.status_code == 206 else length
        return self._expected_size

    def _verify(self) -> str:
        """Return "" on success, or a human-readable error describing the failure.

        Cancellation is *not* checked during verification: the download is
        already complete at this point and verification is fast (typically
        under a second even for large artifacts).  If the user cancelled,
        the caller will discard the .part afterwards via the normal cancel
        path rather than raising mid-verification and leaving an unusable
        partial file.
        """
        if not self._part.exists():
            return _("Downloaded file is missing.")
        actual_size = self._part.stat().st_size
        if self._expected_size and actual_size != self._expected_size:
            return _("Size mismatch (expected {expected}, got {actual}).").format(
                expected=self._expected_size, actual=actual_size
            )
        if self._expected_sha256:
            digest = hashlib.sha256()
            with self._part.open("rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != self._expected_sha256:
                return _("Checksum verification failed — the download may be corrupt or tampered with.")
        return ""

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ── Service ─────────────────────────────────────────────────────────────────────


class UpdateService(QObject):
    """Coordinates update checks, downloads, and applying, for the GUI."""

    check_started = Signal()
    update_available = Signal(object)  # UpdateInfo (newer + passed gating)
    update_not_available = Signal(object)  # UpdateInfo (latest, but not newer / gated)
    check_failed = Signal(str)

    download_started = Signal()
    download_progress = Signal(int, int)  # received, total
    download_finished = Signal(str)  # verified local path
    download_failed = Signal(str)
    download_cancelled = Signal()

    apply_failed = Signal(str)
    quit_requested = Signal()  # ask the app to quit so an installer can take over
    config_save_failed = Signal(str)  # emitted when config.save() fails in the service

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._context = detect_install_context()
        # Debug override: allow injecting a simulated older version so the
        # update check sees "update available" without editing constants.
        debug_version = update_debug.current_version()
        self._current_version = debug_version if debug_version is not None else APP_VERSION
        self._latest: UpdateInfo | None = None
        self._downloaded_path: Path | None = None
        self._downloaded_identity: tuple[str, str] = ("", "")
        self._active_download_identity: tuple[str, str] = ("", "")
        # Backward-compatible manual-check flag used by a few direct callers
        # and tests that invoke _on_check_finished() without the explicit arg.
        self._check_manual: bool = False

        self._check_thread: QThread | None = None
        self._check_worker: UpdateCheckWorker | None = None

        self._dl_thread: QThread | None = None
        self._dl_worker: UpdateDownloadWorker | None = None
        # Monotonic counter that guards against stale deferred signals from the
        # artifact-reuse fast path (QTimer.singleShot).  Every call to
        # download_async increments it; the deferred _reuse_download_done
        # ignores the emission when a newer download_async has since started.
        self._download_gen: int = 0

        log.info("UpdateService init: %s", self._context.describe())

    # ── Read-only accessors ───────────────────────────────────

    @property
    def context(self):
        return self._context

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def latest_update(self) -> UpdateInfo | None:
        return self._latest

    @property
    def downloaded_path(self) -> Path | None:
        return self._downloaded_path

    def active_downloaded_path(self) -> Path | None:
        """Return the downloaded artifact only when it matches the current update."""
        info = self.pending_update() or self._latest
        return self._downloaded_path_for_info(info)

    def is_checking(self) -> bool:
        return self._check_thread is not None and self._check_thread.isRunning()

    def is_downloading(self) -> bool:
        return self._dl_thread is not None and self._dl_thread.isRunning()

    def pending_update(self) -> UpdateInfo | None:
        """The currently-known update if it is newer and not skipped, else None."""
        info = self._latest
        if info is None or not info.is_update_available:
            return None
        if self.is_version_skipped(info.release.version):
            return None
        return info

    def current_policy(self) -> str:
        """Return the configured update policy, normalized to a supported value."""
        policy = self._config.updater.policy or UPDATE_POLICY_NOTIFY_DOWNLOAD
        if policy not in (UPDATE_POLICY_NOTIFY_ONLY, UPDATE_POLICY_NOTIFY_DOWNLOAD, UPDATE_POLICY_AUTO_INSTALL):
            return UPDATE_POLICY_NOTIFY_DOWNLOAD
        if policy == UPDATE_POLICY_AUTO_INSTALL and not self._context.can_self_update:
            return UPDATE_POLICY_NOTIFY_DOWNLOAD
        return policy

    def should_offer_download(self) -> bool:
        """Whether the current policy allows in-app download/apply actions."""
        return self.current_policy() != UPDATE_POLICY_NOTIFY_ONLY and self._context.can_self_update

    def should_auto_download_on_availability(self) -> bool:
        """Whether a newly surfaced update should begin downloading automatically."""
        return self.current_policy() == UPDATE_POLICY_AUTO_INSTALL

    def should_apply_on_quit(self) -> bool:
        """Whether quit should attempt to hand off a downloaded update."""
        if self.current_policy() != UPDATE_POLICY_AUTO_INSTALL:
            return False
        info = self.pending_update() or self._latest
        version = info.release.version if info is not None else ""
        if self.is_install_deferred(version):
            return False
        return self._downloaded_path_for_info(info) is not None

    # ── Auto-check gating ─────────────────────────────────────

    def should_auto_check(self) -> bool:
        """Whether an automatic background check should run now.

        Callers must additionally ensure the app is not in fresh/headless mode
        or mid-first-run; those are process-level conditions the service does
        not own.
        """
        updater = self._config.updater
        if not updater.auto_check_enabled:
            return False
        # Debug override: allow auto-check in source-checkout mode.
        if not self._context.auto_update_supported and not update_debug.force_auto():
            return False
        now = int(time.time())
        if updater.last_check_ts and (now - updater.last_check_ts) < UPDATE_CHECK_INTERVAL_SEC:
            log.debug("Skipping auto update check: within back-off window")
            return False
        return True

    def is_banner_suppressed(self, version: str, now: int | None = None, *, manual: bool = False) -> bool:
        """Whether automatic banner surfacing should stay quiet for *version*."""
        if not version:
            return False
        updater = self._config.updater
        if manual:
            return False
        if self._is_reminder_frequency_suppressed(version, now=now):
            return True
        now = int(time.time()) if now is None else int(now)
        if updater.suppressed_banner_version != version:
            return False
        return not updater.suppress_banner_until_ts <= now

    def reminder_frequency(self) -> str:
        freq = (self._config.updater.reminder_frequency or "always").strip().lower()
        if freq not in {"always", "weekly", "never"}:
            return "always"
        return freq

    def set_reminder_frequency(self, frequency: str) -> None:
        self._config.updater.reminder_frequency = frequency if frequency in {"always", "weekly", "never"} else "always"
        self._save_config()

    def clear_reminder_state(self) -> None:
        updater = self._config.updater
        changed = False
        if updater.last_seen_version:
            updater.last_seen_version = ""
            changed = True
        if updater.last_seen_ts:
            updater.last_seen_ts = 0
            changed = True
        if changed:
            self._save_config()

    def _is_reminder_frequency_suppressed(self, version: str, now: int | None = None) -> bool:
        """Whether the long-term reminder policy suppresses automatic banners."""
        freq = self.reminder_frequency()
        if freq == "never":
            return True
        if freq != "weekly":
            return False
        updater = self._config.updater
        if updater.last_seen_version != version:
            return False
        now = int(time.time()) if now is None else int(now)
        return updater.last_seen_ts > 0 and (now - updater.last_seen_ts) < _AUTO_REMIND_WEEK_SEC

    def remind_later_for_week(self, version: str) -> None:
        """Suppress reminders and auto-install handoff for *version* for one week."""
        if not version:
            return
        updater = self._config.updater
        until_ts = int(time.time()) + _REMIND_LATER_WEEK_SEC
        updater.suppressed_banner_version = version
        updater.suppress_banner_until_ts = until_ts
        updater.suppressed_install_version = version
        updater.suppress_install_until_ts = until_ts
        self._save_config()
        log.info("User deferred update reminders for version %s until %s", version, until_ts)

    def clear_banner_suppression(self, version: str | None = None) -> None:
        """Remove temporary banner suppression globally or for a matching version."""
        updater = self._config.updater
        if version and updater.suppressed_banner_version and updater.suppressed_banner_version != version:
            return
        if not updater.suppressed_banner_version and not updater.suppress_banner_until_ts:
            return
        updater.suppressed_banner_version = ""
        updater.suppress_banner_until_ts = 0
        self._save_config()

    def is_install_deferred(self, version: str, now: int | None = None) -> bool:
        """Whether auto-install on quit is temporarily deferred for *version*."""
        if not version:
            return False
        updater = self._config.updater
        now = int(time.time()) if now is None else int(now)
        if updater.suppressed_install_version != version:
            return False
        return not updater.suppress_install_until_ts <= now

    def clear_install_deferral(self, version: str | None = None) -> None:
        """Remove temporary install deferral globally or for a matching version."""
        updater = self._config.updater
        if version and updater.suppressed_install_version and updater.suppressed_install_version != version:
            return
        if not updater.suppressed_install_version and not updater.suppress_install_until_ts:
            return
        updater.suppressed_install_version = ""
        updater.suppress_install_until_ts = 0
        self._save_config()

    # ── Check ─────────────────────────────────────────────────

    def check_async(self, manual: bool = False) -> None:
        """Start an asynchronous update check.

        *manual* checks bypass the rollout/skip gating so an explicit "Check
        for updates" click always surfaces a newer release.
        """
        if self.is_checking():
            log.debug("Update check already in progress; ignoring new request")
            return

        # Capture *manual* in a closure so the finished callback always sees
        # the intent of *this* check, even if a future check_async call
        # overwrites the service-level state before the worker completes.
        self._check_manual = manual
        _manual = manual
        updater = self._config.updater
        locale = api_locale(lang_manager.get_current_language())

        thread = QThread()
        worker = UpdateCheckWorker(
            context=self._context,
            channel=updater.channel or "stable",
            locale=locale,
            current_version=self._current_version,
            source_order=metadata_source_order(updater),
        )
        self._check_thread = thread
        self._check_worker = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(lambda info, src, m=_manual: self._on_check_finished(info, src, m))
        worker.failed.connect(self._on_check_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._on_check_thread_finished(t))
        thread.finished.connect(thread.deleteLater)

        self.check_started.emit()
        log.info("Update check started (manual=%s, channel=%s)", manual, updater.channel)
        thread.start()

    @Slot(object, str)
    def _on_check_finished(self, info: UpdateInfo, source: str, manual: bool | None = None) -> None:
        if manual is None:
            manual = self._check_manual
        now = int(time.time())
        updater = self._config.updater
        previous_identity = _update_identity(self._latest)
        updater.last_check_ts = now
        updater.last_good_metadata_source = source
        updater.last_good_metadata_source_ts = now
        self._latest = info
        if previous_identity != _update_identity(info):
            self._clear_downloaded_artifact()
        self._save_config()

        if not info.is_update_available:
            log.info("Update check: already up to date (latest=%s)", info.release.version)
            self.update_not_available.emit(info)
            return

        version = info.release.version
        bypass_gates = update_debug.ignore_gates()
        banner_suppressed = False
        if not manual and not bypass_gates:
            if self.is_version_skipped(version):
                log.info("Update %s available but skipped by user", version)
                self.update_not_available.emit(info)
                return
            if not self._rollout_passes(info):
                log.info("Update %s available but not yet in rollout for this device", version)
                self.update_not_available.emit(info)
                return
            banner_suppressed = self.is_banner_suppressed(version, now=now, manual=manual)

        if bypass_gates:
            log.debug("Update gates bypassed via HISTORYSYNC_UPDATE_IGNORE_GATES")

        if updater.suppressed_banner_version and updater.suppressed_banner_version != version:
            updater.suppressed_banner_version = ""
            updater.suppress_banner_until_ts = 0
        elif updater.suppressed_banner_version == version and updater.suppress_banner_until_ts <= now:
            # Same version but the suppression window has expired — clean up.
            updater.suppressed_banner_version = ""
            updater.suppress_banner_until_ts = 0
        if updater.suppressed_install_version and updater.suppressed_install_version != version:
            updater.suppressed_install_version = ""
            updater.suppress_install_until_ts = 0
        elif updater.suppressed_install_version == version and updater.suppress_install_until_ts <= now:
            # Same version but the deferral window has expired — clean up.
            updater.suppressed_install_version = ""
            updater.suppress_install_until_ts = 0
        if not manual and not banner_suppressed:
            updater.last_seen_version = version
            updater.last_seen_ts = now
        self._save_config()
        if not manual and self.should_auto_download_on_availability():
            if info.asset is None:
                log.info("Auto-install policy active but no downloadable asset is available for %s", version)
            else:
                log.info("Auto-install policy active; starting background download for %s", version)
                self.download_async(info)
        if banner_suppressed:
            log.info("Update %s available but banner surfacing is temporarily suppressed", version)
            self.update_not_available.emit(info)
            return
        log.info("Update available: %s (source=%s, asset=%s)", version, source, bool(info.asset))
        self.update_available.emit(info)

    @Slot(str)
    def _on_check_failed(self, message: str) -> None:
        log.warning("Update check failed: %s", message)
        self.check_failed.emit(message)

    @Slot(QThread)
    def _on_check_thread_finished(self, thread: QThread) -> None:
        if thread is not self._check_thread:
            return
        self._check_thread = None
        self._check_worker = None

    def _rollout_passes(self, info: UpdateInfo) -> bool:
        rollout = info.rollout
        if rollout >= 100:
            return True
        if rollout <= 0:
            return False
        uuid = self._config.device_uuid or ""
        if not uuid:
            # No stable identifier — never withhold an update we'd otherwise show.
            return True
        bucket = int(hashlib.sha256(f"{uuid}:{info.release.version}".encode()).hexdigest(), 16) % 100
        return bucket < rollout

    # ── Skip handling ─────────────────────────────────────────

    def is_version_skipped(self, version: str) -> bool:
        return bool(version) and self._config.updater.skipped_version == version

    def skip_version(self, version: str) -> None:
        self._config.updater.skipped_version = version or ""
        self.clear_banner_suppression(version or None)
        self.clear_install_deferral(version or None)
        self._save_config()
        log.info("User skipped update version %s", version)

    def clear_skip(self) -> None:
        self._config.updater.skipped_version = ""
        self._save_config()

    # ── Download ──────────────────────────────────────────────

    def download_dir(self) -> Path:
        return get_app_data_dir() / UPDATE_DOWNLOAD_DIR_NAME

    @staticmethod
    def _cleanup_stale_downloads(download_dir: Path, keep_filename: str | None = None) -> None:
        """Remove stale artifacts from the download directory.

        Keeps the file matching *keep_filename* (if provided) and any active
        ``.part`` / ``.etag`` resume files.  Best-effort — failures are logged
        but never raised.
        """
        if not download_dir.exists():
            return
        keep = {keep_filename} if keep_filename else set()
        for entry in download_dir.iterdir():
            if entry.name in keep:
                continue
            # Never remove in-progress download checkpoints.
            if entry.suffix in (".part", ".etag"):
                continue
            try:
                if entry.is_file():
                    entry.unlink()
                elif entry.is_dir():
                    # Directories are unexpected but clean them up anyway.
                    import shutil

                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                log.debug("Could not remove stale download artifact: %s", entry)

    def download_async(self, info: UpdateInfo) -> None:
        """Download (and verify) the asset for *info* in the background."""
        if self.is_downloading():
            log.debug("Update download already in progress; ignoring new request")
            return
        if self.current_policy() == UPDATE_POLICY_NOTIFY_ONLY:
            self.download_failed.emit(_("In-app download is disabled by your update preferences."))
            return
        if not self._context.can_self_update:
            self.download_failed.emit(_("This installation can only update via the release page."))
            return
        if info.asset is None:
            self.download_failed.emit(_("No downloadable package is available for your platform."))
            return

        self._download_gen += 1
        gen = self._download_gen

        token_order = download_token_order(self._config.updater, self._effective_language())
        candidates = build_download_candidates(info, token_order)
        if not candidates:
            self.download_failed.emit(_("No download source is available."))
            return

        try:
            dest_dir = self.download_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.download_failed.emit(_("Could not create the download folder: {error}").format(error=exc))
            return

        filename = info.asset.filename or self._fallback_filename(info)
        dest = dest_dir / filename
        expected_sha = info.asset.sha256 if info.asset.has_verified_sha256 else ""
        expected_size = info.asset.size_bytes or 0
        identity = _update_identity(info)

        # Reuse an already-downloaded, still-valid artifact instead of re-fetching.
        if self._artifact_is_valid(dest, expected_sha, expected_size):
            log.info("Reusing previously downloaded update artifact: %s", dest)
            self._downloaded_path = dest
            self._downloaded_identity = identity
            self._active_download_identity = identity
            # Defer signals to the next event-loop tick so callers that wired
            # download_started/download_finished synchronously (e.g. the update
            # dialog) never observe a surprise synchronous emission.  The
            # generation guard in _reuse_download_done ensures that if another
            # download_async() call starts before the timer fires, the stale
            # emission is silently dropped.
            QTimer.singleShot(0, self.download_started.emit)
            path_str = str(dest)
            QTimer.singleShot(0, lambda p=path_str, g=gen: self._reuse_download_done(p, g))
            return

        self._downloaded_path = None
        self._downloaded_identity = identity
        self._active_download_identity = identity
        thread = QThread()
        worker = UpdateDownloadWorker(
            candidates=candidates,
            dest_path=dest,
            expected_sha256=expected_sha,
            expected_size=expected_size,
        )
        self._dl_thread = thread
        self._dl_worker = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self.download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.failed.connect(self._on_download_failed)
        worker.cancelled.connect(self._on_download_cancelled)
        for sig in (worker.finished, worker.failed, worker.cancelled):
            sig.connect(thread.quit)
            sig.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._on_download_thread_finished(t))
        thread.finished.connect(thread.deleteLater)

        self.download_started.emit()
        log.info("Update download started -> %s (%d candidate source(s))", dest, len(candidates))
        thread.start()

    def cancel_download(self) -> None:
        if self._dl_worker is not None:
            log.info("Update download cancellation requested")
            self._dl_worker.cancel()

    @Slot(str, str)
    def _on_download_finished(self, path: str, token: str) -> None:
        now = int(time.time())
        updater = self._config.updater
        updater.last_good_download_source = token
        updater.last_good_download_source_ts = now
        self._save_config()
        self._downloaded_path = Path(path)
        if self._active_download_identity != ("", ""):
            self._downloaded_identity = self._active_download_identity
        self._active_download_identity = ("", "")
        # Clean up older artifacts in the download directory, keeping only the
        # freshly downloaded file.
        self._cleanup_stale_downloads(self.download_dir(), keep_filename=Path(path).name)
        log.info("Update download complete via %s: %s", token, path)
        if self.active_downloaded_path() is None:
            log.info("Downloaded artifact no longer matches the current update; suppressing ready state")
            return
        self.download_finished.emit(path)

    @Slot(str)
    def _on_download_failed(self, message: str) -> None:
        log.warning("Update download failed: %s", message)
        self._active_download_identity = ("", "")
        self._clear_downloaded_artifact()
        self.download_failed.emit(message)

    @Slot()
    def _on_download_cancelled(self) -> None:
        log.info("Update download cancelled")
        self._active_download_identity = ("", "")
        self._clear_downloaded_artifact()
        self.download_cancelled.emit()

    def _reuse_download_done(self, path: str, gen: int) -> None:
        """Complete the artifact-reuse fast path, guarded by the download generation.

        If *gen* no longer matches ``self._download_gen``, a newer call to
        :meth:`download_async` has started since the reuse was scheduled — drop
        the stale emission so it cannot overwrite the newer download's state.
        """
        if gen != self._download_gen:
            log.debug("Reuse-download-done gen=%d stale (current=%d); dropping", gen, self._download_gen)
            return
        self._active_download_identity = ("", "")
        self._cleanup_stale_downloads(self.download_dir(), keep_filename=Path(path).name)
        if self.active_downloaded_path() is None:
            log.info("Downloaded artifact no longer matches the current update; suppressing ready state")
            return
        self.download_finished.emit(path)

    @Slot(QThread)
    def _on_download_thread_finished(self, thread: QThread) -> None:
        if thread is not self._dl_thread:
            return
        self._dl_thread = None
        self._dl_worker = None

    def _artifact_is_valid(self, path: Path, expected_sha: str, expected_size: int) -> bool:
        if not path.exists():
            return False
        try:
            if expected_size and path.stat().st_size != expected_size:
                return False
            if expected_sha:
                digest = hashlib.sha256()
                with path.open("rb") as fh:
                    for block in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest().lower() != expected_sha.lower():
                    return False
            # With neither a size nor a verified checksum we cannot trust a
            # pre-existing file; force a fresh download.
            return bool(expected_sha or expected_size)
        except OSError:
            return False

    def _fallback_filename(self, info: UpdateInfo) -> str:
        """Build a filename when the API provides none, including platform/arch."""
        asset = info.asset
        if asset and asset.url_download:
            tail = asset.url_download.rsplit("/", 1)[-1].split("?", 1)[0]
            if tail:
                return tail
        ctx = self._context
        version = info.release.version or "update"
        return f"HistorySync-{version}-{ctx.platform}-{ctx.arch}"

    # ── Apply strategies ──────────────────────────────────────

    def run_installer(self, path: str) -> bool:
        """Launch a downloaded installer detached, then ask the app to quit.

        Refuses to execute if the artifact was not verified against a known
        SHA-256 checksum (e.g. GitHub fallback provides size-only validation).
        In that case the user is directed to the release page instead.
        """
        target = Path(path)
        if not target.exists():
            self.apply_failed.emit(_("The downloaded installer could not be found."))
            return False

        # Security gate: never auto-execute an artifact whose integrity was
        # validated by size alone (no SHA-256).  This protects the GitHub
        # fallback path where checksums are unavailable.
        info = self._latest
        if info is not None and info.asset is not None and not info.asset.has_verified_sha256:
            log.warning("Refusing to run installer without verified SHA-256; opening release page instead")
            self.apply_failed.emit(
                _(
                    "Cannot auto-install: the download source did not provide a verified checksum. "
                    "Please install manually from the release page."
                )
            )
            self.open_release_page(info)
            return False

        try:
            if self._context.platform == PLATFORM_WINDOWS:
                creationflags = 0
                for flag in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
                    creationflags |= getattr(subprocess, flag, 0)
                subprocess.Popen([str(target)], close_fds=True, creationflags=creationflags)
            else:
                subprocess.Popen([str(target)], close_fds=True, start_new_session=True)
        except Exception as exc:
            log.error("Failed to launch installer %s: %s", target, exc)
            self.apply_failed.emit(_("Could not launch the installer: {error}").format(error=exc))
            return False
        log.info("Installer launched (%s); the caller will request quit", target)
        return True

    def open_artifact(self, path: str) -> bool:
        """Hand a downloaded artifact to the OS (e.g. open a .dmg)."""
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))

    def reveal_artifact(self, path: str) -> None:
        """Reveal the downloaded file in the platform file manager."""
        target = Path(path)
        try:
            if self._context.platform == PLATFORM_WINDOWS:
                subprocess.Popen(["explorer", "/select,", str(target)], close_fds=True)
                return
            if self._context.platform == PLATFORM_MACOS:
                subprocess.Popen(["open", "-R", str(target)], close_fds=True)
                return
            subprocess.Popen(["xdg-open", str(target.parent)], close_fds=True)
        except Exception as exc:
            log.warning("Could not reveal %s in file manager: %s", target, exc)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def open_release_page(self, info: UpdateInfo | None = None) -> None:
        url = ""
        if info is not None:
            url = info.release.notes_url
        QDesktopServices.openUrl(QUrl(url or UPDATE_RELEASES_PAGE))

    def open_browser_download(self, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def prepare_update_for_quit(self) -> bool:
        """Apply the downloaded update if policy requires it during orderly quit.

        Returns True when the quit flow should continue immediately, or False
        when an installer handoff was started and the caller should stop doing
        further shutdown work in this invocation.
        """
        if not self.should_apply_on_quit():
            return True

        info = self.pending_update() or self._latest
        path = self._downloaded_path_for_info(info)
        if path is None:
            return True

        strategy = self._context.apply_strategy
        log.info("Auto-install on quit: applying update via %s from %s", strategy, path)
        if strategy == "run_installer":
            if self.run_installer(str(path)):
                # Defer quit_requested to the next event-loop iteration so the
                # caller (_quit in main.py) can finish its bookkeeping (set
                # _already_ran, unwind the stack) before the signal re-enters.
                QTimer.singleShot(0, self.quit_requested.emit)
                return False
            return True
        if strategy == "open_file":
            opened = self.open_artifact(str(path))
            if not opened:
                self.apply_failed.emit(_("Could not open the downloaded update package."))
            return True
        if strategy == "reveal":
            self.reveal_artifact(str(path))
            return True
        self.open_release_page(self._latest)
        return True

    # ── Lifecycle ─────────────────────────────────────────────

    def shutdown(self, timeout_ms: int = 4000) -> None:
        """Cancel any in-flight download/check and wait briefly for worker threads.

        On Windows session-end the process has limited time before the OS
        kills it; this method makes a best-effort attempt to let worker
        threads finish cleanly but will not block the process exit.
        """
        if self._dl_worker is not None:
            self._dl_worker.cancel()
        if self._check_worker is not None:
            self._check_worker.cancel()
        for thread in (self._dl_thread, self._check_thread):
            if thread is not None and thread.isRunning():
                if not thread.wait(timeout_ms):
                    log.warning("Update worker thread did not finish in %d ms; forcing quit", timeout_ms)
                    thread.quit()
                    if not thread.wait(1000):
                        log.warning("Update worker thread still alive after quit(); abandoning")
                # Help the GC by dropping references early.
                if thread is self._dl_thread:
                    self._dl_thread = None
                    self._dl_worker = None
                elif thread is self._check_thread:
                    self._check_thread = None
                    self._check_worker = None

    # ── Internals ─────────────────────────────────────────────

    def _effective_language(self) -> str:
        return self._config.language or lang_manager.get_current_language() or "en_US"

    def _save_config(self) -> None:
        try:
            self._config.save()
        except Exception as exc:
            log.warning("Failed to persist updater state: %s", exc)
            self.config_save_failed.emit(str(exc))

    def _downloaded_path_for_info(self, info: UpdateInfo | None) -> Path | None:
        if self._downloaded_path is None or not self._downloaded_path.exists():
            return None
        if _update_identity(info) != self._downloaded_identity:
            return None
        return self._downloaded_path

    def _clear_downloaded_artifact(self) -> None:
        self._downloaded_path = None
        self._downloaded_identity = ("", "")


def is_update_subsystem_active(config: AppConfig) -> bool:
    """Whether the GUI should wire up the update subsystem at all.

    Disabled in fresh/mock mode (no disk) — there is no point checking for an
    update for a throwaway session.  Source-checkout mode still constructs the
    service (so manual checks work) but :meth:`UpdateService.should_auto_check`
    keeps it quiet.
    """
    if getattr(config, "_fresh", False):
        return False
    # Mock mode generates synthetic data for stress testing; updates are
    # irrelevant and would waste quota / cause noise.
    return not getattr(config, "_mock", False)
