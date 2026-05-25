---
title: 安全架构
description: HistorySync 如何保护敏感数据 — HKDF 密钥派生、HKDF-SHA256 密钥流 XOR 加密、OS 密钥链存储与威胁模型。
---

# 安全架构

HistorySync 处理敏感数据 — 浏览历史和 WebDAV 凭证。本页详细说明这些数据的保护方式。

---

## 威胁模型

HistorySync 设计用于防御：

- **凭证窃取** — 恶意进程读取磁盘上的配置文件不应能恢复明文 WebDAV 密码。
- **传输中的数据暴露** — 历史记录的备份和恢复必须使用加密连接。
- **意外数据丢失** — 损坏的配置和失败的上传不得使数据库处于不一致状态。

HistorySync **不防御**：

- 被入侵的操作系统或根级攻击者（可直接访问密钥链）。
- 物理访问攻击（全盘加密超出本应用范围）。
- 能在同一用户会话中执行代码的攻击者。

---

## 安全架构 V2

### 主密钥存储

首次运行时生成一个密码学随机的 **256 位主密钥**，并通过 [`keyring`](https://github.com/jaraco/keyring) 库存储在 **OS 密钥链**中：

| 平台 | 密钥链后端 |
|---|---|
| Windows | Windows 凭据管理器 |
| macOS | macOS 钥匙串 |
| Linux | Secret Service API（GNOME 钥匙环、KWallet 等）|

主密钥永远不直接接触磁盘。所有磁盘持久化数据都使用**派生子密钥**。

---

### 密钥派生（HKDF）

从主密钥出发，HistorySync 使用 [HKDF](https://en.wikipedia.org/wiki/HKDF)（基于 HMAC 的密钥派生函数）为每个用途派生**独立子密钥**：

```
主密钥（256 位）
    │
    ├── HKDF(info="encryption") → 加密子密钥（256 位）
    └── HKDF(info="authentication") → 认证子密钥（256 位）
```

使用独立子密钥意味着即使一个子密钥被破解（如通过密码分析攻击加密算法），也不会危及另一个。

---

### 敏感值加密

WebDAV 密码和其他敏感配置值使用 **HKDF-SHA256 密钥流 XOR** 加密，并通过 **HMAC-SHA256** 进行认证：

```
encrypt(明文, master_key):
    salt       ← 随机 16 字节盐值
    prk        ← HMAC-SHA256(key=salt, data=master_key)          # HKDF-Extract
    enc_key    ← HKDF-Expand(prk, info="historysync-enc-key")
    auth_key   ← HKDF-Expand(prk, info="historysync-auth-key")
    keystream  ← HKDF-Expand(prk, info="historysync-enc-key", length=len(padded_plaintext))
    ciphertext ← padded_plaintext XOR keystream
    tag        ← HMAC-SHA256(key=auth_key, data=salt ‖ ciphertext)
    return base64(0x02 ‖ salt ‖ tag ‖ ciphertext)
```

结果以 Base64 字符串存储在 `config.json` 中。加载时先验证 HMAC 标签，再进行解密。

HMAC-SHA256 提供**认证加密** — 任何对密文的篡改都会导致 HMAC 验证失败并抛出 `DecryptionError`，该错误会被捕获并记录，应用以空密码继续运行，而非崩溃或静默接受损坏值。

---

### 配置文件安全

配置文件（`config.json`）使用**原子化重命名**写入：

1. 数据写入同目录下的临时文件。
2. 调用 `fsync()` 确保刷盘。
3. 临时文件**重命名**覆盖现有配置文件。

这确保配置文件永远不会处于部分写入状态。如果进程在写入过程中被杀死，旧配置完整保留。

如果加载时发现配置文件损坏：
1. 备份到 `config.json.bak`。
2. 替换为全新默认配置。
3. 向用户显示警告对话框。

---

### WebDAV 传输安全

- 所有 WebDAV 连接默认使用 **HTTPS**。
- SSL 证书验证默认**启用**（`webdav.verify_ssl = true`）。
- 对于受信任内网上的自签名证书，可禁用 SSL 验证（`verify_ssl = false`），但对互联网服务器**不推荐**。
- 备份上传使用**原子化流式传输** — 仅在上传成功完成后才替换远程文件。

---

## 主密码（GUI 锁定）

HistorySync 支持可选的**主密码**锁定 GUI，与上述 WebDAV 凭证加密相互独立。

- 密码以 **bcrypt 哈希**存储在 `config.json` 中（`master_password_hash` 字段）。
- bcrypt 哈希是单向的 — 即使 `config.json` 被盗，也无法恢复明文密码。
- 主密码**不**加密历史数据库本身 — 仅用于锁定 GUI。

---

## 隐私功能

| 功能 | 说明 |
|---|---|
| **域名黑名单** | 黑名单中的域名永远不会被导入，已有记录永久删除。 |
| **URL 前缀过滤** | 内部浏览器 URL（`chrome://`、`about:`、`file://` 等）默认过滤。 |
| **软隐藏** | 记录可从主视图隐藏而不删除。 |
| **隐藏记录视图** | 软隐藏记录的独立、受访问控制的视图。 |
| **无头 / Fresh 模式** | `--fresh` 模式使用临时目录 — 不读写真实配置/数据库。适用于隐私敏感的演示或故障排查。 |

---

## 报告安全漏洞

**请勿为安全漏洞开公开 GitHub Issue。**

请发送邮件至 **security@historysync.app**，包含：

- 漏洞描述。
- 复现步骤。
- 潜在影响。

**72 小时内**将收到回复。我们将与你协调修复和负责任披露时间表。
