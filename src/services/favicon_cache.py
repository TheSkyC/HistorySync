# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
import time

from src.utils.logger import get_logger

log = get_logger("favicon_cache")

# 缓存有效期：30 天后认为过期，下次同步时重新从浏览器数据库提取
_TTL_DAYS = 30


@dataclass
class FaviconRecord:
    """单条归一化图标缓存记录。"""

    domain: str
    data: bytes  # PNG/ICO/WebP/GIF 的二进制数据，或 SVG 的 UTF-8 字节
    data_type: str  # 'png' | 'ico' | 'svg' | 'webp' | 'jpeg' | 'gif'
    width: int  # SVG 统一为 0（矢量，无固定尺寸）
    updated_at: int  # Unix 时间戳（秒）


class FaviconCache:
    """
    管理 favicons.db 独立 SQLite 数据库。

    职责边界：
    - 只负责图标数据的持久化存取，不做任何渲染。
    - 完全独立于 history.db，永远不参与 WebDAV 同步。
    - 以 domain（注册域名）为主键，缓存对应的最优图标。

    性能优化：
    - 使用持久化连接（check_same_thread=False），避免每次 get/get_many
      调用都重新 open/close 连接，大幅降低 UI 线程在图标渲染时的延迟。
    - 写操作（upsert_many、prune_stale）显式 commit；
      读操作（get、get_many）不触发多余的 commit。
    - 所有操作均通过 RLock 序列化，保证主线程读 + 后台线程写的安全性。
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS favicon_cache (
            domain      TEXT    PRIMARY KEY,
            data        BLOB    NOT NULL,
            data_type   TEXT    NOT NULL DEFAULT 'png',
            width       INTEGER NOT NULL DEFAULT 0,
            updated_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_favicon_updated
            ON favicon_cache(updated_at);
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._pconn: sqlite3.Connection | None = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── 持久化连接管理 ────────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        """
        返回持久化连接，不存在时创建。
        调用方必须已持有 self._lock。
        """
        if self._pconn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.commit()
            self._pconn = conn
        return self._pconn

    def _reset_conn(self) -> None:
        """连接出错后重置，下次 _ensure_conn 会重新打开。"""
        if self._pconn is not None:
            try:
                self._pconn.close()
            except Exception:
                pass
            self._pconn = None

    @contextmanager
    def _conn(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        """
        线程安全的连接上下文管理器。
        write=True：yield 后 commit，出错则 rollback。
        write=False（只读）：不触发任何事务操作，减少锁竞争。
        """
        with self._lock:
            conn = self._ensure_conn()
            try:
                yield conn
                if write:
                    conn.commit()
            except Exception:
                if write:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                # 连接状态可能已损坏，重置以便下次重建
                self._reset_conn()
                raise

    def close(self) -> None:
        """显式关闭持久化连接（应用退出时调用）。"""
        with self._lock:
            self._reset_conn()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        with self._conn(write=True) as conn:
            conn.executescript(self._SCHEMA)
        log.info("FaviconCache initialized: %s", self.db_path)

    # ── Write ────────────────────────────────────────────────

    def upsert_many(self, records: list[FaviconRecord]) -> int:
        """
        批量写入图标记录。冲突时（同一 domain）按以下优先级覆盖：
        - SVG 始终优先（矢量可无损缩放）
        - 同为位图时，较大尺寸覆盖较小尺寸
        - 两者尺寸相同时，更新时间较新的获胜
        Python 层的 _select_best_per_domain() 已在入库前完成同批次去重，
        此处 SQL 条件仅防御已有缓存被低质量数据降级。
        """
        if not records:
            return 0

        sql = """
            INSERT INTO favicon_cache (domain, data, data_type, width, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                data       = excluded.data,
                data_type  = excluded.data_type,
                width      = excluded.width,
                updated_at = excluded.updated_at
            WHERE
                -- 新数据是 SVG，旧数据不是 → 升级
                (excluded.data_type = 'svg' AND favicon_cache.data_type != 'svg')
                -- 新旧都是位图，新的分辨率更高 → 升级
                OR (excluded.data_type != 'svg' AND favicon_cache.data_type != 'svg'
                    AND excluded.width > favicon_cache.width)
                -- 同尺寸但数据更新（重新提取的新鲜度更高）
                OR (excluded.width = favicon_cache.width
                    AND excluded.updated_at > favicon_cache.updated_at)
        """
        with self._conn(write=True) as conn:
            conn.executemany(
                sql,
                [(r.domain, r.data, r.data_type, r.width, r.updated_at) for r in records],
            )
        log.info("FaviconCache: upserted %d domain icons", len(records))
        return len(records)

    # ── Read ─────────────────────────────────────────────────

    def get(self, domain: str) -> FaviconRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT domain, data, data_type, width, updated_at FROM favicon_cache WHERE domain = ?",
                (domain,),
            ).fetchone()
        if row is None:
            return None
        return FaviconRecord(
            domain=row["domain"],
            data=bytes(row["data"]),
            data_type=row["data_type"],
            width=row["width"],
            updated_at=row["updated_at"],
        )

    def get_many(self, domains: set[str]) -> dict[str, FaviconRecord]:
        """批量查询，返回 {domain: FaviconRecord} 字典（仅命中的条目）。"""
        if not domains:
            return {}
        placeholders = ",".join("?" * len(domains))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT domain, data, data_type, width, updated_at "
                f"FROM favicon_cache WHERE domain IN ({placeholders})",
                tuple(domains),
            ).fetchall()
        return {
            row["domain"]: FaviconRecord(
                domain=row["domain"],
                data=bytes(row["data"]),
                data_type=row["data_type"],
                width=row["width"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }

    def get_stale_domains(self) -> list[str]:
        """返回超过 TTL、需要重新提取的 domain 列表。"""
        threshold = int(time.time()) - _TTL_DAYS * 86_400
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT domain FROM favicon_cache WHERE updated_at < ?",
                (threshold,),
            ).fetchall()
        return [r["domain"] for r in rows]

    def prune_stale(self) -> int:
        """删除超过 TTL 的缓存条目，返回删除数量。"""
        threshold = int(time.time()) - _TTL_DAYS * 86_400
        with self._conn(write=True) as conn:
            cursor = conn.execute(
                "DELETE FROM favicon_cache WHERE updated_at < ?",
                (threshold,),
            )
            count = cursor.rowcount
        if count:
            log.info("FaviconCache: pruned %d stale entries", count)
        return count

    def get_total_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM favicon_cache").fetchone()
            return row[0] if row else 0
