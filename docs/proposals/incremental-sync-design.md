# HistorySync 增量同步系统设计文档

**版本**: 1.0.0-draft  
**状态**: 设计评审中  
**作者**: TheSkyC  
**日期**: 2026-05-25  
**关联版本**: HistorySync v1.3 → v2.0 迁移路径

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [设计目标与非目标](#2-设计目标与非目标)
3. [现有架构盘点](#3-现有架构盘点)
4. [核心设计决策](#4-核心设计决策)
5. [数据模型变更](#5-数据模型变更)
6. [Bundle 文件格式规范](#6-bundle-文件格式规范)
7. [事件类型系统](#7-事件类型系统)
8. [冲突解决与 CRDT 语义](#8-冲突解决与-crdt-语义)
9. [加密架构升级 (Security Architecture V3)](#9-加密架构升级-security-architecture-v3)
10. [SyncBackend 抽象接口](#10-syncbackend-抽象接口)
11. [WebDAV Backend 实现](#11-webdav-backend-实现)
12. [私有服务器 Backend 实现](#12-私有服务器-backend-实现)
13. [BundleBuilder 与 BundleApplier](#13-bundlebuilder-与-bundleapplier)
14. [Scheduler 集成](#14-scheduler-集成)
15. [CLI 新增子命令](#15-cli-新增子命令)
16. [多设备同步全流程](#16-多设备同步全流程)
17. [Snapshot 折叠机制](#17-snapshot-折叠机制)
18. [威胁模型与安全分析](#18-威胁模型与安全分析)
19. [性能估算](#19-性能估算)
20. [迁移路径（4 阶段）](#20-迁移路径4-阶段)
21. [风险与应对](#21-风险与应对)
22. [开放问题](#22-开放问题)

---


## 1. 背景与动机

### 1.1 现有备份机制的痛点

当前 HistorySync 的 WebDAV 备份是**全量快照模型**：每次备份都将整个 `history.db`（剥离 FTS 后）打包成 ZIP 上传，文件命名为 `history_<unix_ts>.zip`。

这一设计在单设备场景下运作良好，但存在以下根本性限制：

| 问题 | 具体表现 |
|---|---|
| **传输量巨大** | 50 万条记录的库压缩后约 80–120 MB；每次备份上传全量，即使只新增了 100 条 |
| **无实时性** | 最小间隔受 `auto_backup_interval_hours` 控制，默认 48h；无法做到分钟级同步 |
| **多设备合并粗糙** | 还原只能"整体替换"或"整库 merge"，无法精确追踪单条记录的跨设备变更历史 |
| **并发冲突** | 两台设备同秒上传时文件名碰撞（`history_<ts>.zip` 时间戳相同）；后上传者覆盖前者 |
| **数据库明文** | ZIP 内容仅依赖 HTTPS 传输加密；WebDAV 服务端管理员可读取历史数据 |
| **无 unhide 传播** | `unhide_records_by_ids` 不写 tombstone，取消隐藏不能跨设备同步 |

### 1.2 用户需求

- **实时同步**：在一台设备上访问网页后，几秒到一分钟内另一台设备可见
- **增量传输**：每次只传"变化量"，不管库多大，日常同步流量 < 100 KB
- **多设备合并**：3 台设备同时使用，书签、隐藏记录、笔记全部自动合并，无需手动还原
- **私有服务器**：未来付费功能，自托管或 HistorySync Cloud，必须端到端加密
- **插件扩展**：社区可以实现新的存储后端（S3、Dropbox、Nextcloud 等），不改动核心逻辑

---

## 2. 设计目标与非目标

### 2.1 目标

- ✅ **增量同步**：每次只传新增/变更的数据，Bundle 大小目标 < 1 MB
- ✅ **最终一致性**：多设备无论以任何顺序同步，最终状态相同
- ✅ **端到端加密**：私有服务器强制 E2EE；WebDAV 默认启用，可关闭以兼容老客户端
- ✅ **向后兼容**：旧版全量 ZIP 备份继续工作；老版客户端可正常还原
- ✅ **插件化后端**：`SyncBackend` 抽象接口，5 个方法即可接入新存储
- ✅ **WebDAV 与私服统一格式**：同一个 `.hsb` Bundle 格式，差异仅在传输层
- ✅ **书签/隐藏/笔记增量同步**：所有用户数据类型均有对应事件类型
- ✅ **正确的删除语义**：tombstone + 复活规则，防止删除永久胜出

### 2.2 非目标

- ❌ **实时协作编辑**：不是 Google Docs，无需 OT/CRDT 字符级合并
- ❌ **服务端历史检索**：服务端只存 blob，不解析内容，不提供搜索 API
- ❌ **跨用户共享**：仅限同一用户的多台设备
- ❌ **大文件附件同步**：只同步文本数据，不同步 favicon 数据库（太大）
- ❌ **实时冲突 UI**：不弹出"冲突解决对话框"，所有冲突自动处理

---

## 3. 现有架构盘点

### 3.1 数据库 Schema（关键部分）

```sql
-- 历史记录主表
-- 逻辑主键（唯一约束）= (browser_type, url, visit_time)
-- 自增 id 仅本地有效，不可用于跨设备引用
CREATE TABLE history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    url              TEXT    NOT NULL,
    title            TEXT    NOT NULL DEFAULT '',
    visit_time       INTEGER NOT NULL,     -- Unix 秒，访问时间
    visit_count      INTEGER NOT NULL DEFAULT 1,
    browser_type     TEXT    NOT NULL,
    profile_name     TEXT    NOT NULL DEFAULT '',
    metadata         TEXT    NOT NULL DEFAULT '',
    domain_id        INTEGER REFERENCES domains(id),
    created_at       INTEGER NOT NULL DEFAULT (strftime('%s','now')),  -- 行入库时间
    typed_count      INTEGER,
    first_visit_time INTEGER,
    transition_type  INTEGER,
    visit_duration   REAL,
    device_id        INTEGER REFERENCES devices(id)
);
CREATE UNIQUE INDEX idx_history_dedup ON history(browser_type, url, visit_time);

-- 删除 tombstone 表（已存在，增量同步直接复用）
CREATE TABLE deleted_records    (url TEXT NOT NULL PRIMARY KEY, deleted_at INTEGER NOT NULL);
CREATE TABLE deleted_bookmarks  (url TEXT NOT NULL PRIMARY KEY, deleted_at INTEGER NOT NULL);
CREATE TABLE deleted_annotations(url TEXT NOT NULL PRIMARY KEY, deleted_at INTEGER NOT NULL);

-- 设备注册表（已存在）
CREATE TABLE devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    platform     TEXT,
    app_version  TEXT,
    last_sync_at INTEGER,
    created_at   INTEGER DEFAULT (strftime('%s','now'))
);
```

### 3.2 现有合并语义（已证明正确，增量同步完整保留）

| 数据类 | 冲突规则 | 代码位置 |
|---|---|---|
| history 字段 | `MAX(visit_count)`, `COALESCE(title 非空优先)` | `history.py` ON CONFLICT DO UPDATE |
| history tombstone | `MAX(deleted_at)` | `merge.py:195` |
| bookmark 主体 | `bookmarked_at` LWW | `merge.py:260` |
| bookmark_tags | 整体替换（LWW by bookmarked_at） | `merge.py:270` |
| annotation | `updated_at` LWW | `merge.py:320` |
| hidden_records | Union（INSERT OR IGNORE） | `merge.py:220` |
| hidden_domains | 本地优先（INSERT OR IGNORE） | `merge.py:225` |

### 3.3 现有加密（Security Architecture V2）

- **加密对象**：仅 `config.json` 中的 `webdav.password`
- **算法**：HKDF-SHA256 keystream XOR + HMAC-SHA256（Encrypt-then-MAC）
- **Payload 格式**：`0x02 (1B) | salt(16B) | HMAC(32B) | ciphertext(N×64B)`
- **数据库本体**：**明文**，仅依赖 HTTPS 传输加密

V3 在此基础上扩展，新增 Bundle 级 AES-256-GCM 加密，同时保持对 V2 格式的完整解密兼容。

---


## 4. 核心设计决策

### 4.1 Event-sourced 增量，而非状态差异比较

**决策**：在每次写入操作的同一事务内，同步追加一条 `change_log` 事件，而不是在同步时做"前后状态 diff"。

**理由**：
- 状态 diff 需要保存"上次同步快照"作为基线，实现复杂且容易出错（什么时候更新基线？）
- Event log 天然有序，append-only，不会丢失任何中间状态（如 visit_count 从 3 跳到 5）
- 多设备 replay event 时，每个事件独立幂等，不需要锁或协调

### 4.2 打包成不可变 Bundle，而非逐条传输

**决策**：客户端将 change_log 中的事件攒满阈值后打成一个 `.hsb` Bundle 文件再上传。

**理由**：

| 对比项 | 分块 Bundle | 逐条传输 |
|---|---|---|
| 服务端实现 | 纯 blob 存储（S3/WebDAV 直接用） | 必须有行级 API + 索引 + 范围查询 |
| 请求次数 | 每天约 1–5 次/设备 | 每天约 50–500 次/设备 |
| 元数据泄漏（E2EE 后服务端可见） | device_uuid、bundle_id、大小、时间 | 上述 + 每条事件的存在时刻、操作类型 |
| 压缩率 | zstd 字典压缩同 bundle URL 高度重复，60–80% | 单条无法做字典压缩 |
| CDN 可缓存性 | ✅ 不可变 blob，完美适合 CDN | ❌ 动态内容 |
| 崩溃恢复 | bundle 是事务边界 | 需要行级 checkpoint |

**打包阈值**（可配置）：
- `bundle_max_events = 100`（100 条事件）
- `bundle_max_bytes = 1 MB`（压缩前 payload）
- `bundle_max_age_seconds = 30`（最长等待时间）

三者任一满足即立即打包上传。

### 4.3 Frontier-driven Pull，无服务端协商

**决策**：每设备本地维护 `sync_frontier` 表，记录对每个远端设备已拉取的最大 HLC（Hybrid Logical Clock）。Pull 时只下载 frontier 之后的 bundle。

**理由**：WebDAV 服务器没有计算能力，不能"告诉客户端你需要什么"。Frontier 让客户端自主决定 diff，服务端只是 blob 存储。

### 4.4 冲突解决完全继承现有 CRDT 语义

**决策**：不引入新的冲突模型，event replay 时复用 `merge_from_db` 中已验证的合并规则。

**理由**：现有规则经过充分测试和实践验证，重新发明会引入新 bug，且用户已对当前行为有预期。

### 4.5 分块存储 Bundle，服务端不解析内容

**决策**：无论 WebDAV 还是私有服务器，都以整个 Bundle 文件为存储单元，服务端不解析 Bundle 内容。

**理由**：
1. E2EE 要求服务端无法解析内容（否则不是端到端加密）
2. Bundle 不可变，利于 CDN 缓存和断点续传
3. 服务端逻辑极简，降低运维风险

### 4.6 AES-256-GCM 替代 XOR Keystream

**决策**：Bundle 加密使用 AES-256-GCM，替代现有 Security V2 的 HKDF keystream XOR。

**理由**：
- XOR keystream 的最大输出受限（`_hkdf_expand_with_info` 最大 8160 字节），无法加密 1 MB bundle
- AES-GCM 是 AEAD（加密+完整性一体），一次调用同时提供机密性和完整性
- Python `cryptography` 库的 AES-GCM 有 OpenSSL 硬件加速，性能远优于纯 Python XOR
- 兼容性：保留 V2 格式用于 config.json password，V3 格式仅用于 bundle

---

## 5. 数据模型变更

### 5.1 新增表（通过 `_migrate_schema` 平滑迁移）

```sql
-- 变更日志：每次写操作的事件记录
-- 仅追加，不更新，不删除（由 purge_bundled_events 定期清理已打包的事件）
CREATE TABLE IF NOT EXISTS change_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hlc          INTEGER NOT NULL,              -- Hybrid Logical Clock（64-bit，全局有序）
    device_uuid  BLOB    NOT NULL,              -- 16 字节 UUID（来源设备）
    event_type   INTEGER NOT NULL,              -- 见 EventType 枚举
    payload      BLOB    NOT NULL,              -- MessagePack 编码的事件 payload
    bundled_at   INTEGER,                       -- 已打包进 bundle 的时间戳；NULL = 待打包
    created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_change_log_hlc ON change_log(hlc);
CREATE INDEX IF NOT EXISTS idx_change_log_bundled ON change_log(bundled_at) WHERE bundled_at IS NULL;

-- 已上传的 Bundle 清单
CREATE TABLE IF NOT EXISTS sync_bundles (
    bundle_id    TEXT    NOT NULL PRIMARY KEY,  -- ULID（26 字符，时间有序）
    device_uuid  TEXT    NOT NULL,              -- 来源设备 UUID（字符串形式）
    lamport_lo   INTEGER NOT NULL,              -- bundle 内 HLC 下界
    lamport_hi   INTEGER NOT NULL,              -- bundle 内 HLC 上界
    event_count  INTEGER NOT NULL,
    size_bytes   INTEGER NOT NULL,              -- 加密后文件大小
    uploaded_at  INTEGER NOT NULL,
    backend      TEXT    NOT NULL DEFAULT 'webdav'  -- 'webdav' | 'private' | ...
);
CREATE INDEX IF NOT EXISTS idx_sync_bundles_device ON sync_bundles(device_uuid, lamport_lo);

-- 同步边界：本设备对每个远端设备已成功 apply 到的 HLC
CREATE TABLE IF NOT EXISTS sync_frontier (
    device_uuid       TEXT    NOT NULL PRIMARY KEY,  -- 远端设备 UUID
    last_applied_hlc  INTEGER NOT NULL DEFAULT 0,    -- 已 apply 的最大 HLC
    last_pull_at      INTEGER,                       -- 上次拉取时间
    device_name       TEXT                           -- 缓存的设备昵称
);

-- Snapshot 清单
CREATE TABLE IF NOT EXISTS sync_snapshots (
    snapshot_id   TEXT    NOT NULL PRIMARY KEY,  -- ULID
    base_hlc      INTEGER NOT NULL,              -- snapshot 包含到此 HLC 的所有事件
    size_bytes    INTEGER NOT NULL,
    created_at    INTEGER NOT NULL,
    backend       TEXT    NOT NULL DEFAULT 'webdav'
);
```

### 5.2 现有表的小幅改动

```sql
-- hidden_records 已有 hidden_at，无需修改
-- 新增：允许 unhide 事件携带 unhidden_at 与 hidden_at 比较

-- hidden_domains 已有 hidden_at，无需修改

-- change_log 的 purge 策略：
--   bundled_at IS NOT NULL AND bundled_at < (now - 30 days) → 可安全删除
--   保留最近 30 天的已打包事件用于调试
```

### 5.3 HLC（Hybrid Logical Clock）实现

HLC 结合物理时间和逻辑计数器，保证：
1. 永不回拨（即使系统时钟向后跳）
2. 携带物理时间语义（可以"从某时间之后"查询）
3. 64-bit 整数，可直接存入 SQLite INTEGER 列

```python
# src/utils/hlc.py（新增文件，约 50 行）
import time
import threading

_PHYSICAL_SHIFT = 16          # 高 48 位存物理时间（ms），低 16 位存逻辑计数器
_MAX_LOGICAL    = 0xFFFF      # 逻辑计数器上限

class HybridLogicalClock:
    """线程安全的 Hybrid Logical Clock。
    
    格式（64-bit）：
      [63..16] = wall_ms（毫秒级 Unix 时间，48 位，够用到 2978 年）
      [15..0]  = logical_counter（本毫秒内的序号）
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._last: int = 0

    def now(self) -> int:
        """生成一个严格递增的 HLC 时间戳。"""
        with self._lock:
            wall = int(time.time() * 1000)
            wall_hlc = wall << _PHYSICAL_SHIFT
            if wall_hlc > self._last:
                self._last = wall_hlc
            else:
                # 时钟未前进（回拨 or 同毫秒）→ 递增逻辑计数器
                logical = (self._last & _MAX_LOGICAL) + 1
                if logical > _MAX_LOGICAL:
                    # 逻辑计数器溢出（极端情况：同毫秒 >65535 次写入）
                    # 强制等待到下一毫秒
                    self._last = ((self._last >> _PHYSICAL_SHIFT) + 1) << _PHYSICAL_SHIFT
                else:
                    self._last = (self._last & ~_MAX_LOGICAL) | logical
            return self._last

    def update(self, remote_hlc: int) -> int:
        """收到远端 HLC 后更新本地时钟，返回新的本地 HLC。"""
        with self._lock:
            wall = int(time.time() * 1000) << _PHYSICAL_SHIFT
            self._last = max(self._last, remote_hlc, wall) + 1
            return self._last

_global_hlc = HybridLogicalClock()

def hlc_now() -> int:
    return _global_hlc.now()

def hlc_update(remote: int) -> int:
    return _global_hlc.update(remote)

def hlc_to_ms(hlc: int) -> int:
    """提取 HLC 中的物理时间部分（毫秒）。"""
    return hlc >> _PHYSICAL_SHIFT
```

---


## 6. Bundle 文件格式规范

Bundle 文件扩展名为 `.hsb`（HistorySync Bundle）。**WebDAV Backend 和 Private Server Backend 使用完全相同的格式**，差异仅在传输层。

### 6.1 文件整体布局

```
┌──────────────────────────────────────────────────────────┐
│                  FIXED HEADER  (70 bytes)                 │
│  magic[4] | ver[1] | cipher[1] | compress[1] | flags[1]  │
│  device_uuid[16] | bundle_ulid[16]                       │
│  lamport_lo[8] | lamport_hi[8] | event_count[4]          │
│  payload_len[4] | key_generation[1] | reserved[5]        │
├──────────────────────────────────────────────────────────┤
│                  ENCRYPTED PAYLOAD                        │
│  nonce[12]                                               │
│  AES-256-GCM( key, nonce, AAD=header,                    │
│               plaintext=zstd(msgpack([Event,...])) )     │
│  gcm_tag[16]  (位于 ciphertext 末尾，Python cryptography  │
│               库自动附加)                                  │
├──────────────────────────────────────────────────────────┤
│                  TRAILER (optional, 64 bytes)             │
│  Ed25519 signature(sign_key, header || payload)          │
│  仅当 flags & 0x01 (SIGNED) 时存在                        │
└──────────────────────────────────────────────────────────┘
```

### 6.2 Fixed Header 字段详解

| 偏移 | 长度 | 字段名 | 说明 |
|---:|---:|---|---|
| 0 | 4 | `magic` | 固定值 `b"HSB1"` |
| 4 | 1 | `format_version` | `0x01`（当前版本） |
| 5 | 1 | `cipher_id` | `0x00` = 明文；`0x01` = AES-256-GCM；`0x02` = XChaCha20-Poly1305 |
| 6 | 1 | `compression_id` | `0x01` = zstd；`0x00` = 无压缩 |
| 7 | 1 | `flags` | bit0=SIGNED（含 Ed25519 trailer）；其余保留 |
| 8 | 16 | `device_uuid` | 来源设备 UUID（二进制，16 字节） |
| 24 | 16 | `bundle_ulid` | ULID（二进制，16 字节；含时间戳前缀，保证排序）|
| 40 | 8 | `lamport_lo` | bundle 内最小 HLC（uint64 little-endian） |
| 48 | 8 | `lamport_hi` | bundle 内最大 HLC（uint64 little-endian） |
| 56 | 4 | `event_count` | 事件数量（uint32 little-endian） |
| 60 | 4 | `payload_len` | 加密 payload 的字节数（含 nonce[12] + gcm_tag[16]） |
| 64 | 1 | `key_generation` | 密钥世代号（用于密钥轮换，见第 9 节） |
| 65 | 5 | `reserved` | 全零，保留 |

**Header 合计：70 字节**

### 6.3 Encrypted Payload 结构

```
payload = nonce[12] || AES-GCM-ciphertext[N] || gcm_tag[16]
```

其中：
- `nonce = HMAC-SHA256(nonce_key, bundle_ulid)[:12]`  
  使用确定性 nonce 而非随机 nonce：bundle_ulid 全局唯一，HMAC 输出确定，同一 bundle 重传时 nonce 相同（不会因为 nonce 重用影响安全性，因为 bundle 内容不变）
- `AAD = header[0:70]`（整个 header 参与认证，服务端无法篡改 lamport_range / device_uuid）
- `plaintext = zstd_compress(msgpack_encode([Event, ...]))`

### 6.4 明文模式（cipher_id = 0x00）

当 `cipher_id = 0x00` 时（WebDAV 用户显式关闭加密时）：
- payload 区域直接是 `zstd(msgpack([Event,...]))`，无 nonce 和 gcm_tag
- `payload_len` 为 zstd 压缩后字节数
- 无 Ed25519 trailer（flags & 0x01 = 0）

### 6.5 Bundle 文件命名规则

```
<device_uuid_hex_short8>_<bundle_ulid>.hsb

示例：
  a3f2c8d1_01JXXXXXXXXXXXXXXXXXXXXX.hsb

  device_uuid_hex_short8：device UUID 的前 8 个十六进制字符（仅用于目视区分，
                           完整 UUID 在 header 内）
  bundle_ulid：26 字符 ULID 字符串（Crockford Base32，按时间排序）
```

WebDAV 目录结构：
```
<remote_path>/
├── bundles/
│   ├── <device_uuid_A>/
│   │   ├── a3f2c8d1_01JXXX...abc.hsb
│   │   └── a3f2c8d1_01JXXX...def.hsb
│   └── <device_uuid_B>/
│       └── b7e1d4f2_01JXXX...xyz.hsb
├── snapshots/
│   └── snapshot_01JXXX...snap.hsb
├── manifest.json          ← 轻量级全局索引（~5 KB），供 list_bundles 用
└── legacy/                ← 旧版全量 ZIP，只读兼容
    ├── history_1700000000.zip
    └── sync_manifest.json
```

### 6.6 `manifest.json` 格式（WebDAV 专用）

私有服务器不需要此文件（有数据库索引）。WebDAV 无服务端逻辑，靠此文件实现 `list_bundles`。

```json
{
  "version": 2,
  "updated_at": 1748131200,
  "devices": {
    "a3f2c8d1-...": {"name": "MacBook Pro", "last_lamport_hi": 58230},
    "b7e1d4f2-...": {"name": "Desktop PC",  "last_lamport_hi": 57901}
  },
  "bundles": [
    {
      "id":          "01JXXX...abc",
      "device_uuid": "a3f2c8d1-...",
      "lo":          58001,
      "hi":          58100,
      "events":      87,
      "size":        73421,
      "uploaded_at": 1748131000
    }
  ],
  "latest_snapshot": {
    "id":        "01JXXX...snap",
    "base_hlc":  57000,
    "size":      15234567,
    "created_at":1748000000
  }
}
```

Pull 流程：下载 manifest.json（<5 KB）→ 比对本地 `sync_frontier` → 只下载 `lo > frontier` 的 bundle。

---

## 7. 事件类型系统

### 7.1 EventType 枚举

```python
from enum import IntEnum

class EventType(IntEnum):
    # ── History (0x01–0x0F) ────────────────────────────────────
    HISTORY_UPSERT        = 0x01  # 新增或更新一条历史记录（完整字段）
    HISTORY_DELETE        = 0x02  # URL 级删除（tombstone，影响此 URL 所有浏览器记录）
    HISTORY_DELETE_EXACT  = 0x03  # 精确三元组删除 (browser_type, url, visit_time)

    # ── Bookmark (0x10–0x1F) ───────────────────────────────────
    BOOKMARK_ADD          = 0x10  # 添加收藏（含完整 title + tags + bookmarked_at）
    BOOKMARK_REMOVE       = 0x11  # 取消收藏（tombstone）
    BOOKMARK_UPDATE_TAGS  = 0x12  # 仅更新标签（轻量，避免整条覆盖）
    BOOKMARK_UPDATE_TITLE = 0x13  # 仅更新标题

    # ── Annotation (0x20–0x2F) ────────────────────────────────
    ANNOTATION_UPSERT     = 0x20  # 新增或更新笔记（含 updated_at）
    ANNOTATION_DELETE     = 0x21  # 删除笔记（tombstone）

    # ── Visibility (0x30–0x3F) ────────────────────────────────
    HIDE_URL              = 0x30  # 隐藏 URL（写入 hidden_records）
    UNHIDE_URL            = 0x31  # 取消隐藏 URL（NEW：当前版本不可跨设备传播）
    HIDE_DOMAIN           = 0x32  # 隐藏域名（写入 hidden_domains）
    UNHIDE_DOMAIN         = 0x33  # 取消隐藏域名（NEW）

    # ── Control (0xF0–0xFF) ───────────────────────────────────
    DEVICE_REGISTER       = 0xF0  # 新设备注册（name, platform, app_version）
    REVOKE_DEVICE         = 0xF1  # 吊销设备（私有服务器专用；WebDAV 客户端可忽略）
    SNAPSHOT_MARKER       = 0xF2  # 标记 snapshot 基线（折叠点，不含数据）
```

### 7.2 各事件 Payload 字段

所有 payload 均为 MessagePack 编码的 dict，字段名为短字符串以节省空间。

```python
# HISTORY_UPSERT
{
    "u":  str,    # url
    "tt": str,    # title（空字符串合法）
    "vt": int,    # visit_time（Unix 秒）
    "vc": int,    # visit_count
    "bt": str,    # browser_type
    "pn": str,    # profile_name（可为空）
    "md": str,    # metadata（可为空）
    "tc": int|None,  # typed_count
    "fv": int|None,  # first_visit_time
    "tr": int|None,  # transition_type
    "vd": float|None # visit_duration
}

# HISTORY_DELETE
{"u": str, "da": int}   # url, deleted_at

# HISTORY_DELETE_EXACT
{"bt": str, "u": str, "vt": int}   # browser_type, url, visit_time

# BOOKMARK_ADD
{"u": str, "tt": str, "tg": list[str], "ba": int}
#  url,     title,      tags,           bookmarked_at

# BOOKMARK_REMOVE
{"u": str, "da": int}   # url, deleted_at

# BOOKMARK_UPDATE_TAGS
{"u": str, "tg": list[str], "ua": int}
#  url,     tags,             updated_at（= bookmarked_at 将被更新）

# BOOKMARK_UPDATE_TITLE
{"u": str, "tt": str, "ua": int}   # url, title, updated_at

# ANNOTATION_UPSERT
{"u": str, "n": str, "ca": int, "ua": int}
#  url,     note,    created_at, updated_at

# ANNOTATION_DELETE
{"u": str, "da": int}   # url, deleted_at

# HIDE_URL
{"u": str, "ha": int}   # url, hidden_at

# UNHIDE_URL
{"u": str, "ua": int}   # url, unhidden_at（用于 LWW 与 hidden_at 比较）

# HIDE_DOMAIN
{"d": str, "so": bool, "ha": int}
#  domain,  subdomain_only, hidden_at

# UNHIDE_DOMAIN
{"d": str, "ua": int}   # domain, unhidden_at

# DEVICE_REGISTER
{"uuid": str, "name": str, "plat": str, "ver": str}

# REVOKE_DEVICE
{"uuid": str, "ra": int}   # uuid, revoked_at
```

### 7.3 change_log 写入时机

在现有每个写入方法的**同一事务内**末尾调用 `_append_event(conn, event_type, payload)`：

| 写入方法 | 追加的事件 |
|---|---|
| `upsert_records(records)` | 每条 record → `HISTORY_UPSERT` |
| `delete_records_by_ids(ids)` | 按 URL 粒度 → `HISTORY_DELETE` 或 `HISTORY_DELETE_EXACT` |
| `delete_records_by_browser(bt)` | `HISTORY_DELETE` × N |
| `delete_records_by_domain(d)` | `HISTORY_DELETE` × N |
| `add_bookmark(url, ...)` | `BOOKMARK_ADD` |
| `remove_bookmark(url)` | `BOOKMARK_REMOVE` |
| `update_bookmark_tags(url, ...)` | `BOOKMARK_UPDATE_TAGS` |
| `upsert_annotation(url, ...)` | `ANNOTATION_UPSERT` |
| `delete_annotation(url)` | `ANNOTATION_DELETE` |
| `hide_records_by_ids(ids)` | `HIDE_URL` × N |
| `unhide_records_by_ids(ids)` | `UNHIDE_URL` × N |
| `hide_domain(domain, ...)` | `HIDE_DOMAIN` |
| `unhide_domain(domain)` | `UNHIDE_DOMAIN` |

**注意**：`merge_from_db` 和 `BundleApplier.apply()` **不写** change_log，防止 replay 事件被二次记录形成无限循环。通过 `_skip_changelog: bool` 上下文标志控制。

---


## 8. 冲突解决与 CRDT 语义

增量同步的冲突解决继承现有 `merge_from_db` 的语义，额外引入"复活规则"解决删除永久胜出的问题。

### 8.1 History 记录冲突

#### 并发 Upsert（同 URL 同 visit_time，不同设备或不同字段值）

```
规则（对应现有 ON CONFLICT DO UPDATE）：
  title:           CASE WHEN new.title != '' THEN new.title ELSE local.title END
  visit_count:     MAX(local.visit_count, new.visit_count)
  typed_count:     COALESCE(local.typed_count, new.typed_count)
  first_visit_time:COALESCE(local.first_visit_time, new.first_visit_time)
  transition_type: COALESCE(local.transition_type, new.transition_type)
  visit_duration:  COALESCE(local.visit_duration, new.visit_duration)
  device_id:       COALESCE(local.device_id, new.device_id)  ← 首次写入的设备胜出
```

所有规则幂等、可交换、可结合，满足 state-based CRDT 的三个属性。

#### Upsert 与 Delete 冲突（"复活规则"）

```
场景：设备 A 在 T3 删除了 URL，设备 B 在 T4（T4 > T3）又访问了同一 URL

Apply HISTORY_DELETE event 时的完整逻辑：
  local_tombstone_at = SELECT deleted_at FROM deleted_records WHERE url = ?

  # 先合并 tombstone（MAX 语义）
  UPSERT deleted_records SET deleted_at = MAX(local, event.da)

  # 检查"复活"：此 URL 是否存在 created_at > tombstone 的行？
  surviving = SELECT COUNT(*) FROM history
              WHERE url = ? AND created_at > MAX(local_tombstone_at, event.da)

  IF surviving > 0:
      # 用户在删除后重新访问了这个 URL → 不执行删除，移除 tombstone
      DELETE FROM deleted_records WHERE url = ?
  ELSE:
      # tombstone 有效 → 删除所有匹配行
      DELETE FROM history WHERE url = ?
```

**精确三元组删除**（`HISTORY_DELETE_EXACT`）不写 URL 级 tombstone，仅当该 URL 已无任何剩余行时才升级为 tombstone：

```sql
-- Apply HISTORY_DELETE_EXACT (browser_type=bt, url=u, visit_time=vt)
DELETE FROM history WHERE browser_type = ? AND url = ? AND visit_time = ?;

-- 检查是否需要升级为 URL 级 tombstone
INSERT OR IGNORE INTO deleted_records(url, deleted_at)
SELECT ?, strftime('%s','now')
WHERE NOT EXISTS (SELECT 1 FROM history WHERE url = ?);
```

### 8.2 Bookmark 冲突

#### 核心原则：`MAX(bookmarked_at, deleted_at)` 决定最终状态

```
Apply BOOKMARK_ADD event（url=u, bookmarked_at=ba）：
  local_deleted_at = SELECT deleted_at FROM deleted_bookmarks WHERE url = u
  
  IF local_deleted_at IS NULL OR ba > local_deleted_at:
      # 添加意图更新 → upsert bookmark，清除 tombstone
      UPSERT bookmarks(url, title, tags, bookmarked_at)
          ON CONFLICT(url) DO UPDATE SET
              title         = CASE WHEN ba > bookmarked_at THEN new.title ELSE local.title END,
              tags          = CASE WHEN ba > bookmarked_at THEN new.tags  ELSE local.tags  END,
              bookmarked_at = MAX(local.bookmarked_at, ba)
      DELETE FROM deleted_bookmarks WHERE url = u  ← 清除 tombstone（"复活"）
  ELSE:
      # 删除意图更新 → 忽略此 ADD 事件
      pass

Apply BOOKMARK_REMOVE event（url=u, deleted_at=da）：
  local_bookmarked_at = SELECT bookmarked_at FROM bookmarks WHERE url = u
  
  IF local_bookmarked_at IS NULL OR da > local_bookmarked_at:
      # 删除意图更新
      DELETE FROM bookmarks WHERE url = u
      UPSERT deleted_bookmarks(url, deleted_at) SET deleted_at = MAX(local, da)
  ELSE:
      # 添加意图更新 → 忽略此 REMOVE 事件
      pass
```

**时序示例（说明复活规则正确性）**：

```
T1: 设备A 收藏 github.com (bookmarked_at=100)
T2: 设备B 拉取，看到了收藏
T3: 设备B 取消收藏 (deleted_at=200)
T4: 设备A 重新收藏 (bookmarked_at=300)
T5: 两端同步

设备B 收到 T4 事件：ba=300 > local_deleted_at=200 → bookmark 复活 ✓
设备A 收到 T3 事件：da=200 < local_bookmarked_at=300 → 忽略 REMOVE 事件 ✓

最终两端状态：已收藏（bookmarked_at=300）✓
```

#### 标签冲突（LWW 整体替换）

```
Apply BOOKMARK_UPDATE_TAGS event（url=u, tags=tg, updated_at=ua）：
  current_bookmarked_at = SELECT bookmarked_at FROM bookmarks WHERE url = u
  
  IF current_bookmarked_at IS NOT NULL AND ua > current_bookmarked_at:
      UPDATE bookmarks SET bookmarked_at = ua WHERE url = u
      DELETE FROM bookmark_tags WHERE bookmark_id = (SELECT id FROM bookmarks WHERE url = u)
      INSERT INTO bookmark_tags(bookmark_id, tag) VALUES(?, ?) × len(tg)
  ELSE:
      pass  # 本地版本更新，忽略
```

**为何不用 tag Union 而是 LWW**：用户修改标签的语义是"我想要的最终标签集是这些"，而非"请帮我添加一个标签"。Union 会导致标签只能增加不能减少（删除某个 tag 需要广播 TAG_REMOVE 事件）。若未来需要细粒度标签同步，可新增 `TAG_ADD(0x14)` / `TAG_REMOVE(0x15)` 事件类型（向前兼容）。

### 8.3 Annotation 冲突

```
Apply ANNOTATION_UPSERT event（url=u, note=n, updated_at=ua）：
  UPSERT annotations(url, note, updated_at)
      ON CONFLICT(url) DO UPDATE SET
          note       = CASE WHEN ua > updated_at THEN new.note ELSE local.note END,
          updated_at = MAX(local.updated_at, ua)

Apply ANNOTATION_DELETE event（url=u, deleted_at=da）：
  local_updated_at = SELECT updated_at FROM annotations WHERE url = u
  IF local_updated_at IS NULL OR da > local_updated_at:
      DELETE FROM annotations WHERE url = u
      UPSERT deleted_annotations(url, deleted_at) SET deleted_at = MAX(local, da)
  ELSE:
      pass  # 注解内容比删除更新，忽略删除
```

### 8.4 Hidden / Unhide 冲突（新增语义）

```
Apply HIDE_URL event（url=u, hidden_at=ha）：
  UPSERT hidden_records(url, hidden_at)
      ON CONFLICT(url) DO UPDATE SET hidden_at = MAX(local.hidden_at, ha)

Apply UNHIDE_URL event（url=u, unhidden_at=ua）：
  local_hidden_at = SELECT hidden_at FROM hidden_records WHERE url = u
  IF local_hidden_at IS NOT NULL AND ua > local_hidden_at:
      DELETE FROM hidden_records WHERE url = u
  ELSE:
      pass  # 隐藏意图更新，忽略 UNHIDE

Apply HIDE_DOMAIN event（domain=d, subdomain_only=so, hidden_at=ha）：
  UPSERT hidden_domains(domain, subdomain_only, hidden_at)
      ON CONFLICT(domain) DO UPDATE SET
          subdomain_only = CASE WHEN ha > hidden_at THEN so ELSE subdomain_only END,
          hidden_at      = MAX(local.hidden_at, ha)

Apply UNHIDE_DOMAIN event（domain=d, unhidden_at=ua）：
  local_hidden_at = SELECT hidden_at FROM hidden_domains WHERE domain = d
  IF local_hidden_at IS NOT NULL AND ua > local_hidden_at:
      DELETE FROM hidden_domains WHERE domain = d
  ELSE:
      pass
```

### 8.5 冲突规则汇总

| 操作 | 决策规则 | 数学性质 |
|---|---|---|
| History 同字段并发写 | field-level MAX/COALESCE | Semilattice（join） |
| History delete vs upsert | `created_at > deleted_at` → 复活 | 带时间序的 OR-Set |
| History delete vs delete | `MAX(deleted_at)` | Max-register |
| Bookmark add vs remove | `MAX(bookmarked_at, deleted_at)` → 大者胜 | 带时间序的 OR-Set |
| Bookmark tags | `updated_at` LWW（整体替换） | LWW-register |
| Annotation | `updated_at` LWW | LWW-register |
| Annotation delete vs upsert | `MAX(updated_at, deleted_at)` | 带时间序的 OR-Set |
| Hide vs Unhide | `MAX(hidden_at, unhidden_at)` | LWW-register |
| Hide vs Hide | `MAX(hidden_at)` | Max-register |

**所有规则满足**：幂等性（I）、交换律（C）、结合律（A），即满足 state-based CRDT 的收敛条件。

---


## 9. 加密架构升级 (Security Architecture V3)

V3 在 V2 的密钥管理基础上扩展，不破坏任何现有解密能力。

### 9.1 密钥派生树

```
master_key (32B)
  ← 来源：OS Keyring (优先) 或 secret.key 文件 (降级)
  ← 不变：由 _get_or_create_master_key() 管理，V3 不修改

master_key + HKDF-Extract(salt = device_uuid_bytes[0:16])
  ↓
device_root_key (32B)          ← V3 新增，每设备唯一
  │
  ├─ HKDF-Expand(info="historysync-bundle-aead-v1\x00")
  │    → bundle_aead_key (32B)   ← AES-256-GCM 加密密钥
  │
  ├─ HKDF-Expand(info="historysync-bundle-nonce-v1\x00")
  │    → bundle_nonce_key (32B)  ← 确定性 nonce 派生
  │
  └─ HKDF-Expand(info="historysync-bundle-sign-v1\x00")
       → bundle_sign_seed (32B)  ← Ed25519 签名密钥种子（可选）


# V2 子密钥（保持不变，用于 config.json password）
master_key + HKDF-Extract(salt=random_16B)
  → prk
  ├─ HKDF-Expand(info="historysync-enc-key\x00")  → enc_key
  └─ HKDF-Expand(info="historysync-auth-key\x00") → auth_key
```

### 9.2 Bundle 加密/解密流程

```python
# src/utils/bundle_crypto.py（新增文件）

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hmac, hashlib

def derive_bundle_keys(master_key: bytes, device_uuid: bytes) -> tuple[bytes, bytes, bytes]:
    """派生 bundle 专用三元密钥：(aead_key, nonce_key, sign_seed)"""
    # HKDF-Extract: device_root_key
    device_root = hmac.new(device_uuid[:16], master_key, hashlib.sha256).digest()
    
    def expand(info: bytes) -> bytes:
        # HKDF-Expand, length=32
        return hmac.new(device_root, b"\x01" + info, hashlib.sha256).digest()
    
    aead_key  = expand(b"historysync-bundle-aead-v1\x00")
    nonce_key = expand(b"historysync-bundle-nonce-v1\x00")
    sign_seed = expand(b"historysync-bundle-sign-v1\x00")
    return aead_key, nonce_key, sign_seed

def derive_nonce(nonce_key: bytes, bundle_ulid: bytes) -> bytes:
    """确定性 nonce（12 字节）：HMAC(nonce_key, bundle_ulid)[:12]"""
    return hmac.new(nonce_key, bundle_ulid, hashlib.sha256).digest()[:12]

def encrypt_bundle_payload(
    aead_key: bytes,
    nonce: bytes,
    plaintext: bytes,          # zstd_compressed msgpack bytes
    aad: bytes,                # = fixed_header (70 bytes)
) -> bytes:
    """AES-256-GCM 加密，返回 ciphertext + 16B tag"""
    aesgcm = AESGCM(aead_key)
    return aesgcm.encrypt(nonce, plaintext, aad)

def decrypt_bundle_payload(
    aead_key: bytes,
    nonce: bytes,
    ciphertext_with_tag: bytes,  # ciphertext + 16B GCM tag
    aad: bytes,
) -> bytes:
    """AES-256-GCM 解密；tag 验证失败抛 InvalidTag"""
    aesgcm = AESGCM(aead_key)
    return aesgcm.decrypt(nonce, ciphertext_with_tag, aad)
```

### 9.3 密钥世代与轮换

每个 bundle header 含 `key_generation (1B)`，解密时按 generation 选对应密钥：

```python
# src/utils/key_store.py（新增）
@dataclass
class KeyGeneration:
    generation: int       # 0, 1, 2, ...
    master_key: bytes     # 32 字节
    created_at: int       # Unix 时间戳
    retired_at: int | None = None  # 轮换时设置

class KeyStore:
    """管理多世代密钥，支持平滑轮换。"""
    
    def get_current_gen(self) -> KeyGeneration: ...
    def get_gen(self, generation: int) -> KeyGeneration | None: ...
    
    def rotate(self) -> KeyGeneration:
        """生成新世代密钥。
        
        流程：
          1. new_key = os.urandom(32)
          2. old_gen.retired_at = now
          3. 写入 Keyring（key "master_key:gen=N"）
          4. 老世代保留 90 天，然后由 purge_old_generations() 清理
        """
```

### 9.4 私有服务器的强制加密

私有服务器 Backend 在 `upload_bundle` 前校验 `cipher_id != 0x00`，否则拒绝：

```python
class PrivateServerBackend(SyncBackend):
    def upload_bundle(self, local_path: Path, meta: BundleMeta) -> None:
        # 读取 header 前 6 字节，检查 cipher_id
        with local_path.open("rb") as f:
            header_start = f.read(6)
        if len(header_start) < 6 or header_start[5] == 0x00:
            raise ValueError(
                "Private server requires encrypted bundles. "
                "Set incremental_sync.encryption_enabled = true"
            )
        # ... 继续上传
```

### 9.5 Ed25519 签名（可选，flags & 0x01）

当 `flags & 0x01 = 1` 时，bundle 末尾附加 64 字节 Ed25519 签名：

```python
# 签名覆盖范围：header(70B) + nonce(12B) + ciphertext(N B)
sign_key = Ed25519PrivateKey.from_private_bytes(sign_seed)
signature = sign_key.sign(header_bytes + encrypted_payload)

# 验证
verify_key = Ed25519PublicKey.from_public_bytes(
    sign_key.public_key().public_bytes_raw()
)
verify_key.verify(signature, header_bytes + encrypted_payload)
```

**Ed25519 的用途**：在设备吊销场景中，可以分发吊销后的公钥列表，其他设备拒绝接受来自被吊销设备的 bundle，即使 AES 密钥尚未轮换。

### 9.6 与 V2 的兼容性

- `config.json` 中的 WebDAV password 继续使用 V2 格式（`ENC:<base64>`），不迁移
- Bundle 加密是 V3 格式，与 V2 完全独立
- 老版客户端（不支持增量同步）：无法读取 `.hsb` 文件，但全量 ZIP 备份不受影响

---

## 10. SyncBackend 抽象接口

`SyncBackend` 是整个增量同步系统的插件化核心。WebDAV、私有服务器、S3、Dropbox 等只需实现这 5 个抽象方法。

```python
# src/services/sync_backends/base.py

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass(slots=True)
class BundleMeta:
    bundle_id:   str    # ULID（26 字符）
    device_uuid: str    # 来源设备 UUID（字符串）
    lamport_lo:  int    # bundle 内最小 HLC
    lamport_hi:  int    # bundle 内最大 HLC
    event_count: int
    size_bytes:  int    # 加密后文件大小
    uploaded_at: int    # Unix 时间戳

@dataclass(slots=True)
class SnapshotMeta:
    snapshot_id: str    # ULID
    base_hlc:    int    # snapshot 包含到此 HLC 的所有数据
    size_bytes:  int
    created_at:  int

class SyncBackend(ABC):
    """
    增量同步后端的统一抽象接口。
    
    实现者只需关注"如何存取字节"，不需要理解 Bundle 内容。
    Bundle 的生成、加密、解密、Event replay 全部由上层处理。
    """

    # ── 必须实现的 5 个方法 ─────────────────────────────────────

    @abstractmethod
    def upload_bundle(self, local_path: Path, meta: BundleMeta) -> None:
        """上传一个 Bundle 文件到远端存储。
        
        实现应保证原子性：上传失败不能留下不完整文件。
        建议：先上传到临时路径，成功后原子重命名。
        
        Raises:
            SyncBackendError: 上传失败（网络、认证、配额等）
        """

    @abstractmethod
    def list_bundles(
        self,
        device_uuid: str | None = None,
        after_lamport: int = 0,
    ) -> list[BundleMeta]:
        """列出远端 Bundle 元数据列表。
        
        Args:
            device_uuid:   None = 所有设备；指定 UUID = 只列该设备的 bundle
            after_lamport: 只返回 lamport_lo > after_lamport 的 bundle
        
        Returns:
            按 lamport_lo 升序排列的 BundleMeta 列表
        """

    @abstractmethod
    def download_bundle(self, bundle_id: str, dest: Path) -> None:
        """下载指定 Bundle 到本地路径。
        
        Raises:
            BundleNotFoundError: bundle_id 在服务端不存在
            SyncBackendError:    下载失败
        """

    @abstractmethod
    def upload_snapshot(self, local_path: Path, meta: SnapshotMeta) -> None:
        """上传 Snapshot 文件（全量快照，用于新设备首次同步）。"""

    @abstractmethod
    def get_latest_snapshot(self) -> SnapshotMeta | None:
        """获取最新 Snapshot 的元数据（不下载文件）。
        
        Returns:
            最新 SnapshotMeta，或 None（无 snapshot）
        """

    # ── 可选方法（有默认实现）──────────────────────────────────

    def download_snapshot(self, snapshot_id: str, dest: Path) -> None:
        """下载 Snapshot。默认实现等价于 download_bundle。"""
        self.download_bundle(snapshot_id, dest)

    def delete_bundles(self, bundle_ids: list[str]) -> list[str]:
        """裁剪 Bundle（snapshot 折叠后调用）。
        
        Returns:
            删除失败的 bundle_id 列表（空列表表示全部成功）
        """
        return []  # 默认不支持删除，安全降级

    def supports_push_notification(self) -> bool:
        """是否支持服务端主动推送（WebSocket/SSE）。
        
        False = 客户端定时轮询（WebDAV）
        True  = 服务端有新 bundle 时主动通知客户端
        """
        return False

    def subscribe_push(self, callback) -> None:
        """订阅推送通知。仅当 supports_push_notification() 返回 True 时实现。"""
        pass

    def health_check(self) -> bool:
        """检查后端连通性。默认实现尝试 list_bundles(limit=1)。"""
        try:
            self.list_bundles(after_lamport=2**62)  # 极大值，预期返回空列表
            return True
        except Exception:
            return False


class SyncBackendError(Exception):
    """后端操作失败的基础异常。"""

class BundleNotFoundError(SyncBackendError):
    """请求的 bundle 在服务端不存在。"""

class QuotaExceededError(SyncBackendError):
    """存储配额超限（私有服务器付费功能）。"""
```

---


## 11. WebDAV Backend 实现

```python
# src/services/sync_backends/webdav_backend.py

class WebDavSyncBackend(SyncBackend):
    """
    基于 webdavclient3 的 SyncBackend 实现。
    
    远端结构：
      <remote_path>/
      ├── bundles/<device_uuid>/  ← 每设备一个子目录
      │   └── <bundle_id>.hsb
      ├── snapshots/
      │   └── <snapshot_id>.hsb
      └── manifest.json           ← 全局元数据索引（WebDAV 的"穷人版数据库"）
    
    线程安全：manifest.json 更新使用"临时文件 + 原子重命名"模式，
              与现有 webdav_resumable.py 的 upload_resumable 策略一致。
    """
    
    def upload_bundle(self, local_path: Path, meta: BundleMeta) -> None:
        client = self._make_client()
        remote_dir = f"{self._remote_path}/bundles/{meta.device_uuid}/"
        self._ensure_dir(client, remote_dir)
        remote_file = f"{remote_dir}{meta.bundle_id}.hsb"
        
        # 复用现有 ResumableTransfer.upload_resumable（temp 文件 + atomic move）
        self._resumable.upload_resumable(client, local_path, remote_file)
        
        # 更新 manifest.json（读取→合并→写回）
        self._update_manifest(client, lambda m: m["bundles"].append({
            "id": meta.bundle_id, "device_uuid": meta.device_uuid,
            "lo": meta.lamport_lo, "hi": meta.lamport_hi,
            "events": meta.event_count, "size": meta.size_bytes,
            "uploaded_at": meta.uploaded_at,
        }))

    def list_bundles(
        self,
        device_uuid: str | None = None,
        after_lamport: int = 0,
    ) -> list[BundleMeta]:
        # 下载 manifest.json（轻量，<5 KB）
        manifest = self._fetch_manifest()
        bundles = manifest.get("bundles", [])
        result = []
        for b in bundles:
            if device_uuid and b["device_uuid"] != device_uuid:
                continue
            if b["lo"] <= after_lamport:
                continue
            result.append(BundleMeta(
                bundle_id=b["id"], device_uuid=b["device_uuid"],
                lamport_lo=b["lo"], lamport_hi=b["hi"],
                event_count=b["events"], size_bytes=b["size"],
                uploaded_at=b["uploaded_at"],
            ))
        # 按 lamport_lo 升序
        return sorted(result, key=lambda x: x.lamport_lo)
    
    def download_bundle(self, bundle_id: str, dest: Path) -> None:
        # 先从 manifest 找 device_uuid → 确定路径
        manifest = self._fetch_manifest()
        b = next((b for b in manifest["bundles"] if b["id"] == bundle_id), None)
        if not b:
            raise BundleNotFoundError(bundle_id)
        remote_file = f"{self._remote_path}/bundles/{b['device_uuid']}/{bundle_id}.hsb"
        client = self._make_client()
        self._resumable.download_resumable(client, remote_file, dest)

    def upload_snapshot(self, local_path: Path, meta: SnapshotMeta) -> None:
        client = self._make_client()
        remote_dir = f"{self._remote_path}/snapshots/"
        self._ensure_dir(client, remote_dir)
        remote_file = f"{remote_dir}{meta.snapshot_id}.hsb"
        self._resumable.upload_resumable(client, local_path, remote_file)
        self._update_manifest(client, lambda m: m.update({
            "latest_snapshot": {
                "id": meta.snapshot_id, "base_hlc": meta.base_hlc,
                "size": meta.size_bytes, "created_at": meta.created_at,
            }
        }))
    
    def get_latest_snapshot(self) -> SnapshotMeta | None:
        manifest = self._fetch_manifest()
        snap = manifest.get("latest_snapshot")
        if not snap:
            return None
        return SnapshotMeta(
            snapshot_id=snap["id"], base_hlc=snap["base_hlc"],
            size_bytes=snap["size"], created_at=snap["created_at"],
        )

    def delete_bundles(self, bundle_ids: list[str]) -> list[str]:
        # 裁剪 snapshot 折叠后的老 bundle，错误不阻塞主流程
        failed = []
        manifest = self._fetch_manifest()
        client = self._make_client()
        id_set = set(bundle_ids)
        bm = {b["id"]: b for b in manifest["bundles"]}
        for bid in bundle_ids:
            b = bm.get(bid)
            if not b:
                continue
            remote_file = f"{self._remote_path}/bundles/{b['device_uuid']}/{bid}.hsb"
            try:
                client.clean(remote_file)
            except Exception as e:
                log.warning("delete_bundle %s failed: %s", bid, e)
                failed.append(bid)
        # 更新 manifest
        self._update_manifest(client, lambda m: m.update({
            "bundles": [b for b in m["bundles"] if b["id"] not in id_set]
        }))
        return failed
```

### 11.1 manifest.json 并发更新安全

多设备同时 upload_bundle 时都会更新 manifest.json，可能出现竞态。策略：

1. 下载 manifest → 修改 → 上传到 `manifest.json.uploading.<rand>` → MOVE 覆盖
2. 最后一个 MOVE 成功的设备的版本胜出（Last-Write-Wins on manifest）
3. **manifest 仅是索引，不是真相的来源**：即使 manifest 暂时不一致，`list_bundles` 可以降级扫目录（`PROPFIND <remote_path>/bundles/`）重建
4. Pull 时若发现 manifest 中没有某 bundle 但文件存在（目录扫描），仍可正常下载

---

## 12. 私有服务器 Backend 实现

### 12.1 服务端架构

```
┌─────────────────────────────────────────────────────────┐
│                 HistorySync Private Server               │
│                                                          │
│  FastAPI (Python 3.11+) / Go Fiber                      │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ REST API    │  │ WebSocket   │  │ Admin API       │ │
│  │ /api/v1/    │  │ /ws/push    │  │ /admin/         │ │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘ │
│         └────────────────┼──────────────────┘           │
│                    ┌─────▼──────┐                        │
│                    │ PostgreSQL │  ← bundle 元数据索引   │
│                    └─────┬──────┘                        │
│                    ┌─────▼──────┐                        │
│                    │ S3 / MinIO │  ← bundle blob 存储   │
│                    └────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

### 12.2 REST API 端点（OpenAPI 草案）

```yaml
# 认证：JWT Bearer Token（用 master_key 派生的 device_sign_key 签发）

POST   /api/v1/auth/register    # 设备注册，返回 device_token
POST   /api/v1/auth/refresh     # token 刷新

POST   /api/v1/bundles          # 上传 bundle（multipart/form-data）
GET    /api/v1/bundles          # 列出 bundle 元数据
       ?device_uuid=&after_lamport=&limit=

GET    /api/v1/bundles/{id}     # 下载 bundle（返回二进制文件）
DELETE /api/v1/bundles/{id}     # 删除 bundle（需要是上传者）

POST   /api/v1/snapshots        # 上传 snapshot
GET    /api/v1/snapshots/latest # 获取最新 snapshot 元数据
GET    /api/v1/snapshots/{id}   # 下载 snapshot

GET    /api/v1/devices          # 列出本账号下所有设备
POST   /api/v1/devices/{uuid}/revoke  # 吊销设备
GET    /api/v1/revocations      # 获取吊销列表（客户端定期拉取）

GET    /api/v1/quota            # 查询账号存储配额使用情况
```

### 12.3 WebSocket 推送通知

```
客户端连接：ws://server/ws/push?token=<device_token>

服务端推送事件（JSON）：
  {"type": "bundle_uploaded",   "device_uuid": "...", "bundle_id": "..."}
  {"type": "snapshot_uploaded", "snapshot_id": "..."}
  {"type": "device_revoked",    "device_uuid": "..."}

客户端收到 bundle_uploaded 事件后立即触发 pull 流程。
```

### 12.4 客户端 PrivateServerBackend 实现

```python
class PrivateServerBackend(SyncBackend):
    def __init__(self, config: PrivateServerConfig):
        self._config = config
        self._session = requests.Session()
        self._ws = None  # WebSocket 连接，懒加载
    
    def upload_bundle(self, local_path: Path, meta: BundleMeta) -> None:
        # 强制校验加密
        self._verify_encrypted(local_path)
        with local_path.open("rb") as f:
            resp = self._session.post(
                f"{self._config.url}/api/v1/bundles",
                files={"bundle": (meta.bundle_id + ".hsb", f, "application/octet-stream")},
                data={
                    "bundle_id": meta.bundle_id,
                    "device_uuid": meta.device_uuid,
                    "lamport_lo": str(meta.lamport_lo),
                    "lamport_hi": str(meta.lamport_hi),
                    "event_count": str(meta.event_count),
                },
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=120,
            )
        resp.raise_for_status()
    
    def list_bundles(self, device_uuid=None, after_lamport=0) -> list[BundleMeta]:
        params = {"after_lamport": after_lamport}
        if device_uuid:
            params["device_uuid"] = device_uuid
        resp = self._session.get(
            f"{self._config.url}/api/v1/bundles",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return [BundleMeta(**b) for b in resp.json()["bundles"]]
    
    def supports_push_notification(self) -> bool:
        return True
    
    def subscribe_push(self, callback) -> None:
        import websocket
        def on_message(ws, message):
            data = json.loads(message)
            if data["type"] == "bundle_uploaded":
                callback("bundle_uploaded", data)
            elif data["type"] == "device_revoked":
                callback("device_revoked", data)
        self._ws = websocket.WebSocketApp(
            f"{self._config.ws_url}/ws/push?token={self._token}",
            on_message=on_message,
        )
        threading.Thread(target=self._ws.run_forever, daemon=True).start()
```

### 12.5 设备吊销流程

```
1. 用户在设备 A 执行：hsync sync revoke <device_uuid>
2. 调用 POST /api/v1/devices/{uuid}/revoke
3. 服务端：
   a. 标记该设备 token 失效（拒绝后续 upload）
   b. 向所有在线设备推送 {type: "device_revoked", device_uuid: ...}
   c. 被吊销设备的 bundle 在服务端保留（用于其他设备查询历史）
4. 其他客户端收到推送后：
   a. 更新本地 sync_frontier，将该设备标记为 revoked
   b. 不再 apply 此后来自该设备的任何 bundle
5. 被吊销设备再次请求时：401 Unauthorized
```

---


## 13. BundleBuilder 与 BundleApplier

### 13.1 BundleBuilder

BundleBuilder 从 `change_log` 读取未打包事件，打包成 `.hsb` 文件并调用 `SyncBackend.upload_bundle`。

```python
# src/services/bundle_builder.py

class BundleBuilder:
    """
    从 change_log 读取未打包事件 → 打包成 .hsb → 上传到 Backend。
    
    打包阈值（任一满足即触发）：
      - bundle_max_events:  100 条事件
      - bundle_max_bytes:   1 MB（压缩前 payload 估算）
      - bundle_max_age_secs:30 秒（最长等待时间）
    """
    
    def __init__(self, db: LocalDatabase, backend: SyncBackend, config: SyncConfig):
        self._db = db
        self._backend = backend
        self._config = config
        self._crypto = BundleCrypto(config)  # 封装加密/解密逻辑

    def flush(self, force: bool = False) -> int:
        """
        检查是否需要打包并上传。
        
        Args:
            force: True = 无论是否达到阈值，立即打包剩余事件
        
        Returns:
            本次上传的 bundle 数量
        """
        uploaded = 0
        while True:
            events = self._db.get_unbundled_events(
                limit=self._config.bundle_max_events
            )
            if not events:
                break
            if not force and not self._should_flush(events):
                break
            
            bundle_id = ulid_generate()           # 时间有序 ULID
            device_uuid = self._db.local_device_uuid
            
            # 序列化：msgpack → zstd
            payload_plain = zstd.compress(
                msgpack.packb([e.to_dict() for e in events]),
                level=3,
            )
            
            # 加密
            header_bytes, encrypted_payload = self._crypto.encrypt_bundle(
                bundle_id=bundle_id,
                device_uuid=device_uuid,
                events=events,
                payload_plain=payload_plain,
            )
            
            # 写入临时文件
            tmp = Path(tempfile.mktemp(suffix=".hsb"))
            try:
                tmp.write_bytes(header_bytes + encrypted_payload)
                
                meta = BundleMeta(
                    bundle_id=bundle_id,
                    device_uuid=device_uuid,
                    lamport_lo=events[0].hlc,
                    lamport_hi=events[-1].hlc,
                    event_count=len(events),
                    size_bytes=tmp.stat().st_size,
                    uploaded_at=int(time.time()),
                )
                
                # 上传
                self._backend.upload_bundle(tmp, meta)
                
                # 标记已打包（同事务）
                event_ids = [e.id for e in events]
                self._db.mark_events_bundled(event_ids, bundle_id)
                self._db.record_bundle(meta)
                
                uploaded += 1
            finally:
                tmp.unlink(missing_ok=True)
        
        return uploaded
    
    def _should_flush(self, events: list) -> bool:
        if len(events) >= self._config.bundle_max_events:
            return True
        oldest_created_at = events[0].created_at if events else 0
        if time.time() - oldest_created_at >= self._config.bundle_max_age_secs:
            return True
        return False
```

### 13.2 BundleApplier

BundleApplier 下载远端 bundle，解密后 replay 事件到本地数据库。

```python
# src/services/bundle_applier.py

class BundleApplier:
    """
    下载 bundle → 解密 → replay 事件到本地 DB。
    
    关键保证：
      1. apply 过程不写 change_log（通过 _skip_changelog 标志防止循环）
      2. 每个 bundle 的 apply 在一个 SQLite SAVEPOINT 内，失败可回滚
      3. apply 完成后更新 sync_frontier（frontier 仅在成功后推进）
    """
    
    def __init__(self, db: LocalDatabase, backend: SyncBackend, config: SyncConfig):
        self._db = db
        self._backend = backend
        self._crypto = BundleCrypto(config)

    def pull_and_apply(
        self,
        progress_cb: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        """
        拉取所有设备的新 bundle 并 apply。
        
        Returns:
            {device_uuid: applied_event_count}
        """
        # 收集每个已知设备的 frontier
        frontiers = self._db.get_sync_frontiers()  # {uuid: last_applied_hlc}
        
        # 找出所有设备中 frontier 最小的，作为全局查询起点
        min_frontier = min(frontiers.values(), default=0)
        
        # 从 backend 列出所有新 bundle
        all_bundles = self._backend.list_bundles(after_lamport=min_frontier)
        
        # 按设备分组，确保同设备的 bundle 按 lamport 顺序 apply
        by_device: dict[str, list[BundleMeta]] = {}
        for b in all_bundles:
            if b.device_uuid == self._db.local_device_uuid:
                continue  # 跳过自己上传的 bundle
            device_frontier = frontiers.get(b.device_uuid, 0)
            if b.lamport_lo > device_frontier:
                by_device.setdefault(b.device_uuid, []).append(b)
        
        results: dict[str, int] = {}
        
        for device_uuid, bundles in by_device.items():
            applied = 0
            for meta in sorted(bundles, key=lambda x: x.lamport_lo):
                tmp = Path(tempfile.mktemp(suffix=".hsb"))
                try:
                    # 下载
                    self._backend.download_bundle(meta.bundle_id, tmp)
                    
                    # 解密 + 反序列化
                    events = self._crypto.decrypt_bundle(tmp)
                    
                    # 应用（在 SAVEPOINT 内）
                    n = self._apply_events(events, device_uuid)
                    applied += n
                    
                    # 更新 frontier
                    self._db.update_frontier(device_uuid, meta.lamport_hi)
                    
                except BundleNotFoundError:
                    log.warning("bundle %s not found, skipping", meta.bundle_id)
                except Exception as e:
                    # 单个 bundle 失败：记录到 quarantine，继续处理其他 bundle
                    log.error("failed to apply bundle %s: %s", meta.bundle_id, e)
                    self._db.quarantine_bundle(meta.bundle_id, str(e))
                finally:
                    tmp.unlink(missing_ok=True)
            
            results[device_uuid] = applied
        
        return results

    def _apply_events(self, events: list[SyncEvent], source_device_uuid: str) -> int:
        """在 SAVEPOINT 内 replay 事件列表，返回成功 apply 的事件数。"""
        applied = 0
        
        # 关键：设置标志，让写入方法跳过 change_log 追加
        with self._db.skip_changelog_context():
            with self._db.savepoint("apply_bundle") as conn:
                for event in events:
                    try:
                        self._apply_single_event(conn, event, source_device_uuid)
                        applied += 1
                    except Exception as e:
                        log.warning("skip malformed event type=%d: %s", event.event_type, e)
                        # 单条事件错误不回滚整个 bundle，记录跳过
        
        return applied

    def _apply_single_event(
        self, conn, event: SyncEvent, source_device_uuid: str
    ) -> None:
        """将单条事件的变更写入数据库（调用现有写入方法，不走 change_log）。"""
        p = event.payload
        et = event.event_type
        hlc = event.hlc

        if et == EventType.HISTORY_UPSERT:
            record = HistoryRecord(
                url=p["u"], title=p.get("tt",""), visit_time=p["vt"],
                visit_count=p.get("vc",1), browser_type=p["bt"],
                profile_name=p.get("pn",""), metadata=p.get("md",""),
                typed_count=p.get("tc"), first_visit_time=p.get("fv"),
                transition_type=p.get("tr"), visit_duration=p.get("vd"),
                device_id=self._db.get_or_create_device_id(source_device_uuid),
            )
            self._db.upsert_records([record])

        elif et == EventType.HISTORY_DELETE:
            url, da = p["u"], p["da"]
            # 复活规则：检查 created_at > da 的存活行
            surviving = conn.execute(
                "SELECT COUNT(*) FROM history WHERE url=? AND created_at>?", (url, da)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO deleted_records(url,deleted_at) VALUES(?,?)"
                " ON CONFLICT(url) DO UPDATE SET deleted_at=MAX(deleted_at,excluded.deleted_at)",
                (url, da),
            )
            if surviving == 0:
                conn.execute("DELETE FROM history WHERE url=?", (url,))
            else:
                conn.execute("DELETE FROM deleted_records WHERE url=?", (url,))

        elif et == EventType.HISTORY_DELETE_EXACT:
            conn.execute(
                "DELETE FROM history WHERE browser_type=? AND url=? AND visit_time=?",
                (p["bt"], p["u"], p["vt"]),
            )
            # 如果 URL 已无任何行，升级为 URL tombstone
            if not conn.execute("SELECT 1 FROM history WHERE url=?", (p["u"],)).fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO deleted_records(url,deleted_at) VALUES(?,?)",
                    (p["u"], hlc_to_ms(hlc) // 1000),
                )

        elif et == EventType.BOOKMARK_ADD:
            local_del = conn.execute(
                "SELECT deleted_at FROM deleted_bookmarks WHERE url=?", (p["u"],)
            ).fetchone()
            if not local_del or p["ba"] > local_del[0]:
                self._db.add_bookmark(p["u"], p.get("tt",""), p.get("tg",[]))
                conn.execute("DELETE FROM deleted_bookmarks WHERE url=?", (p["u"],))

        elif et == EventType.BOOKMARK_REMOVE:
            local_bm = conn.execute(
                "SELECT bookmarked_at FROM bookmarks WHERE url=?", (p["u"],)
            ).fetchone()
            if not local_bm or p["da"] > local_bm[0]:
                self._db.remove_bookmark(p["u"])

        elif et == EventType.BOOKMARK_UPDATE_TAGS:
            local_bm = conn.execute(
                "SELECT bookmarked_at FROM bookmarks WHERE url=?", (p["u"],)
            ).fetchone()
            if local_bm and p["ua"] > local_bm[0]:
                self._db.update_bookmark_tags(p["u"], p.get("tg",[]))

        elif et == EventType.ANNOTATION_UPSERT:
            self._db.upsert_annotation(p["u"], p.get("n",""))

        elif et == EventType.ANNOTATION_DELETE:
            local_ann = conn.execute(
                "SELECT updated_at FROM annotations WHERE url=?", (p["u"],)
            ).fetchone()
            if not local_ann or p["da"] > local_ann[0]:
                self._db.delete_annotation(p["u"])

        elif et == EventType.HIDE_URL:
            conn.execute(
                "INSERT INTO hidden_records(url,hidden_at) VALUES(?,?)"
                " ON CONFLICT(url) DO UPDATE SET hidden_at=MAX(hidden_at,excluded.hidden_at)",
                (p["u"], p["ha"]),
            )
        elif et == EventType.UNHIDE_URL:
            local_hr = conn.execute(
                "SELECT hidden_at FROM hidden_records WHERE url=?", (p["u"],)
            ).fetchone()
            if local_hr and p["ua"] > local_hr[0]:
                conn.execute("DELETE FROM hidden_records WHERE url=?", (p["u"],))

        elif et == EventType.HIDE_DOMAIN:
            self._db.hide_domain(p["d"], p.get("so", False))

        elif et == EventType.UNHIDE_DOMAIN:
            local_hd = conn.execute(
                "SELECT hidden_at FROM hidden_domains WHERE domain=?", (p["d"],)
            ).fetchone()
            if local_hd and p["ua"] > local_hd[0]:
                self._db.unhide_domain(p["d"])
```

---


## 14. Scheduler 集成

### 14.1 新增 IncrementalSyncWorker

在现有 `scheduler.py` 中平行新增 `IncrementalSyncWorker`，与 `SyncWorker`（浏览器抽取）和 `BackupWorker`（全量备份）完全独立：

```python
class IncrementalSyncWorker(QObject):
    """增量同步 Worker：先 push 本地 bundle，再 pull 远端 bundle。"""
    
    finished = Signal(dict)   # {"pushed": N, "pulled": {uuid: count}}
    error    = Signal(str)
    progress = Signal(str)
    
    def __init__(self, builder: BundleBuilder, applier: BundleApplier):
        super().__init__()
        self._builder = builder
        self._applier = applier
        self._cancelled = threading.Event()
    
    @Slot()
    def run(self) -> None:
        try:
            # 1. Push：将本地未上传的 bundle 全部上传
            pushed = self._builder.flush(force=False)
            self.progress.emit(f"Pushed {pushed} bundle(s)")
            
            if self._cancelled.is_set():
                return
            
            # 2. Pull：拉取所有远端新 bundle 并 apply
            pulled = self._applier.pull_and_apply(
                progress_cb=self.progress.emit
            )
            
            total_applied = sum(pulled.values())
            self.progress.emit(f"Applied {total_applied} event(s) from {len(pulled)} device(s)")
            
            self.finished.emit({"pushed": pushed, "pulled": pulled})
        except Exception as e:
            self.error.emit(str(e))
```

### 14.2 Scheduler 配置扩展

```python
# src/models/app_config.py 新增

@dataclass
class IncrementalSyncConfig:
    enabled:               bool  = False     # opt-in 新功能，默认关闭
    backend:               str   = "webdav"  # "webdav" | "private" | 插件名
    interval_seconds:      int   = 30        # push+pull 周期
    bundle_max_events:     int   = 100
    bundle_max_bytes:      int   = 1_048_576  # 1 MB
    bundle_max_age_secs:   int   = 30
    snapshot_every_bundles:int   = 1000      # 每 N 个 bundle 触发一次 snapshot 折叠
    snapshot_every_days:   int   = 7         # 或每 N 天触发一次
    encryption_enabled:    bool  = True      # WebDAV 可关闭，私服强制 True
    purge_bundled_days:    int   = 30        # change_log 已打包事件保留天数
```

### 14.3 三条定时线互不干扰

```
浏览器抽取 Timer (sync_interval_hours)
    └→ SyncWorker → run_extraction() → upsert_records() → 写 change_log

增量同步 Timer (interval_seconds = 30s)
    └→ IncrementalSyncWorker → BundleBuilder.flush() + BundleApplier.pull_and_apply()

全量备份 Timer (auto_backup_interval_hours, 仅作为灾难恢复保底)
    └→ BackupWorker → WebDavSyncService.sync() → 整库 ZIP

三条线共享同一把 _lock（写操作串行），读操作通过 _ro_conn 并发。
```

### 14.4 增量同步触发逻辑

```python
# Scheduler.configure() 增量同步相关部分（新增）

if inc_config.enabled and inc_config.interval_seconds > 0:
    self._inc_timer.setInterval(inc_config.interval_seconds * 1000)
    # 启动时：先等一个完整间隔，避免刚启动就 push 半个 bundle
    first_delay = self._calc_first_interval_ms(
        inc_config.interval_seconds * 1000,
        last_incremental_sync_ts,
    )
    self._inc_lead_timer.start(max(0, first_delay))

# 手动触发（CLI: hsync sync push/pull）
def trigger_incremental_now(self) -> None:
    if not self._inc_running:
        self._run_incremental_sync(force_push=True)
```

---

## 15. CLI 新增子命令

在现有 `hsync` CLI 基础上，`sync` 升级为子命令组：

```
hsync sync push              # 打包并上传所有待上传事件
hsync sync pull              # 拉取所有远端 bundle 并 apply
hsync sync status            # 显示同步状态（frontier、待上传事件数、空间用量）
hsync sync watch [--interval N]  # 前台守护，每 N 秒自动 push+pull（默认 30s）
hsync sync compact           # 强制生成 snapshot 并裁剪可删除的老 bundle
hsync sync rotate-key        # 轮换 master_key（交互式确认）
hsync sync revoke <uuid>     # 吊销指定设备（仅私服后端有效）
hsync sync list-devices      # 列出所有已知设备及其 frontier
```

### `hsync sync status` 输出示例

```
══════════════════════════════════════
 Incremental Sync Status
══════════════════════════════════════
 Backend       webdav (https://dav.example.com)
 Encryption    AES-256-GCM (key_gen=0)
 Local device  MacBook Pro (a3f2c8d1-...)

 Pending events (unbundled)    23
 Pending upload (local bundles) 1

 Remote devices:
   Desktop PC  (b7e1d4f2-...)  frontier HLC=57901  last_pull=2min ago
   Phone       (c9a3e5f0-...)  frontier HLC=57850  last_pull=5min ago

 Latest snapshot  01JXXX...  base_hlc=57000  size=14.5 MB  7d ago
══════════════════════════════════════
```

---

## 16. 多设备同步全流程

### 16.1 正常工作流（3 台设备）

```
MacBook (A)          Desktop (B)          Phone (C)
  │                      │                    │
  │ 访问网页 x.com        │                    │
  │ → upsert_records()   │                    │
  │ → change_log += E1   │                    │
  │                      │                    │
  │──[30s timer]──────→  │                    │
  │ BundleBuilder.flush()│                    │
  │ → bundle_001.hsb     │                    │
  │ → upload to WebDAV   │                    │
  │                      │                    │
  │                  [30s timer]              │
  │                 BundleApplier.pull()      │
  │                 → download bundle_001     │
  │                 → apply E1 (upsert)       │
  │                 → frontier[A] = HLC(E1)   │
  │                      │                   │
  │ 删除书签 github.com   │                    │
  │ → remove_bookmark()  │                    │
  │ → change_log += E2   │                    │
  │   (BOOKMARK_REMOVE)  │                    │
  │                      │                    │
  │ 在 B 重新添加同一书签 │                    │
  │                 add_bookmark()            │
  │                 bookmarked_at = T_B       │
  │                 → change_log[B] += E3     │
  │                 (BOOKMARK_ADD, ba=T_B)    │
  │                      │                    │
  │──[flush]────────────→│                    │
  │ upload bundle_002    │                    │
  │ (contains E2)        │                    │
  │                      │                    │
  │               [pull] │                    │
  │               download bundle_002        │
  │               apply E2: BOOKMARK_REMOVE   │
  │               local bookmarked_at=T_B     │
  │               E2.da < T_B → 忽略 REMOVE  │
  │               书签保持存在 ✓              │
  │                      │                    │
  │               [flush]│                    │
  │               upload bundle_003           │
  │               (contains E3)              │
  │                      │                    │
  │    [pull]            │                    │
  │ apply E3: ba=T_B     │                    │
  │ local del_at < T_B   │                    │
  │ → 书签复活 ✓         │                    │
```

### 16.2 新设备首次加入

```
新设备 (D) 首次启动：

1. generate device_uuid，写入 config.json
2. SyncManager 初始化：
   a. 检查是否有 snapshot → get_latest_snapshot()
   
3a. 有 snapshot（推荐路径）：
   a. download_snapshot(snapshot_id, tmp.hsb)
   b. 解密 → 得到 history.db（无 FTS）
   c. LocalDatabase.replace_database(tmp.db)  ← 复用现有方法
   d. 重建 FTS（rebuild_fts_index()）
   e. 读取 snapshot.base_hlc，设置所有已知设备 frontier = base_hlc
   f. pull 所有 bundle（lamport > base_hlc）并 apply
   
3b. 无 snapshot（fallback）：
   a. 直接 pull 所有 bundle，从 lamport=0 开始
   b. 数据量大时可能很慢（历史遗留场景）

4. upload DEVICE_REGISTER event（让其他设备知道有新设备加入）
```

### 16.3 长期离线后重新上线

```
设备 A 离线 30 天后重新上线：

1. BundleApplier.pull_and_apply()
   → 从 frontier 开始，可能有大量 bundle 需要 apply

2. 如果有 snapshot.base_hlc > 本地 frontier：
   → 提示用户：是否用 snapshot 恢复（更快）？
   → 用户选择 snapshot：replace_database → 重建 FTS → pull 增量 bundle
   → 用户选择继续 apply：逐 bundle 处理（慢但不丢本地数据）

3. 重新上线后的事件（本地 30 天的浏览历史）：
   → 这些已经在 change_log 中，BundleBuilder.flush() 打包上传
   → 其他设备 pull 后 apply（HLC 时间戳正确标记了事件发生时间）
```

---

## 17. Snapshot 折叠机制

Snapshot 是某一时刻全量数据库状态的加密快照，用于：
1. 新设备快速初始化（避免 replay 所有历史 bundle）
2. Bundle 文件数量超限时折叠（删除 snapshot.base_hlc 之前的 bundle）

### 17.1 触发条件

```python
def should_compact(self) -> bool:
    local_bundle_count = self._db.count_local_bundles()
    last_snapshot_at = self._db.get_last_snapshot_at()
    
    return (
        local_bundle_count >= self._config.snapshot_every_bundles  # 默认 1000
        or
        (time.time() - last_snapshot_at) >= self._config.snapshot_every_days * 86400  # 默认 7d
    )
```

### 17.2 Snapshot 生成流程

```python
def compact(self) -> SnapshotMeta:
    """生成全量 snapshot 并上传；成功后裁剪老 bundle。"""
    
    # 1. 获取当前最大 HLC（原子快照点）
    base_hlc = self._db.get_max_hlc()
    
    # 2. 导出无 FTS 的数据库副本（复用现有 export_without_fts）
    tmp_db = Path(tempfile.mktemp(suffix="_snap.db"))
    self._db.export_without_fts(tmp_db)
    
    # 3. 加密封装为 .hsb（cipher_id = 0x01, event_count = 0, SNAPSHOT_MARKER）
    #    payload = zstd(tmp_db.read_bytes())
    snapshot_id = ulid_generate()
    tmp_hsb = Path(tempfile.mktemp(suffix="_snap.hsb"))
    self._crypto.encrypt_snapshot(tmp_db, tmp_hsb, snapshot_id, base_hlc)
    
    # 4. 上传
    meta = SnapshotMeta(
        snapshot_id=snapshot_id,
        base_hlc=base_hlc,
        size_bytes=tmp_hsb.stat().st_size,
        created_at=int(time.time()),
    )
    self._backend.upload_snapshot(tmp_hsb, meta)
    self._db.record_snapshot(meta)
    
    # 5. 裁剪：删除 lamport_hi < base_hlc 的老 bundle（所有设备的）
    old_bundles = self._db.get_bundles_before_hlc(base_hlc)
    failed = self._backend.delete_bundles([b.bundle_id for b in old_bundles])
    if not failed:
        self._db.delete_bundle_records([b.bundle_id for b in old_bundles])
    else:
        log.warning("compact: failed to delete %d bundles (non-fatal)", len(failed))
    
    return meta
```

### 17.3 Snapshot 文件格式

Snapshot 复用 `.hsb` 格式，但有特殊标记：
- `event_count = 0`（不是 event bundle，是全量快照）
- `flags` 中设置 `SNAPSHOT_BIT (0x02)`
- payload 的 plaintext = `zstd_compress(sqlite_db_bytes)`（去 FTS 的 SQLite 文件）
- bundle_ulid 的 ULID 前缀被用于时间排序，便于找"最新 snapshot"

客户端收到 snapshot 后，调用 `replace_database()` 而非 apply events。

---


## 18. 威胁模型与安全分析

### 18.1 受保护的资产

| 资产 | 机密级别 | 描述 |
|---|---|---|
| 浏览历史 URL + 时间 | 高度隐私 | 用户的完整上网行为 |
| 书签、笔记 | 高度隐私 | 用户主动标注的信息 |
| 隐藏记录列表 | 高度隐私 | 用户明确不想展示的 URL |
| 设备名称 / UUID | 中等隐私 | 标识用户设备 |
| 访问频率 / 时序 | 行为指纹 | 可用于推断用户习惯 |

### 18.2 威胁与应对

#### T1：WebDAV 服务器管理员读取数据

**威胁**：用户将备份存到第三方 WebDAV（Nextcloud、坚果云等），服务端管理员可读文件。  
**V2 现状**：数据库明文，管理员可直接读取所有历史。  
**V3 应对**：Bundle 启用 AES-256-GCM 加密（默认开启），服务端只见不可解的密文 blob。  
**残余风险**：元数据（bundle 大小、上传时间、设备数量）仍可见；无法消除。

#### T2：中间人攻击（MITM on HTTPS）

**威胁**：网络中间人截获 WebDAV 传输内容。  
**应对**：
- 传输层：HTTPS + `verify_ssl=True`（现有，默认强制）
- 应用层：AES-GCM AAD 包含 bundle_id，中间人无法篡改内容后通过 GCM 验证
- 防降级：客户端拒绝接受 `cipher_id = 0x00` 的 bundle（如配置了 `encryption_required=true`）

#### T3：设备丢失 / 被盗

**威胁**：盗贼获取了某台设备，希望继续向同步服务推送污染数据。  
**WebDAV 应对**：无强吊销机制；建议用户更换 WebDAV 密码（使所有设备的凭据失效）并重新分发；未来可研究"设备证书"机制。  
**私服应对**：`POST /api/v1/devices/{uuid}/revoke` 立即吊销，服务端拒绝该设备的所有后续上传，其他设备收到 WebSocket 推送后停止 apply 该设备的 bundle。

#### T4：恶意事件注入（来自被吊销设备）

**威胁**：被吊销设备在吊销前上传了恶意 bundle（如大量 `HISTORY_DELETE` 清除所有记录）。  
**应对**：
- Ed25519 签名 + 公钥注册：其他设备验证 bundle 签名，被吊销设备的公钥从 revocation list 移除
- 对 `HISTORY_DELETE` 事件：复活规则（`created_at > deleted_at`）防止删除永久胜出
- 本地 change_log 保留 30 天，可用于"撤销回滚"（`hsync sync rollback --before <date>`，计划中的功能）

#### T5：时钟篡改（HLC 回拨）

**威胁**：攻击者将某设备时钟往未来调，制造高 HLC 事件，让其在所有 LWW 冲突中永远胜出。  
**应对**：
- HLC 自带单调性：`hlc_now()` 返回值永不小于历史值（即使系统时钟回拨）
- 接收端验证：如果远端 bundle 的 `lamport_hi` 比当前本地 HLC 超过 `MAX_DRIFT = 30 * 24 * 3600 * 1000`（30 天），拒绝该 bundle 并 quarantine
- 隔离文件：`<data_dir>/sync_quarantine/<bundle_id>.hsb`，日志记录原因

#### T6：Bundle 重放攻击

**威胁**：攻击者保存旧 bundle 并再次上传（将已回滚的事件重新 apply）。  
**应对**：
- `sync_frontier` 只推进不回退：`last_applied_hlc = MAX(current, new)`
- Apply 前检查：`event.hlc <= frontier[device]` 则跳过（已 apply）
- 幂等性：所有 apply 操作幂等，重放只会"无效 apply"，不会有害

### 18.3 端到端加密覆盖范围

| 数据 | E2EE 状态 | 说明 |
|---|---|---|
| Bundle payload（历史/书签/笔记/隐藏） | ✅ AES-256-GCM | 服务端不可解密 |
| Bundle header（device_uuid, lamport_range, 大小） | ❌ 明文 | 元数据不可避免地暴露 |
| WebDAV 登录凭据 | ✅ V2 HKDF 加密存储于 config.json | 不落盘明文 |
| 私服 JWT token | ✅ 设备签名，短期有效 | |
| FTS 索引（本地） | ❌ 明文（本地文件） | 不同步，纯本地 |
| 全量 ZIP 备份（legacy） | ❌ 明文（历史兼容） | 建议用户迁移到增量模式 |

---

## 19. 性能估算

### 19.1 存储用量（每设备每天）

假设：每天新增 200 条历史记录 + 5 次书签操作 + 2 次笔记操作

| 项目 | 计算 | 结果 |
|---|---|---|
| 每条 `HISTORY_UPSERT` event | ~150 字节（msgpack） | |
| 200 条 history events | 200 × 150B | ~30 KB |
| 7 条其他 events | 7 × 80B | ~0.5 KB |
| msgpack 总计 | | ~30.5 KB |
| zstd 压缩（URL 重复率高，ratio≈3x） | 30.5 / 3 | ~10 KB |
| AES-GCM overhead（nonce 12B + tag 16B） | | ~28 B |
| bundle 文件大小（2 个 bundle/天） | | ~5 KB / bundle |
| **每设备每天上传流量** | 2 × 5 KB | **~10 KB** |
| **每设备每月上传流量** | 10 KB × 30 | **~300 KB** |
| **每设备每年上传流量** | 300 KB × 12 | **~3.6 MB** |

对比现有全量备份：50 万条库 → 压缩后 ~80 MB；即使每天备份一次也是 80 MB/天。**增量模式节省 4 个数量级的流量**。

### 19.2 Snapshot 大小

50 万条历史记录（无 FTS）的数据库：
- 原始 SQLite：~60–80 MB
- 去 FTS 后（双 VACUUM INTO）：~20–30 MB
- zstd 压缩：~8–12 MB
- AES-GCM overhead：16 B（tag）+ 12 B（nonce）

**Snapshot 文件约 8–12 MB，每 7 天生成一次，年产 ~600 MB**（但仅需保留最新 1–2 个）。

### 19.3 apply 延迟

| 场景 | 估算 |
|---|---|
| 下载一个 5 KB bundle | < 100ms（100 Mbps 宽带）|
| decrypt + decompress 5 KB | < 5ms（AES-NI 硬件加速）|
| apply 100 条 upsert events | < 50ms（复用现有 upsert_records，SAVEPOINT）|
| **端到端延迟（设备 A 写入→设备 B 看到）** | **~30s–60s**（受 pull 周期控制）|
| 私服 WebSocket 推送模式 | **~2s–5s**（bundle 上传完成即推送）|

### 19.4 change_log 表大小

每条 change_log 行约 250–300 字节（含 hlc, device_uuid, event_type, payload msgpack）。
- 200 条/天 × 300 B = 60 KB/天
- 30 天保留 = 1.8 MB（极小，不影响数据库性能）
- 已打包 30 天后 purge，表大小稳定在 ~2 MB

---

## 20. 迁移路径（4 阶段）

### Phase 1 — v1.4：数据基础（用户无感知）

**目标**：为增量同步铺好数据层基础，不暴露任何用户功能。

变更内容：
- `_migrate_schema()` 新增 `change_log`、`sync_bundles`、`sync_frontier`、`sync_snapshots` 四张表
- 所有写入方法（`upsert_records`, `add_bookmark` 等）末尾追加 `_append_event()`
- 新增 `src/utils/hlc.py`（HLC 实现）
- 新增 `src/utils/bundle_crypto.py`（AES-GCM 加密层）
- 新增 `src/services/sync_backends/base.py`（接口定义）
- 新增 `src/services/sync_backends/webdav_backend.py`（WebDAV 实现，不对外激活）
- 特性开关 `INCREMENTAL_SYNC_DEV_ENABLED = False`（环境变量 `HSYNC_DEV_INCREMENTAL=1` 可临时开启）

风险：新增表和 change_log 追加，**不影响任何现有功能**，schema 迁移幂等。

### Phase 2 — v1.5：CLI 实验性功能

**目标**：Power users 可通过 CLI 测试增量同步，GUI 暂不暴露。

变更内容：
- 新增 `hsync sync push / pull / status / watch / compact` CLI 子命令
- 在 `hsync config` 新增 `incremental.*` 配置项
- `IncrementalSyncWorker` 实现完成
- `BundleBuilder` + `BundleApplier` 完整实现
- 文档：`docs/site/guide/incremental-sync.md`

启用方式：`hsync config set incremental.enabled true`（CLI only）

### Phase 3 — v1.6：GUI 集成 + 私服 Beta

**目标**：GUI 全功能上线，私服 reference 实现开源。

变更内容：
- Settings → Sync 新增 "Incremental Sync" 子 tab（独立于 WebDAV tab）
- 状态面板：显示每设备 frontier、待上传 events、bundle 数量
- 私有服务器 reference 实现（`server/` 子目录，FastAPI + PostgreSQL + MinIO）
- `PrivateServerBackend` 实现完成
- 私服 beta 测试（邀请制）

### Phase 4 — v2.0：默认开启

**目标**：增量同步成为默认体验，全量备份降级为保底。

变更内容：
- 新安装默认 `incremental.enabled = true`（仍需用户配置存储后端）
- 全量备份改为每 7 天一次（作为 snapshot 的同步入口，而非主备份）
- GUI Setup Wizard 引导用户选择同步后端
- 私服云服务上线（付费功能）
- CLI `hsync sync` 默认等价于 `hsync sync push && hsync sync pull`

---


## 21. 风险与应对

| 风险 | 严重性 | 概率 | 应对措施 |
|---|---|---|:---|
| change_log 双写导致 FTS 不一致 | 高 | 低 | `_skip_changelog_context()` 上下文管理器防止 apply 时二次追加；现有 `_ensure_fts_triggers` 崩溃保护依然有效 |
| manifest.json 并发覆盖 | 中 | 中 | manifest 只是索引；降级为 PROPFIND 目录扫描重建；LWW 覆盖不丢数据（bundle 文件仍在） |
| HLC 溢出（同毫秒 >65535 次写入）| 低 | 极低 | HLC 实现中强制等下一毫秒；正常使用场景（每次浏览记录 1 条事件）不可能触发 |
| 大体量 apply 阻塞 UI | 中 | 低 | `IncrementalSyncWorker` 在 QThread 运行，不阻塞主线程；apply 使用与 `merge_from_db` 相同的流式 batch=2000 策略 |
| WebDAV 并发上传大量 bundle（长期离线后） | 中 | 中 | `BundleBuilder.flush()` 串行上传，失败重试；断点续传复用现有 `ResumableTransfer` |
| Bundle 解密失败（密钥丢失或损坏） | 高 | 低 | 解密失败的 bundle 移入 `quarantine/` 目录，不静默丢弃；记录到 sync_log；保留整库 ZIP 备份作为恢复兜底 |
| 私服服务不可用期间的本地累积 | 中 | 中 | change_log 事件无限积累直到服务恢复；本地 SQLite 每条事件 ~300 B，100 万条也只 ~300 MB（可接受）；超过 `purge_bundled_days=30` 的已打包事件定期清理 |
| 旧版客户端无法读取新格式 | 低 | 确定 | .hsb 文件不可被旧版读取，但旧版不会主动删除它们；全量 ZIP 备份保留在 `legacy/` 目录；文档明确说明版本要求 |
| Tombstone 表无限膨胀 | 中 | 低 | 现有 `prune_tombstones(keep_days=90)` 定期清理（已由 `vacuum_and_analyze` 触发）；增量同步不改变此逻辑 |
| 时钟漂移 >30 天（极端 HLC 时间戳） | 低 | 极低 | 接收端验证 `lamport_hi` 与本地时钟差值；超过 `MAX_DRIFT` 的 bundle 被 quarantine |

---

## 22. 开放问题

以下问题需要作者决策后才能最终确定：

### Q1：Bundle 阈值

当前建议：`max_events=100 / max_bytes=1MB / max_age=30s`

| 选项 | 优点 | 缺点 |
|---|---|---|
| `max_age=5s`（激进） | 接近实时同步 | 碎 bundle 多，请求次数增加 |
| `max_age=30s`（建议） | 平衡实时性和请求效率 | 手机省电场景可能仍偏频繁 |
| `max_age=5min`（保守） | 极少请求，节能 | 延迟明显 |

**建议**：默认 30s，UI 里提供"实时"（5s）/"平衡"（30s）/"省电"（5min）三档。

### Q2：加密算法选择

| 算法 | 优点 | 缺点 |
|---|---|---|
| **AES-256-GCM**（当前建议）| 硬件加速（AES-NI），标准 AEAD，广泛支持 | nonce 重用致命（由确定性派生 nonce 缓解）|
| XChaCha20-Poly1305 | 抗 nonce 误用，无 AES-NI 时更快 | Python `cryptography` 库支持稍复杂 |

**建议**：默认 AES-256-GCM；在 `cipher_id` 字段预留 `0x02=XChaCha20-Poly1305`，未来客户端可选。

### Q3：Snapshot 触发策略

| 策略 | 优点 | 缺点 |
|---|---|---|
| 固定 bundle 数（每 1000 个）| 可预测 | 低频用户可能永远不触发 |
| 固定天数（每 7 天）| 保证定期快照 | 高频用户可能过于频繁 |
| **组合**（bundle 数 OR 天数，当前建议）| 兼顾两端 | 配置项稍多 |
| 本地 bundle 总大小 > snapshot 大小 × 30%  | 存储驱动，最合理 | 需要知道 snapshot 大小（鸡蛋问题）|

**建议**：默认"每 1000 bundle 或每 7 天，取先到者"；UI 暴露为一个"同步折叠频率"滑块。

### Q4：WebDAV 私有服务器的 manifest.json 写锁

多设备同时 upload_bundle 时 manifest 竞态写是目前 WebDAV Backend 的最大弱点。

| 方案 | 可行性 |
|---|---|
| 客户端接受 LWW 覆盖，降级为目录扫描 | ✅ 已设计为 fallback |
| WebDAV `LOCK` + `UNLOCK` | ❌ 大多数 WebDAV 服务器不支持或限制 LOCK |
| manifest 版本号 + CAS（Compare-And-Swap）| ⚠️ WebDAV `If` header 支持有限 |
| 不依赖 manifest，完全靠目录扫描 | ✅ 可靠，但每次 pull 需要 PROPFIND（略慢）|

**建议**：保留 manifest 作为快速路径（cache），目录扫描作为 fallback，两者结果不一致时以目录扫描为准。

### Q5：私有服务器 bundle 存储后端

| 选项 | 部署门槛 | 横向扩展 | 推荐场景 |
|---|---|---|---|
| PostgreSQL + S3/MinIO | 高 | ★★★ | 商业云服务 |
| SQLite + 本地磁盘 | 低 | ★ | 个人 VPS / NAS |
| PostgreSQL + 本地磁盘 | 中 | ★★ | 小团队自托管 |

**建议**：reference 实现提供两个 Compose 配置：
1. `docker-compose.simple.yml`：SQLite + 本地磁盘（个人用，一个容器）
2. `docker-compose.full.yml`：PostgreSQL + MinIO（生产用，微服务拆分）

---

## 附录 A：文件新增列表

```
src/
├── utils/
│   ├── hlc.py                         # Hybrid Logical Clock
│   ├── bundle_crypto.py               # Bundle 加密/解密（AES-GCM）
│   ├── key_store.py                   # 密钥世代管理
│   └── ulid.py                        # ULID 生成（或引入 python-ulid 依赖）
├── services/
│   ├── bundle_builder.py              # change_log → .hsb 打包上传
│   ├── bundle_applier.py              # 下载 .hsb → replay events
│   ├── snapshot_manager.py            # Snapshot 折叠管理
│   └── sync_backends/
│       ├── __init__.py
│       ├── base.py                    # SyncBackend ABC + BundleMeta + SnapshotMeta
│       ├── webdav_backend.py          # WebDAV 实现
│       └── private_server_backend.py  # 私有服务器实现
│
server/                                # 私有服务器（独立目录）
├── README.md
├── app/
│   ├── main.py                        # FastAPI 入口
│   ├── api/
│   │   ├── bundles.py
│   │   ├── snapshots.py
│   │   ├── devices.py
│   │   └── auth.py
│   ├── storage/
│   │   ├── blob.py                    # S3/MinIO/本地磁盘抽象
│   │   └── db.py                      # PostgreSQL/SQLite 元数据存储
│   └── ws/
│       └── push.py                    # WebSocket 推送
├── docker-compose.simple.yml
└── docker-compose.full.yml
```

## 附录 B：依赖变更

```toml
# pyproject.toml 新增

[project.optional-dependencies]
incremental = [
    "cryptography>=42.0",   # AES-256-GCM（可能已作为现有依赖存在）
    "msgpack>=1.0",         # 事件序列化
    "zstandard>=0.22",      # Bundle payload 压缩
    "python-ulid>=2.0",     # ULID 生成
]

private-server = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "sqlalchemy>=2.0",
    "asyncpg>=0.29",        # PostgreSQL async driver
    "aioboto3>=12.0",       # S3/MinIO async client
    "websockets>=12.0",
]
```

安装增量同步依赖：`pip install historysync[incremental]`

`cryptography` 很可能已经作为间接依赖存在（WebDAV 库引用），需验证后确认是否 0 新增依赖。

---

*文档版本 1.0.0-draft — 待作者评审后更新为 1.0.0-final*
