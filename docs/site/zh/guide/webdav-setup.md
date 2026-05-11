---
title: WebDAV 配置
description: HistorySync WebDAV 云端备份的分步配置指南 — 涵盖 Nextcloud、Synology、Alist、Nginx 等。
---

# WebDAV 配置

HistorySync 使用 **WebDAV** 将浏览历史数据库备份并恢复到云端。任何兼容 WebDAV 的服务器都可使用，本页涵盖最常见的配置方案。

---

## 工作原理

1. HistorySync 将 `history.db`（及可选的网站图标缓存）**压缩**打包。
2. 使用**原子化流式上传**将归档文件上传到 WebDAV 远程路径 — 仅在上传成功后才替换旧备份。
3. 自动保留最多 `max_backups` 份副本，旧版本自动清理。
4. 恢复时，HistorySync 下载所选备份并与本地数据库**合并**（或在 `--replace` 模式下替换）。

---

## 快速配置（GUI）

1. 打开**设置 → WebDAV 云端备份**。
2. 填写以下字段：
   - **URL** — 完整 URL（含路径），如 `https://cloud.example.com/remote.php/dav/files/alice/`
   - **用户名 / 密码** — 你的 WebDAV 凭证
   - **远程路径** — 备份子文件夹（默认：`HistorySync/`）
   - **最大备份数** — 保留的快照数量（默认：10）
3. 点击**测试连接**。
4. 启用**自动备份**并设置间隔。

---

## 快速配置（CLI）

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"
# 如需预先写入密码，请在 GUI 中设置，或直接编辑 config.json。
# hsync config 当前不暴露 webdav.password 这个键。
hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# 测试
hsync -b
```

---

## 各服务商配置指南

### Nextcloud

Nextcloud 的 WebDAV URL 格式：
```
https://<你的Nextcloud域名>/remote.php/dav/files/<用户名>/
```

1. 登录 Nextcloud。
2. 进入**设置 → 安全 → 设备与会话**，创建一个**应用密码**（推荐，比使用主密码更安全）。
3. 在 HistorySync 中使用上述 URL、你的 Nextcloud 用户名和应用密码。
4. 可选：预先创建专用文件夹（如 `HistorySync`），并将 `remote_path` 设置为 `HistorySync/`。

!!! tip "使用 Nextcloud 应用密码"
    应用密码意味着即使凭证泄露，也无法访问你 Nextcloud 账户中的其他内容。强烈推荐。

---

### 群晖 Synology DSM

**在 Synology DSM 中启用 WebDAV：**

1. 打开**控制面板 → 文件服务 → WebDAV**。
2. 启用 **WebDAV** 或 **WebDAV HTTPS**（强烈推荐使用 HTTPS）。
3. 记录端口号（默认：HTTP 5005，HTTPS 5006）。

**HistorySync URL 格式：**
```
https://<群晖IP或QuickConnect地址>:5006/
```

将远程路径设置为你有写入权限的共享文件夹，如 `homes/alice/HistorySync/`。

!!! warning "自签名证书"
    群晖默认使用自签名证书。解决方案：
    - 在 DSM 中安装 Let's Encrypt 证书（推荐），或
    - 设置 `hsync config set webdav.verify_ssl false`（仅适用于受信任的内网）

---

### AList（通过 WebDAV 接入 S3 / OneDrive / Google Drive）

[AList](https://alist.nn.ci/) 是一个开源文件管理器，可将多种云存储服务暴露为 WebDAV。

```
https://<你的AList域名>/dav/
```

使用 AList 的用户名和密码。将 `remote_path` 设置为配置的存储路径，如 `OneDrive/HistorySync/`。

---

### Nginx WebDAV

自建 Nginx WebDAV 服务器：

```nginx
location /dav/ {
    root /var/webdav;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_ext_methods PROPFIND OPTIONS;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
    auth_basic "WebDAV";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

HistorySync URL：`https://<你的域名>/dav/`

---

### Apache WebDAV

```apache
<Location /dav>
    DAV On
    AuthType Basic
    AuthName "WebDAV"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user
</Location>
```

---

## 故障排除

### "连接被拒绝" / "超时"

- 检查 URL — 确认协议（`https://`）和端口正确。
- 验证服务器可从你的机器访问：`curl -u user:pass https://your-server/dav/`。

### "401 未授权"

- 仔细检查用户名和密码。
- Nextcloud：使用**应用密码**，而非登录密码。
- 确认账户对远程路径有写入权限。

### "SSL: CERTIFICATE_VERIFY_FAILED"

- 服务器使用了自签名或过期证书。
- 修复证书，或执行 `hsync config set webdav.verify_ssl false`（仅限受信任内网）。

### 备份成功但恢复时显示无备份

- 检查 `webdav.remote_path` — 必须与备份时使用的路径一致。
- 运行 `hsync restore --list` 查看 `hsync` 在服务器上找到的内容。

---

## 安全注意事项

- WebDAV **凭证使用 HKDF 派生密钥加密**存储在磁盘上。详见[安全架构](../dev/security.md)。
- 始终使用 **HTTPS** — 纯 HTTP 会在传输过程中暴露你的凭证和历史数据。
- 在支持的服务商处优先使用应用专用密码，而非主账户密码。
- 如果存储空间有限，将 `max_backups` 设置为较小的值。默认为 **5**。
