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

    # 文件 Handler：最大 5MB，保留 3 个滚动文件
    fh = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    fh.setFormatter(fmt)

    # 控制台 Handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    _logger.setLevel(level)
    _logger.addHandler(fh)
    _logger.addHandler(sh)

    return _logger


def get_logger(name: str = "") -> logging.Logger:
    """获取子 logger"""
    if name:
        return logging.getLogger(f"{APP_NAME}.{name}")
    return _logger
