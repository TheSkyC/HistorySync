# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from src.utils.constants import APP_NAME, LOG_BACKUP_COUNT, LOG_FILENAME, LOG_MAX_BYTES

_state = {"initialized": False}
_logger = logging.getLogger(APP_NAME)


def setup_logger(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    if _state["initialized"]:
        return _logger

    _state["initialized"] = True
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILENAME

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler: max 5MB, keep 3 rotating backup files
    fh = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    fh.setFormatter(fmt)

    # Console handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    _logger.setLevel(level)
    _logger.addHandler(fh)
    _logger.addHandler(sh)

    return _logger


def get_logger(name: str = "") -> logging.Logger:
    """Get a child logger."""
    if name:
        return logging.getLogger(f"{APP_NAME}.{name}")
    return _logger
