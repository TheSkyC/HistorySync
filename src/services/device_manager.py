# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import platform
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from src.models.app_config import AppConfig
    from src.services.local_db import LocalDatabase

from src.utils.constants import APP_VERSION
from src.utils.logger import get_logger

log = get_logger("device_manager")


def ensure_local_device(config: AppConfig, db: LocalDatabase) -> int:
    """Ensure the local device is registered in the DB.

    Generates a UUID on first call (stored in config), then upserts the
    device row with current platform/version metadata.

    Returns the ``devices.id`` integer for this machine.
    """
    newly_generated = False

    if not config.device_uuid:
        config.device_uuid = str(uuid.uuid4())
        newly_generated = True
        log.info("Generated new device UUID: %s", config.device_uuid)

    if not config.device_name:
        config.device_name = platform.node() or "Unknown Device"
        newly_generated = True

    device_id = db.upsert_device(
        uuid=config.device_uuid,
        name=config.device_name,
        plat=platform.system(),
        app_version=APP_VERSION,
    )

    if newly_generated:
        try:
            config.save()
        except Exception as exc:
            log.warning("Failed to persist new device UUID: %s", exc)

    log.debug("Local device id=%d uuid=%s name=%r", device_id, config.device_uuid, config.device_name)
    return device_id


def update_device_name(config: AppConfig, db: LocalDatabase, new_name: str) -> int:
    """Rename the local device both in config and in the DB. Returns device_id."""
    config.device_name = new_name
    device_id = db.upsert_device(
        uuid=config.device_uuid,
        name=new_name,
        plat=platform.system(),
        app_version=APP_VERSION,
    )
    try:
        config.save()
    except Exception as exc:
        log.warning("Failed to save device name update: %s", exc)
    return device_id


def adopt_device(config: AppConfig, db: LocalDatabase, target_uuid: str) -> int:
    """Switch this machine's identity to an existing device UUID in the DB.

    After adoption the caller should re-run ``ensure_local_device`` to get
    the correct device_id for the new identity.
    """
    config.device_uuid = target_uuid
    dev = db.get_device_by_uuid(target_uuid)
    if dev:
        config.device_name = dev["name"]
    device_id = db.upsert_device(
        uuid=target_uuid,
        name=config.device_name,
        plat=platform.system(),
        app_version=APP_VERSION,
    )
    try:
        config.save()
    except Exception as exc:
        log.warning("Failed to save adopted device UUID: %s", exc)
    log.info("Adopted device uuid=%s id=%d", target_uuid, device_id)
    return device_id
