# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from src.models.history_record import HistoryRecord
from src.services.browser_defs import BrowserDef
from src.utils.logger import get_logger

log = get_logger("extractor")

_BACKUP_TIMEOUT_SEC = 10


# ── 模块级工具（供历史 & 图标两侧共用）─────────────────────


def copy_db_with_wal(src: Path, dst: Path) -> None:
    """
    文件级拷贝 SQLite 数据库（含 WAL / SHM 三件套）。

    拷贝顺序：先 WAL/SHM，后主文件。
    先拷 WAL 可使副本的 "主文件 + WAL" 在时间轴上更接近一致点，
    减小不一致窗口。WAL / SHM 文件可能不存在，缺失时跳过。
    """
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(str(side), str(dst.with_name(dst.name + suffix)))
    shutil.copy2(str(src), str(dst))


def _close_quietly(conn: sqlite3.Connection | None) -> None:
    """静默关闭 SQLite 连接，忽略所有异常。"""
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def open_db_snapshot(db_path: Path, display_name: str = "", timeout_sec: float = _BACKUP_TIMEOUT_SEC):
    """
    上下文管理器：将 SQLite 数据库备份到内存快照并 yield 连接。
    退出时无论是否异常都会关闭连接。

    优先使用 SQLite backup() API（完整处理 WAL，无文件竞态）；
    backup() 失败时自动降级为文件拷贝方案。

    用法：
        with open_db_snapshot(db_path, display_name) as conn:
            rows = conn.execute(sql).fetchall()
    """
    conn = _open_snapshot(db_path, display_name, timeout_sec)
    if conn is None:
        raise RuntimeError(f"[{display_name}] Cannot open snapshot of {db_path}")
    try:
        yield conn
    finally:
        _close_quietly(conn)


def _open_snapshot(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
) -> sqlite3.Connection | None:
    """尝试 backup() → 降级文件拷贝，返回内存连接或 None。"""
    conn = _try_backup(db_path, display_name, timeout_sec)
    if conn is not None:
        return conn
    return _try_file_copy(db_path, display_name, timeout_sec)


def _try_backup(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
) -> sqlite3.Connection | None:
    """尝试 SQLite backup() API，超时或失败返回 None。"""
    src_conn = mem_conn = None
    _start = time.monotonic()
    _last_log = [_start]

    def _progress(status: int, remaining: int, total: int) -> None:
        now = time.monotonic()
        if now - _last_log[0] >= 2.0:
            log.debug(
                "[%s] backup() progress: remaining=%d total=%d elapsed=%.1fs",
                display_name,
                remaining,
                total,
                now - _start,
            )
            _last_log[0] = now
        if now - _start > timeout_sec:
            raise sqlite3.OperationalError(
                f"backup() timed out after {timeout_sec}s (browser may be holding a write lock)"
            )

    try:
        src_conn = sqlite3.connect(str(db_path), timeout=0)
        src_conn.execute("SELECT 1")
        mem_conn = sqlite3.connect(":memory:")
        src_conn.backup(mem_conn, pages=100, progress=_progress)
        mem_conn.row_factory = sqlite3.Row
        log.debug("[%s] backup() OK in %.2fs", display_name, time.monotonic() - _start)
        return mem_conn
    except sqlite3.Error as exc:
        log.warning(
            "[%s] backup() failed for '%s' (%.2fs): %s — will try file copy",
            display_name,
            db_path.name,
            time.monotonic() - _start,
            exc,
        )
        _close_quietly(src_conn)
        _close_quietly(mem_conn)
        return None
    finally:
        _close_quietly(src_conn)


def _try_file_copy(
    db_path: Path,
    display_name: str,
    timeout_sec: float,
    retry: int = 3,
    delay: float = 0.5,
) -> sqlite3.Connection | None:
    _start = time.monotonic()

    def _progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() - _start > timeout_sec:
            raise sqlite3.OperationalError(f"[{display_name}] file-copy backup() timed out")

    for attempt in range(1, retry + 1):
        file_conn = mem_conn = None
        try:
            with tempfile.TemporaryDirectory(prefix="historysync_") as tmp_dir:
                dst = Path(tmp_dir) / db_path.name
                copy_db_with_wal(db_path, dst)
                file_conn = sqlite3.connect(f"file:{dst}?immutable=1", uri=True)
                file_conn.execute("PRAGMA query_only = ON")
                mem_conn = sqlite3.connect(":memory:")
                file_conn.backup(mem_conn, pages=200, progress=_progress)
                mem_conn.row_factory = sqlite3.Row
                _close_quietly(file_conn)
                log.debug("[%s] file-copy OK (attempt %d)", display_name, attempt)
                return mem_conn
        except OSError as exc:
            _close_quietly(mem_conn)
            if attempt < retry:
                log.debug("[%s] file copy attempt %d blocked: %s — retrying", display_name, attempt, exc)
                time.sleep(delay)
            else:
                log.warning("[%s] file copy failed after %d attempts: %s", display_name, retry, exc)
                return None
        except Exception as exc:
            _close_quietly(mem_conn)
            log.warning("[%s] file-copy backup() failed: %s", display_name, exc)
            return None
        finally:
            _close_quietly(file_conn)

    return None


# ── BaseExtractor ─────────────────────────────────────────────


class BaseExtractor(ABC):
    def __init__(self, defn: BrowserDef, custom_db_path: Path | None = None):
        """
        Args:
            defn:           浏览器定义，提供路径策略与元数据。
            custom_db_path: 用户手动指定的单一数据库路径（仅自定义 Chromium 使用）。
        """
        self._defn = defn
        self._custom_db_path = custom_db_path

    @property
    def browser_type(self) -> str:
        return self._defn.browser_type

    @property
    def display_name(self) -> str:
        return self._defn.display_name

    # ── 公开接口 ──────────────────────────────────────────────

    def extract(self, since_map: dict[str, int] | None = None) -> list[HistoryRecord]:
        """
        公开入口：发现所有 Profile 数据库，安全拷贝后提取。

        Args:
            since_map: {profile_name: last_known_unix_timestamp}
                       只提取 visit_time > timestamp 的新记录；
                       None 或未命中的 profile 视为 0（全量提取）。
        """
        all_records: list[HistoryRecord] = []
        since_map = since_map or {}

        for profile_name, db_path in self.get_all_db_paths():
            if not db_path.exists():
                continue
            since = since_map.get(profile_name, 0)
            log.info(
                "[%s] Extracting profile '%s' from %s (since=%d)",
                self.display_name,
                profile_name,
                db_path,
                since,
            )
            try:
                records = self._safe_extract(profile_name, db_path, since)
                all_records.extend(records)
                log.info(
                    "[%s] '%s' → %d records (incremental=%s)",
                    self.display_name,
                    profile_name,
                    len(records),
                    since > 0,
                )
            except Exception as exc:
                log.warning(
                    "[%s] Failed to extract '%s': %s",
                    self.display_name,
                    profile_name,
                    exc,
                )

        return all_records

    def is_available(self) -> bool:
        """检测该浏览器在当前系统是否有可用的历史数据库文件。"""
        return self._defn.is_history_available(self._custom_db_path)

    def get_all_db_paths(self) -> list[tuple[str, Path]]:
        """
        返回所有 Profile 的历史数据库路径列表。
        供 BrowserMonitor 监控文件修改时间使用。
        """
        return list(self._defn.iter_history_db_paths(self._custom_db_path))

    # ── 子类实现 ──────────────────────────────────────────────

    @abstractmethod
    def _extract_from_db(
        self,
        conn: sqlite3.Connection,
        profile_name: str,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        """
        从已打开的 SQLite 内存快照中提取记录。

        Args:
            conn:            指向内存快照数据库的连接（只读）。
            profile_name:    Profile 名称，用于填充 HistoryRecord。
            since_unix_time: 仅返回 visit_time > 此值的记录（0 = 全量）。
        """

    # ── 内部实现 ──────────────────────────────────────────────

    def _safe_extract(
        self,
        profile_name: str,
        db_path: Path,
        since_unix_time: int = 0,
    ) -> list[HistoryRecord]:
        """
        将数据库备份到内存快照，再调用 _extract_from_db()。
        连接生命周期完全内聚于此方法，调用方无需关心连接管理。
        """
        try:
            with open_db_snapshot(db_path, self.display_name) as conn:
                return self._extract_from_db(conn, profile_name, since_unix_time)
        except RuntimeError as exc:
            log.warning("[%s] Cannot open snapshot for '%s': %s", self.display_name, profile_name, exc)
            return []
