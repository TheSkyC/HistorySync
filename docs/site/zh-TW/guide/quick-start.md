---
title: 快速上手
description: 五分鐘內完成 HistorySync 設定 — 自動背景同步、雲端備份與 Spotlight 速查。
---

# 快速上手

本指南幫助您在 **5 分鐘內** 完成設定，實現全自動的瀏覽器歷史紀錄備份。

---

## 第一步 — 首次啟動

啟動 HistorySync。首次執行時，**安裝精靈**將引導您完成基本設定。

如果從原始碼執行：
```bash
python -m src.main
```

---

## 第二步 — 同步瀏覽器

在**儀表板**中，點擊**立即同步**。HistorySync 將：

1. 自動偵測系統上已安裝的所有瀏覽器。
2. 使用 WAL 快照安全讀取 SQLite 歷史資料庫 — 瀏覽器可保持執行狀態。
3. 將紀錄匯入 HistorySync 本機資料庫。

!!! tip "首次同步耗時較長"
    如果您有跨多個瀏覽器的多年歷史資料，首次同步可能需要一兩分鐘。後續同步為**增量**模式 — 僅匯入新紀錄。

### 選擇性同步

只同步特定瀏覽器，使用 CLI：
```bash
hsync -s --browsers chrome,firefox
```

---

## 第三步 — 搜尋歷史紀錄

### GUI 搜尋
在**歷史**標籤頁頂部的搜尋列中輸入關鍵詞，結果即時呈現。

### 全域懸浮視窗（Spotlight 風格）
在**任意應用程式**中按下 <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> 即可喚出速查懸浮視窗，支援 Windows、macOS 和 Linux（X11）。Wayland 環境下請將 `python -m src.main --quick` 綁定到系統級快捷鍵代替。

自然輸入，或使用[進階查詢語法](cli-reference.md#query-dsl)：

| 範例查詢 | 搜尋內容 |
|---|---|
| `python async` | 標題或 URL 中含這些詞的頁面 |
| `domain:github.com` | 僅 GitHub 頁面 |
| `after:2024-06-01 domain:arxiv.org` | 2024年6月後瀏覽的論文 |
| `is:bookmarked tag:work` | 標記為「work」的已收藏頁面 |
| `react -tutorial` | React 相關頁面，排除教學 |

---

## 第四步 — 開啟自動同步

進入**設定 → 自動同步**：

1. 啟用**自動同步**。
2. 設定偏好的間隔（預設：2 小時）。
3. 啟用**開機啟動**，讓 HistorySync 以背景靜默模式隨系統啟動。

從此，瀏覽器歷史紀錄將持續自動聚合到同一個可搜尋的資料庫中。

---

## 第五步 — 設定雲端備份（選用）

WebDAV 備份讓您能在新設備上恢復歷史紀錄，或跨設備共享資料。

1. 進入**設定 → WebDAV 雲端備份**。
2. 填寫 WebDAV 伺服器 URL、使用者名稱和密碼。
3. 啟用**自動備份**並設定間隔。
4. 點擊**測試連線**驗證設定。

主流服務商的詳細設定步驟請參閱 [WebDAV 設定指南](webdav-setup.md)。

---

## 第六步 — 開啟更新檢查

進入 **設定 → 更新**，決定你希望 HistorySync 如何處理新版本：

1. 保持 **自動檢查更新** 開啟，以便在背景發現新版本。
2. 選擇發布通道，例如 **Stable** 或 **Beta**。
3. 設定提醒策略，例如「每週最多提醒一次」，避免過於頻繁。
4. 隨時點擊 **檢查更新** 執行手動檢查。

偵測到新版本後，HistorySync 可以顯示更新橫幅、開啟版本詳情對話框，並記住「稍後提醒」或「跳過此版本」的決定。

---

## 第七步 — 系統匣模式（背景執行）

設定完成後，關閉主視窗。HistorySync 將最小化到**系統匣**，繼續靜默同步和備份。

以右鍵點擊系統匣圖示可以：

- **開啟 HistorySync** — 恢復主視窗。
- **立即同步** — 觸發即時同步。
- **立即備份** — 觸發即時 WebDAV 備份。
- **結束** — 完全停止應用程式。

---

## 後續步驟

| 目標 | 文件 |
|---|---|
| 從終端機自動化同步 | [CLI 命令參考](cli-reference.md) |
| 從終端機檢查新版本 | [CLI 命令參考](cli-reference.md#update-check-for-updates) |
| 設定特定 WebDAV 服務商 | [WebDAV 設定](webdav-setup.md) |
| 自訂鍵盤快捷鍵 | [鍵盤快捷鍵](keyboard-shortcuts.md) |
| 匯出歷史紀錄為 CSV / JSON / HTML | [CLI 參考 — 匯出歷史紀錄](cli-reference.md#export) |
| 了解安全架構 | [安全架構](../dev/security.md) |
