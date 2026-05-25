---
title: 常見問題
description: HistorySync 常見問題解答 — 安裝、同步、隱私、WebDAV 等。
---

# 常見問題

---

## 一般問題

### HistorySync 會將我的瀏覽資料上傳給第三方嗎？

**不會。** HistorySync 完全以本機為優先。所有歷史資料都儲存在**您自己機器上**的 SQLite 資料庫中。唯一的網路流量是選用的 WebDAV 備份 — 目標是*您自己*控制的伺服器（或自建服務）。HistorySync 永遠不會傳送任何分析資料、遙測資訊或外部請求。

### 支援哪些瀏覽器？

HistorySync 原生支援 **30+ 款瀏覽器**，包括：

**Chromium 系：** Chrome、Edge、Brave、Vivaldi、Arc、Chromium、Opera、Opera GX、Yandex 瀏覽器、百分瀏覽器、Thorium 等。

**Firefox 系：** Firefox、Firefox ESR、LibreWolf、Waterfox、Pale Moon、SeaMonkey、Basilisk。

**Safari：** 僅 macOS。

**國內瀏覽器（Windows/macOS/Linux）：** QQ 瀏覽器、搜狗瀏覽器、UC 瀏覽器、獵豹瀏覽器、傲遊瀏覽器、星願瀏覽器等。

如果您的瀏覽器未在清單中，請使用**設定 → 瀏覽器 → 新增自訂路徑**手動新增，或嘗試智慧掃描功能。

### 可以在多台電腦上使用 HistorySync 嗎？

可以！在每台設備上安裝 HistorySync，設定相同的 WebDAV 伺服器，並啟用自動同步。恢復時（或 HistorySync 自動從雲端合併時），來自所有設備的紀錄將依據瀏覽器類型、URL 和造訪時間戳記**智慧去除重複**。

---

## 同步與擷取

### 瀏覽器開著的時候 HistorySync 也能運作嗎？

可以。HistorySync 使用 **SQLite WAL（預寫日誌）快照** — 它在讀取前先複製 WAL 檔案，因此與正在執行的瀏覽器不會產生任何衝突。您的瀏覽器不會被鎖定或暫停。

### 為什麼同步後有些紀錄缺失？

幾個可能的原因：

- **隱私/無痕瀏覽** — 瀏覽器不會將無痕瀏覽歷史寫入磁碟；HistorySync 無法取得。
- **瀏覽器設定檔被停用** — 檢查**設定 → 瀏覽器**，確認該設定檔未被停用。
- **URL 被過濾** — HistorySync 會自動忽略內部瀏覽器 URL（`chrome://`、`about:`、`file://` 等）以及黑名單中的網域。
- **首次同步為增量模式** — 嘗試**設定 → 維護 → 完全重新同步**，或使用 GUI 啟動入口 `python -m src.main --resync`，重新讀取所有歷史紀錄。

### 什麼是「完全重新同步」？

一般同步是**增量**的 — 只讀取上次同步時間戳記之後的新紀錄。完全重新同步忽略水位線，重新讀取所有瀏覽器的每一筆紀錄，補全 `visit_count` 等可能在早期同步中未擷取的欄位。可隨時安全執行 — 紀錄使用 upsert，不會產生重複。

```bash
# 透過 GUI 啟動入口（不是 hsync CLI）
python -m src.main --resync

# 透過 GUI：設定 → 維護 → 完全重新同步
```

---

## 隱私與安全性

### 我的資料儲存在哪裡？

| 平台 | 預設位置 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

使用 `--config-dir 路徑` 覆寫，或使用 `--portable` 將所有內容儲存在執行檔旁邊。

### WebDAV 憑證如何保護？

憑證**永遠不會明文儲存**。HistorySync 透過系統金鑰鏈（via `keyring`）儲存主金鑰，並使用 HKDF 派生獨立的加密和認證子金鑰。詳見[安全架構](../dev/security.md)。

### 什麼是「軟隱藏」 / 隱藏紀錄？

軟隱藏將某筆紀錄（或某個網域的所有紀錄）標記為隱藏 — 它們從主歷史視圖中消失，但仍保留在資料庫中。可在**歷史 → 顯示隱藏紀錄**中查看。這對於隱藏敏感頁面而不永久刪除非常有用。

### 什麼是網域黑名單？

黑名單中的網域**永遠不會被匯入**，已有的相關紀錄也會被**永久刪除**。以右鍵點擊紀錄 → **封鎖該網域**，或在**設定 → 隱私權 → 網域黑名單**中管理。

---

## WebDAV 與雲端備份

### 哪些 WebDAV 服務商與 HistorySync 相容？

任何標準 WebDAV 伺服器均可。已測試：Nextcloud、Synology DSM、ownCloud、AList、Nginx WebDAV、Apache mod_dav、Caddy WebDAV。詳見 [WebDAV 設定指南](webdav-setup.md)。

### 保留多少份備份？

預設保留 **10 份備份**。每次成功上傳後，舊的備份會自動清理。透過 `hsync config set webdav.max_backups N` 修改。

### 備份失敗提示「連線被拒絕」，我該如何排查？

1. 驗證 WebDAV URL（通訊協定、主機名稱、連接埠、路徑）。
2. 檢查使用者名稱和密碼 — Nextcloud 請使用**應用程式密碼**。
3. 測試連通性：`curl -u user:pass https://your-server/dav/`。
4. 如使用自我簽署憑證，設定 `hsync config set webdav.verify_ssl false`。

---

## 效能

### HistorySync 在百萬筆紀錄下執行緩慢，怎麼解決？

依序嘗試以下步驟：

1. **執行 `hsync db vacuum`** — 回收碎片空間，重新整理查詢最佳化器統計資訊。
2. **執行 `hsync db rebuild-fts`** — 重建全文搜尋索引。
3. 確保資料庫在本機快速 SSD 上，而非網路共享或 USB 設備。
4. 如果使用正規表示式搜尋，考慮改用一般關鍵詞搜尋 — 正規表示式透過 SQL 下推更快，但非常複雜的模式仍可能較慢。

---

## CLI（`hsync`）

### 如何在 Docker 容器 / CI 流水線中使用 `hsync`？

使用 `--headless` 模式避免 GUI 相依：

```bash
python -m src.main --headless --sync --config-dir /data/config
```

或直接使用 `hsync`：

```bash
hsync -s --config-dir /data/config -q
```

如果 Qt 報錯提示沒有顯示器，設定 `QT_QPA_PLATFORM=offscreen`。

---

## 貢獻與開發

### 如何回報錯誤（Bug）？

使用 **[GitHub 錯誤回報範本](https://github.com/TheSkyC/HistorySync/issues/new?template=bug_report.yml)**。請包含您的作業系統、HistorySync 版本、涉及的瀏覽器及重現步驟。

### 我發現了安全性漏洞，該怎麼做？

**請勿開公開 Issue。** 請直接寄信至 **security@historysync.app**，說明漏洞描述、重現步驟和潛在影響。72 小時內回覆。

### 如何新增對新瀏覽器的支援？

參閱[貢獻指南](../dev/contributing.md)。瀏覽器擷取器位於 `src/services/extractors/`。大多數新的 Chromium 分支只需繼承 `ChromiumExtractor` 並設定資料目錄路徑，幾行程式碼即可完成。
