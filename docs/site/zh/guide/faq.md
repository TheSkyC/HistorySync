---
title: 常见问题
description: HistorySync 常见问题解答 — 安装、同步、隐私、WebDAV 等。
---

# 常见问题

---

## 一般问题

### HistorySync 会将我的浏览数据上传给第三方吗？

**不会。** HistorySync 完全以本地为优先。所有历史数据都存储在**你自己机器上**的 SQLite 数据库中。唯一的网络流量是可选的 WebDAV 备份 — 目标是*你自己*控制的服务器（或自建服务）。HistorySync 永远不会发送任何分析数据、遥测信息或外部请求。

### 支持哪些浏览器？

HistorySync 原生支持 **30+ 款浏览器**，包括：

**Chromium 系：** Chrome、Edge、Brave、Vivaldi、Arc、Chromium、Opera、Opera GX、Yandex 浏览器、百分浏览器、Thorium 等。

**Firefox 系：** Firefox、Firefox ESR、LibreWolf、Waterfox、Pale Moon、SeaMonkey、Basilisk。

**Safari：** 仅 macOS。

**国内浏览器（Windows/macOS/Linux）：** QQ 浏览器、搜狗浏览器、UC 浏览器、猎豹浏览器、傲游浏览器、星愿浏览器等。

如果你的浏览器未在列表中，请使用**设置 → 浏览器 → 添加自定义路径**手动添加，或尝试智能扫描功能。

### 可以在多台电脑上使用 HistorySync 吗？

可以！在每台设备上安装 HistorySync，配置相同的 WebDAV 服务器，并启用自动同步。恢复时（或 HistorySync 自动从云端合并时），来自所有设备的记录将根据浏览器类型、URL 和访问时间戳**智能去重**。

---

## 同步与提取

### 浏览器开着的时候 HistorySync 也能工作吗？

可以。HistorySync 使用 **SQLite WAL（预写日志）快照** — 它在读取前先复制 WAL 文件，因此与正在运行的浏览器不会产生任何冲突。你的浏览器不会被锁定或暂停。

### 为什么同步后有些记录缺失？

几个可能的原因：

- **隐私/无痕浏览** — 浏览器不会将无痕浏览历史写入磁盘；HistorySync 无法获取。
- **浏览器配置文件被禁用** — 检查**设置 → 浏览器**，确认该配置文件未被禁用。
- **URL 被过滤** — HistorySync 会自动忽略内部浏览器 URL（`chrome://`、`about:`、`file://` 等）以及黑名单中的域名。
- **首次同步为增量模式** — 尝试**设置 → 维护 → 完全重新同步**，或使用 GUI 启动入口 `python -m src.main --resync`，重新读取所有历史记录。

### 什么是"完全重新同步"？

普通同步是**增量**的 — 只读取上次同步时间戳之后的新记录。完全重新同步忽略水印，重新读取所有浏览器的每一条记录，补全 `visit_count` 等可能在早期同步中未捕获的字段。可随时安全运行 — 记录使用 upsert，不会产生重复。

```bash
# 通过 GUI 启动入口（不是 hsync CLI）
python -m src.main --resync

# 通过 GUI：设置 → 维护 → 完全重新同步
```

---

## 隐私与安全

### 我的数据存储在哪里？

| 平台 | 默认位置 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

使用 `--config-dir 路径` 覆盖，或使用 `--portable` 将所有内容存储在可执行文件旁边。

### WebDAV 凭证如何保护？

凭证**永远不会明文存储**。HistorySync 通过系统密钥链（via `keyring`）存储主密钥，并使用 HKDF 派生独立的加密和认证子密钥。详见[安全架构](../dev/security.md)。

### 什么是"软隐藏" / 隐藏记录？

软隐藏将某条记录（或某个域名的所有记录）标记为隐藏 — 它们从主历史视图中消失，但仍保留在数据库中。可在**历史 → 显示隐藏记录**中查看。这对于隐藏敏感页面而不永久删除非常有用。

### 什么是域名黑名单？

黑名单中的域名**永远不会被导入**，已有的相关记录也会被**永久删除**。右键点击记录 → **拉黑该域名**，或在**设置 → 隐私 → 域名黑名单**中管理。

---

## WebDAV 与云端备份

### 哪些 WebDAV 服务商兼容 HistorySync？

任何标准 WebDAV 服务器均可。已测试：Nextcloud、Synology DSM、ownCloud、AList、Nginx WebDAV、Apache mod_dav、Caddy WebDAV。详见 [WebDAV 配置指南](webdav-setup.md)。

### 保留多少份备份？

默认保留 **10 份备份**。每次成功上传后，旧的备份会自动清理。通过 `hsync config set webdav.max_backups N` 修改。

### 备份失败提示"连接被拒绝"，我该怎么排查？

1. 验证 WebDAV URL（协议、主机名、端口、路径）。
2. 检查用户名和密码 — Nextcloud 请使用**应用密码**。
3. 测试连通性：`curl -u user:pass https://your-server/dav/`。
4. 如使用自签名证书，设置 `hsync config set webdav.verify_ssl false`。

---

## 性能

### HistorySync 在百万条记录下运行缓慢，怎么解决？

按顺序尝试以下步骤：

1. **运行 `hsync db vacuum`** — 回收碎片空间，刷新查询优化器统计信息。
2. **运行 `hsync db rebuild-fts`** — 重建全文搜索索引。
3. 确保数据库在本地快速 SSD 上，而非网络共享或 USB 设备。
4. 如果使用正则表达式搜索，考虑改用普通关键词搜索 — 正则通过 SQL 下推更快，但非常复杂的模式仍可能较慢。

---

## CLI（`hsync`）

### 如何在 Docker 容器 / CI 流水线中使用 `hsync`？

使用 `--headless` 模式避免 GUI 依赖：

```bash
python -m src.main --headless --sync --config-dir /data/config
```

或直接使用 `hsync`：

```bash
hsync -s --config-dir /data/config -q
```

如果 Qt 报错提示没有显示器，设置 `QT_QPA_PLATFORM=offscreen`。

---

## 贡献与开发

### 如何报告 Bug？

使用 **[GitHub Bug 报告模板](https://github.com/TheSkyC/HistorySync/issues/new?template=bug_report.yml)**。请包含你的操作系统、HistorySync 版本、涉及的浏览器及复现步骤。

### 我发现了安全漏洞，该怎么做？

**请勿开公开 Issue。** 请直接发邮件至 **security@historysync.app**，说明漏洞描述、复现步骤和潜在影响。72 小时内回复。

### 如何添加对新浏览器的支持？

参阅[贡献指南](../dev/contributing.md)。浏览器提取器位于 `src/services/extractors/`。大多数新的 Chromium 分支只需继承 `ChromiumExtractor` 并设置数据目录路径，几行代码即可完成。
