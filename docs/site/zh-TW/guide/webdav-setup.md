---
title: WebDAV 設定
description: HistorySync WebDAV 雲端備份的逐步設定指南 — 涵蓋 Nextcloud、Synology、Alist、Nginx 等。
---

# WebDAV 設定

HistorySync 使用 **WebDAV** 將瀏覽歷史資料庫備份並恢復到雲端。任何相容 WebDAV 的伺服器都可使用，本頁涵蓋最常見的設定方案。

---

## 運作原理

1. HistorySync 將 `history.db`（及選用的網站圖示快取）**壓縮**打包。
2. 使用**原子化串流上傳**將封存檔案上傳到 WebDAV 遠端路徑 — 僅在上傳成功後才替換舊備份。
3. 自動保留最多 `max_backups` 份副本，舊版本自動清理。
4. 恢復時，HistorySync 下載所選備份並與本機資料庫**合併**（或在 `--replace` 模式下取代）。

---

## 快速設定（GUI）

1. 開啟**設定 → WebDAV 雲端備份**。
2. 填寫以下欄位：
   - **URL** — 完整 URL（含路徑），如 `https://cloud.example.com/remote.php/dav/files/alice/`
   - **使用者名稱 / 密碼** — 您的 WebDAV 憑證
   - **遠端路徑** — 備份子資料夾（預設：`HistorySync/`）
   - **最大備份數** — 保留的快照數量（預設：10）
3. 點擊**測試連線**。
4. 啟用**自動備份**並設定間隔。

---

## 快速設定（CLI）

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"
# 如需預先寫入密碼，請在 GUI 中設定，或直接編輯 config.json。
# hsync config 目前不支援 webdav.password 這個鍵。
hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# 測試
hsync -b
```

---

## 各服務商設定指南

### Nextcloud

Nextcloud 的 WebDAV URL 格式：
```
https://<您的Nextcloud網域>/remote.php/dav/files/<使用者名稱>/
```

1. 登入 Nextcloud。
2. 進入**設定 → 安全性 → 設備與工作階段**，建立一個**應用程式密碼**（建議，比使用主密碼更安全）。
3. 在 HistorySync 中使用上述 URL、您的 Nextcloud 使用者名稱和應用程式密碼。
4. 選用：預先建立專用資料夾（如 `HistorySync`），並將 `remote_path` 設定為 `HistorySync/`。

!!! tip "使用 Nextcloud 應用程式密碼"
    應用程式密碼意味著即使憑證外洩，也無法存取您 Nextcloud 帳號中的其他內容。強烈建議使用。

---

### 群暉 Synology DSM

**在 Synology DSM 中啟用 WebDAV：**

1. 開啟**控制台 → 檔案服務 → WebDAV**。
2. 啟用 **WebDAV** 或 **WebDAV HTTPS**（強烈建議使用 HTTPS）。
3. 記下連接埠號（預設：HTTP 5005，HTTPS 5006）。

**HistorySync URL 格式：**
```
https://<群暉IP或QuickConnect位址>:5006/
```

將遠端路徑設定為您有寫入權限的共用資料夾，如 `homes/alice/HistorySync/`。

!!! warning "自我簽署憑證"
    群暉預設使用自我簽署憑證。解決方案：
    - 在 DSM 中安裝 Let's Encrypt 憑證（建議），或
    - 設定 `hsync config set webdav.verify_ssl false`（僅適用於受信任的內部網路）

---

### AList（透過 WebDAV 接入 S3 / OneDrive / Google Drive）

[AList](https://alist.nn.ci/) 是一個開源檔案管理器，可將多種雲端儲存服務公開為 WebDAV。

```
https://<您的AList網域>/dav/
```

使用 AList 的使用者名稱和密碼。將 `remote_path` 設定為已設定的儲存路徑，如 `OneDrive/HistorySync/`。

---

### Nginx WebDAV

自建 Nginx WebDAV 伺服器：

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

HistorySync URL：`https://<您的網域>/dav/`

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

## 疑難排解

### 「連線被拒絕」 / 「逾時」

- 檢查 URL — 確認通訊協定（`https://`）和連接埠正確。
- 驗證伺服器可從您的機器存取：`curl -u user:pass https://your-server/dav/`。

### 「401 未授權」

- 仔細確認使用者名稱和密碼。
- Nextcloud：使用**應用程式密碼**，而非登入密碼。
- 確認帳號對遠端路徑有寫入權限。

### 「SSL: CERTIFICATE_VERIFY_FAILED」

- 伺服器使用了自我簽署或過期憑證。
- 修復憑證，或執行 `hsync config set webdav.verify_ssl false`（僅限受信任內部網路）。

### 備份成功但恢復時顯示無備份

- 檢查 `webdav.remote_path` — 必須與備份時使用的路徑一致。
- 執行 `hsync restore --list` 查看 `hsync` 在伺服器上找到的內容。

---

## 安全注意事項

- WebDAV **憑證使用 HKDF 派生金鑰加密**儲存在磁碟上。詳見[安全架構](../dev/security.md)。
- 始終使用 **HTTPS** — 純 HTTP 會在傳輸過程中暴露您的憑證和歷史資料。
- 在支援的服務商處優先使用應用程式專用密碼，而非主帳號密碼。
- 如果儲存空間有限，將 `max_backups` 設定為較小的值。預設為 **5**。
