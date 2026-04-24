<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center">
  <a href="../README.md">English</a> | 
  <a href="./README.zh-CN.md">简体中文</a> | 
  繁體中文 | 
  <a href="./README.ja.md">日本語</a> | 
  <a href="./README.ko.md">한국어</a> | 
  <a href="./README.ru.md">Русский</a> | 
  <a href="./README.fr.md">Français</a>
<br></p>

# HistorySync
**HistorySync** 是一款功能強大的跨平台桌面應用程式。它提供了一套完整、高效的瀏覽器歷史紀錄統一管理與雲端備份解決方案，從多瀏覽器資料彙整，到毫秒級全文檢索，再到 WebDAV 自動化備份與豐富統計，讓您徹底掌控自己的瀏覽資料。

本工具完全相容 Chromium 系、Firefox 系以及 Safari 瀏覽器的底層資料庫，並提供極佳的隱私保護和在地化管理體驗。

---

## 📥 下載
您可以從 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 頁面下載最新版本。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 核心特性

### 📂 全能的資料彙整 (支援 30+ 瀏覽器)
*   **海量瀏覽器支援**：原生支援 Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc 以及眾多區域/客製化瀏覽器（QQ、搜狗、星願、百分、獵豹等）。
*   **智慧增量提取**：基於底層 SQLite WAL 機制的安全快照讀取，支援增量提取，即使瀏覽器正在執行也能無損獲取最新紀錄。
*   **游離資料庫匯入**：支援手動匯入獨立的 `History` 或 `places.sqlite` 檔案，輕鬆合併舊電腦或免安裝版瀏覽器的資料。

### 🔍 Spotlight 風格速查與知識庫
*   **全域速查懸浮窗**：無論在任何軟體中，按下 `Ctrl+Shift+H` 即可喚出極簡搜尋框，瞬間檢索歷史並打開網頁。
*   **全新快捷鍵引擎**：基於 `pynput` 的跨平台快捷鍵系統，提供 14 個可高度自訂的全域與應用程式內快捷鍵。
*   **進階查詢語法**：支援類似搜尋引擎的語法（如 `domain:github.com`, `after:2024-01-01`），並帶有模糊比對的下拉提示與內聯文字補全。
*   **書籤與批註**：為重要網頁添加標籤（Tags）和富文本批註（Notes），將其轉化為個人知識庫。

### ⚡ 極致效能與現代化 UI
*   **百萬級資料流暢捲動**：底層重寫分頁邏輯，引入兩步分頁與 Keyset 索引，並將正規表示式搜尋下推至 SQL 層，徹底消除海量資料下快速捲動時的卡頓。
*   **自適應介面**：引入比例欄寬分配機制，視窗縮放平滑自然；完美支援系統明暗主題的即時無縫切換。
*   **豐富的資料視覺化**：透過 GitHub 風格的年度活躍度熱力圖、瀏覽器市占率圓餅圖、24小時活躍度長條圖，直觀了解數位生活軌跡，並支援一鍵匯出為高畫質長圖。

### ☁️ 雲端同步與自動化
*   **WebDAV 備份與合併**：採用**原子化串流上傳**。從雲端還原時，系統會智慧合併跨裝置的紀錄。
*   **無頭命令列 (`hsync`)**：專為極客打造的 CLI 工具。支援無頭環境下的資料提取、備份與匯出，背景常駐記憶體極低。
*   **背景靜默排程**：支援開機自動啟動並最小化到系統匣，在背景自動完成提取與雲端備份。

### 🛡️ 極致的隱私與掌控
*   **隱藏模式與軟隱藏**：新增專屬的「隱藏紀錄」檢視，支援對特定網域進行軟隱藏（紀錄保留在資料庫中但從主視圖消失）。
*   **安全架構 V2**：使用獨立的 HKDF 加密與認證子金鑰保護 WebDAV 憑證等敏感設定。
*   **網域黑名單與 URL 過濾**：一鍵封鎖特定網域，不僅立即刪除相關紀錄，未來的同步也會自動將其過濾。

## 📸 截圖

*資料儀表板概覽*

<img width="1000" alt="Dashboard" src="assets/ui-dashboard.png" />

<details>
<summary><b>► 點擊查看更多截圖</b></summary>

*視覺化統計與熱力圖*

<img width="1000" alt="Statistics" src="assets/ui-stats.png" />

*歷史紀錄檢索與管理*

<img width="1000" alt="History" src="assets/ui-history.png" />

</details>

## 🛠️ 開發環境設定

### 前提條件
*   Python 3.10 或更高版本
*   Git (可選，用於複製儲存庫)

### 步驟
1.  **複製儲存庫 (或下載 ZIP)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **建立並啟動虛擬環境 (推薦)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **安裝相依套件**
    ```bash
    pip install -r requirements.txt
    ```

4.  **執行**
    ```bash
    python -m src.main
    ```

## 🚀 快速上手

HistorySync 提供靈活的工作模式，您可以把它當作一個背景服務，也可以當作一個主動管理工具：

### 1. 🔄 背景靜默模式 (推薦)
*適用於希望「設定一次，永遠忘記」，讓資料自動備份的使用者。*
1.  **設定啟動**: 進入 `設定 > 開機啟動`，勾選「開機自動啟動」。
2.  **設定定時**: 在 `自動同步` 中設定自動提取的間隔。
3.  **設定雲端硬碟**: 在 `WebDAV 雲端備份` 中填入您的 WebDAV 帳號，並開啟自動備份。
4.  **背景執行**: 關閉主視窗，程式將最小化到系統匣，在背景默默守護您的瀏覽資料。

### 2. 🔍 主動管理模式
*適用於需要經常尋找歷史紀錄、做筆記、清理隱私資料的使用者。*
1.  **全域速查**: 隨時隨地按下 `Ctrl+Shift+H` 喚出懸浮窗尋找歷史。
2.  **知識沉澱**: 為有價值的網頁添加書籤和批註，方便日後回顧。
3.  **隱私清理**: 選中不想保留的紀錄，右鍵選擇「刪除」；或者直接選擇「封鎖該網域」，一勞永逸地清理特定網站的痕跡。

## 🌐 支援的語言
本工具支援以下語言的 UI 介面：
*   **English** (`en_US`)
*   **简体中文** (`zh_CN`)
*   **繁體中文** (`zh_TW`)
*   **日本語** (`ja_JP`)
*   **한국어** (`ko_KR`)
*   **Français** (`fr_FR`)
*   **Deutsch** (`de_DE`)
*   **Русский** (`ru_RU`)
*   **Español** (`es_ES`)
*   **Italiano** (`it_IT`)

## 🤝 貢獻
歡迎任何形式的貢獻。請先閱讀 [CONTRIBUTING.md](../CONTRIBUTING.md) 了解開發環境、程式碼規範與 DCO 簽署要求。提交 Bug、功能建議或使用問題時，請優先使用 GitHub 提供的 issue 範本。

## 📄 授權條款
專案基於 [Apache 2.0](../LICENSE) 開源，允許自由使用、修改和分發，但需保留版權聲明。

## 📞 聯絡方式
- 作者：骰子掷上帝 (TheSkyC)
- 信箱：0x4fe6@gmail.com