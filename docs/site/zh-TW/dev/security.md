---
title: 安全架構
description: HistorySync 如何保護敏感資料 — HKDF 金鑰派生、HKDF-SHA256 金鑰流 XOR 加密、作業系統金鑰鏈儲存與威脅模型。
---

# 安全架構

HistorySync 處理敏感資料 — 瀏覽歷史紀錄和 WebDAV 憑證。本頁詳細說明這些資料的保護方式。

---

## 威脅模型

HistorySync 設計用於防禦：

- **憑證竊取** — 惡意程序讀取磁碟上的設定檔不應能恢復明文 WebDAV 密碼。
- **傳輸中的資料暴露** — 歷史紀錄的備份和恢復必須使用加密連線。
- **意外資料遺失** — 損毀的設定和失敗的上傳不得使資料庫處於不一致狀態。

HistorySync **不防禦**：

- 遭入侵的作業系統或根級攻擊者（可直接存取金鑰鏈）。
- 實體存取攻擊（全磁碟加密超出本應用程式範疇）。
- 能在同一使用者工作階段中執行程式碼的攻擊者。

---

## 安全架構 V2

### 主金鑰儲存

首次執行時產生一個密碼學隨機的 **256 位元主金鑰**，並透過 [`keyring`](https://github.com/jaraco/keyring) 函式庫儲存在 **作業系統金鑰鏈**中：

| 平台 | 金鑰鏈後端 |
|---|---|
| Windows | Windows 認證管理員 |
| macOS | macOS 鑰匙圈 |
| Linux | Secret Service API（GNOME 金鑰圈、KWallet 等）|

主金鑰永遠不直接接觸磁碟。所有磁碟持久化資料都使用**派生子金鑰**。

---

### 金鑰派生（HKDF）

從主金鑰出發，HistorySync 使用 [HKDF](https://en.wikipedia.org/wiki/HKDF)（基於 HMAC 的金鑰派生函數）為每個用途派生**獨立子金鑰**：

```
主金鑰（256 位元）
    │
    ├── HKDF(info="encryption") → 加密子金鑰（256 位元）
    └── HKDF(info="authentication") → 認證子金鑰（256 位元）
```

使用獨立子金鑰意味著即使一個子金鑰被破解（如透過密碼分析攻擊加密演算法），也不會危及另一個。

---

### 敏感值加密

WebDAV 密碼和其他敏感設定值使用 **HKDF-SHA256 金鑰流 XOR** 加密，並透過 **HMAC-SHA256** 進行認證：

```
encrypt(明文, master_key):
    salt       ← 隨機 16 位元組鹽值
    prk        ← HMAC-SHA256(key=salt, data=master_key)          # HKDF-Extract
    enc_key    ← HKDF-Expand(prk, info="historysync-enc-key")
    auth_key   ← HKDF-Expand(prk, info="historysync-auth-key")
    keystream  ← HKDF-Expand(prk, info="historysync-enc-key", length=len(padded_plaintext))
    ciphertext ← padded_plaintext XOR keystream
    tag        ← HMAC-SHA256(key=auth_key, data=salt ‖ ciphertext)
    return base64(0x02 ‖ salt ‖ tag ‖ ciphertext)
```

結果以 Base64 字串儲存在 `config.json` 中。載入時先驗證 HMAC 標籤，再進行解密。

HMAC-SHA256 提供**認證加密** — 任何對密文的竄改都會導致 HMAC 驗證失敗並擲出 `DecryptionError`，該錯誤會被捕捉並記錄，應用程式以空密碼繼續執行，而非崩潰或靜默接受損毀值。

---

### 設定檔安全性

設定檔（`config.json`）使用**原子化重新命名**寫入：

1. 資料寫入同目錄下的暫存檔案。
2. 呼叫 `fsync()` 確保寫入磁碟。
3. 暫存檔案**重新命名**覆蓋現有設定檔。

這確保設定檔永遠不會處於部分寫入狀態。如果程序在寫入過程中被終止，舊設定完整保留。

如果載入時發現設定檔損毀：
1. 備份到 `config.json.bak`。
2. 替換為全新預設設定。
3. 向使用者顯示警告對話框。

---

### WebDAV 傳輸安全性

- 所有 WebDAV 連線預設使用 **HTTPS**。
- SSL 憑證驗證預設**啟用**（`webdav.verify_ssl = true`）。
- 對於受信任內部網路上的自我簽署憑證，可停用 SSL 驗證（`verify_ssl = false`），但對網際網路伺服器**不建議**。
- 備份上傳使用**原子化串流傳輸** — 僅在上傳成功完成後才替換遠端檔案。

---

## 主密碼（GUI 鎖定）

HistorySync 支援選用的**主密碼**鎖定 GUI，與上述 WebDAV 憑證加密相互獨立。

- 密碼以 **bcrypt 雜湊**儲存在 `config.json` 中（`master_password_hash` 欄位）。
- bcrypt 雜湊是單向的 — 即使 `config.json` 遭竊，也無法恢復明文密碼。
- 主密碼**不**加密歷史資料庫本身 — 僅用於鎖定 GUI。

---

## 隱私功能

| 功能 | 說明 |
|---|---|
| **網域黑名單** | 黑名單中的網域永遠不會被匯入，已有紀錄永久刪除。 |
| **URL 前置詞過濾** | 內部瀏覽器 URL（`chrome://`、`about:`、`file://` 等）預設過濾。 |
| **軟隱藏** | 紀錄可從主視圖隱藏而不刪除。 |
| **隱藏紀錄視圖** | 軟隱藏紀錄的獨立、受存取控制的視圖。 |
| **無頭 / Fresh 模式** | `--fresh` 模式使用暫存目錄 — 不讀寫真實設定/資料庫。適用於隱私敏感的示範或疑難排解。 |

---

## 回報安全性漏洞

**請勿為安全性漏洞開公開 GitHub Issue。**

請寄信至 **security@historysync.app**，包含：

- 漏洞描述。
- 重現步驟。
- 潛在影響。

**72 小時內**將收到回覆。我們將與您協調修復和負責任揭露時程表。
