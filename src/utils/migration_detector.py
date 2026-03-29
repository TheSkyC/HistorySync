# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3


def _default_config_dir() -> Path:
    from src.utils.path_helper import _default_config_dir as _dc

    return _dc()


def _default_data_dir() -> Path:
    from src.utils.path_helper import _default_data_dir as _dd

    return _dd()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LegacyDetectionResult:
    """Describes what legacy data was found (or not found)."""

    found: bool
    # Populated only when found=True
    config_dir: Path | None = None
    data_dir: Path | None = None
    config_file: Path | None = None
    db_file: Path | None = None
    favicon_db: Path | None = None
    secret_key: Path | None = None
    db_record_count: int = 0
    db_size_bytes: int = 0
    favicon_count: int = 0
    webdav_enabled: bool = False
    raw_config: dict = field(default_factory=dict)
    # Error conditions
    parse_error: bool = False
    # Set to True when the result was synthesised by build_force_migrate_result()
    # for developer / QA testing of the migration pipeline.
    is_force_mode: bool = False


# ---------------------------------------------------------------------------
# Internal probers
# ---------------------------------------------------------------------------


def _probe_db(db_path: Path) -> tuple[int, int]:
    """Return (record_count, favicon_count) from a SQLite database.

    Both values default to 0 on any error.  favicon_count is only non-zero
    when the database looks like a favicons.db.
    """
    record_count = 0
    favicon_count = 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            # Check if this is a history db
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='history'")
            if cur.fetchone():
                row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
                record_count = row[0] if row else 0

            # Check if this is a favicon db (table is 'favicon_cache', not 'favicons')
            cur2 = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favicon_cache'")
            if cur2.fetchone():
                row2 = conn.execute("SELECT COUNT(*) FROM favicon_cache").fetchone()
                favicon_count = row2[0] if row2 else 0
        finally:
            conn.close()
    except Exception:
        pass
    return record_count, favicon_count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_legacy_installation() -> LegacyDetectionResult:
    """Scan the default paths for a legacy 1.0.x installation.

    This function is intentionally side-effect-free: it reads files but never
    writes them.  It also never imports heavy application modules so it is safe
    to call before Qt is initialised.

    Returns a :class:`LegacyDetectionResult`.  ``result.found`` is ``True``
    only when a legacy installation is positively identified.
    """
    from src.utils.constants import (
        CONFIG_FILENAME,
        DB_FILENAME,
        FAVICON_DB_FILENAME,
        SECRET_FILENAME,
    )
    from src.utils.path_helper import get_app_data_dir, get_config_dir

    # Use runtime-overridden paths if set (e.g. --portable / --config-dir),
    # otherwise fall back to platform defaults.
    config_dir = get_config_dir()
    data_dir = get_app_data_dir()

    config_file = config_dir / CONFIG_FILENAME
    db_file = data_dir / DB_FILENAME
    favicon_db = config_dir / FAVICON_DB_FILENAME
    secret_key = config_dir / SECRET_FILENAME

    # 1. No config.json → fresh installation, nothing to migrate.
    if not config_file.exists():
        return LegacyDetectionResult(found=False)

    # 2. Parse config.json (raw JSON, no AppConfig.load() to avoid side effects).
    try:
        raw = json.loads(config_file.read_text("utf-8"))
    except Exception:
        return LegacyDetectionResult(found=False, parse_error=True)

    # 3. New-format config already has first_run_completed=True → not legacy.
    if raw.get("first_run_completed") is True:
        return LegacyDetectionResult(found=False)

    # 4. Config exists but lacks first_run_completed → 1.0.x legacy data.
    #    Gather stats about what we found.
    db_record_count = 0
    db_size_bytes = 0
    favicon_count = 0

    if db_file.exists():
        db_size_bytes = db_file.stat().st_size
        rec, _ = _probe_db(db_file)
        db_record_count = rec

    if favicon_db.exists():
        _, fav = _probe_db(favicon_db)
        favicon_count = fav

    return LegacyDetectionResult(
        found=True,
        config_dir=config_dir,
        data_dir=data_dir,
        config_file=config_file,
        db_file=db_file if db_file.exists() else None,
        favicon_db=favicon_db if favicon_db.exists() else None,
        secret_key=secret_key if secret_key.exists() else None,
        db_record_count=db_record_count,
        db_size_bytes=db_size_bytes,
        favicon_count=favicon_count,
        webdav_enabled=bool(raw.get("webdav", {}).get("enabled")),
        raw_config=raw,
    )


# ---------------------------------------------------------------------------
# Force-migrate helper (for testing / QA)
# ---------------------------------------------------------------------------


def build_force_migrate_result() -> LegacyDetectionResult:
    """Synthesise a :class:`LegacyDetectionResult` that points at the *current*
    installation, so the real migration pipeline can be exercised even when no
    legacy data exists.

    This is intentionally **not** called during normal startup — it is only
    invoked when the user explicitly clicks "Force Migrate Current Data…" in
    Settings → Maintenance.

    The resulting object is structurally identical to a genuine legacy-detection
    result, except:
    * ``found`` is forced to ``True``
    * ``is_force_mode`` is set to ``True`` so the wizard can display an
      appropriate warning banner instead of the normal "legacy data found" copy.
    """
    from src.utils.constants import (
        CONFIG_FILENAME,
        DB_FILENAME,
        FAVICON_DB_FILENAME,
        SECRET_FILENAME,
    )
    from src.utils.path_helper import get_app_data_dir, get_config_dir

    config_dir = get_config_dir()
    data_dir = get_app_data_dir()

    config_file = config_dir / CONFIG_FILENAME
    db_file = data_dir / DB_FILENAME
    favicon_db = config_dir / FAVICON_DB_FILENAME
    secret_key = config_dir / SECRET_FILENAME

    # Read config raw so migration_service can re-merge it (idempotent).
    raw: dict = {}
    if config_file.exists():
        try:
            raw = json.loads(config_file.read_text("utf-8"))
        except Exception:
            pass

    db_record_count = 0
    db_size_bytes = 0
    favicon_count = 0

    if db_file.exists():
        db_size_bytes = db_file.stat().st_size
        rec, _ = _probe_db(db_file)
        db_record_count = rec

    if favicon_db.exists():
        _, fav = _probe_db(favicon_db)
        favicon_count = fav

    return LegacyDetectionResult(
        found=True,
        is_force_mode=True,
        config_dir=config_dir,
        data_dir=data_dir,
        config_file=config_file if config_file.exists() else None,
        db_file=db_file if db_file.exists() else None,
        favicon_db=favicon_db if favicon_db.exists() else None,
        secret_key=secret_key if secret_key.exists() else None,
        db_record_count=db_record_count,
        db_size_bytes=db_size_bytes,
        favicon_count=favicon_count,
        webdav_enabled=bool(raw.get("webdav", {}).get("enabled")),
        raw_config=raw,
    )
