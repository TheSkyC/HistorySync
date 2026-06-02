---
title: CLI 命令參考
description: hsync 命令列工具完整參考 — 所有旗標、子命令與進階查詢語法。
---

# CLI 命令參考 — `hsync`

`hsync` 是 HistorySync 的**無頭 CLI 工具**。它無需 GUI 即可使用應用程式的全部功能，非常適合定時任務、腳本和 CI 環境。

---

## 全域選項

這些選項適用於所有命令和子命令。

| 旗標 | 簡寫 | 說明 |
|---|---|---|
| `--version` | | 印出版本號並結束 |
| `--config-dir PATH` | | 使用自訂設定/資料目錄 |
| `--portable` | | 將所有資料儲存在 `hsync` 執行檔旁邊 |
| `--verbose` | `-v` | 啟用除錯級別日誌 |
| `--quiet` | `-q` | 抑制進度輸出，僅將錯誤印出到 stderr |
| `--no-color` | | 停用 ANSI 顏色（也可透過 `NO_COLOR` 環境變數設定）|
| `--dry-run` | | 探測/驗證，不寫入任何內容到磁碟或網路 |

---

## 經典操作旗標

透過旗標執行快捷操作（無需子命令）。

### `-s` / `--sync` — 擷取瀏覽器歷史紀錄

將瀏覽器歷史紀錄匯入本機資料庫。

```bash
hsync -s
hsync --sync

# 僅同步特定瀏覽器
hsync -s --browsers chrome,firefox

# 每 30 分鐘同步一次（監聽模式）
hsync -s -w 30
```

**同步選項：**

| 旗標 | 說明 |
|---|---|
| `--browsers LIST` | 以逗號分隔的瀏覽器類型（預設：所有已偵測到的瀏覽器），例如 `chrome,firefox,edge` |
| `-w 分鐘數` / `--watch 分鐘數` | 每隔指定分鐘數重複同步。按 <kbd>Ctrl</kbd>+<kbd>C</kbd> 停止。 |

### `-b` / `--backup` — WebDAV 備份

將本機資料庫的壓縮快照上傳到 WebDAV。

```bash
hsync -b
hsync --backup

# 同步後立即備份
hsync -sb
```

!!! note "需要先設定 WebDAV"
    使用 `--backup` 前，請先執行 `hsync config set webdav.enabled true` 並設定 URL、使用者名稱和密碼。

<a id="export"></a>

### `-e 檔案` / `--export 檔案` — 匯出歷史紀錄

將瀏覽歷史紀錄匯出到檔案，格式依副檔名自動推斷。

```bash
# 匯出為 CSV
hsync -e history.csv

# 帶過濾器匯出為 JSON
hsync -e history.json --keyword python --after 2024-01-01

# 帶嵌入圖示的 HTML 報告
hsync -e report.html --format html --embed-icons

# 依網域過濾
hsync -e out.csv --domain github.com --domain stackoverflow.com

# 自訂欄位
hsync -e out.csv --columns title,url,visit_time,browser_type

# 正規表示式關鍵詞過濾
hsync -e out.json --keyword "^https://github" --regex

# 日期範圍
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**匯出選項：**

| 旗標 | 說明 |
|---|---|
| `--format 格式` | `csv` \| `json` \| `html`（預設：依副檔名推斷）|
| `--columns 欄位名` | 以逗號分隔的欄位名。可用欄位：`id`、`title`、`url`、`visit_time`、`visit_count`、`browser_type`、`profile_name`、`domain`、`metadata`、`typed_count`、`first_visit_time`、`transition_type`、`visit_duration` |
| `--embed-icons` | 將網站圖示嵌入為 Base64 data-URI（僅 HTML 匯出）|
| `--keyword 文字` | 全文關鍵詞過濾 |
| `--regex` | 將 `--keyword` 視為 Python 正規表示式 |
| `--browser 類型` | 依瀏覽器類型過濾（如 `chrome`、`firefox`、`edge`）|
| `--after 日期` | 包含該日期及之後的紀錄（`YYYY-MM-DD`）|
| `--before 日期` | 包含該日期及之前的紀錄（`YYYY-MM-DD`）|
| `--domain 網域` | 限制到指定網域，可重複：`--domain a.com --domain b.com` |

### `-S` / `--status` — 資料庫統計

印出資料庫統計資訊。

```bash
hsync -S
hsync --status

# 機器可讀的 JSON 格式
hsync -S --json

# 腳本友善的單行輸出
hsync -S -q
```

### `-i` / `--interactive` — 互動式選單

啟動互動式終端機選單，非常適合初次使用。

```bash
hsync -i
hsync --interactive
```

---

## 子命令

### `search` — 搜尋歷史紀錄

使用結構化查詢語法搜尋歷史紀錄。

```bash
# 瀏覽最近 20 筆紀錄
hsync search

# 瀏覽最近 100 筆
hsync search --limit 100

# 簡單關鍵詞搜尋
hsync search python

# 互動模式（支援鍵盤導覽）
hsync search -i

# 結構化查詢
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**選項：**

| 旗標 | 預設值 | 說明 |
|---|---|---|
| `--limit N` | `20` | 最大結果數 |
| `--format 格式` | `table` | 輸出格式：`table` \| `json` \| `tsv` \| `csv` |
| `--columns 欄位名` | `title,url,visit_time,browser_type` | 顯示的欄位 |
| `--open` | | 在預設瀏覽器中開啟第一筆結果 |
| `-i` / `--interactive` | | 帶鍵盤導覽的互動模式 |

---

<a id="query-dsl"></a>

### 查詢語法

搜尋子命令和 GUI 搜尋列都支援豐富的查詢語言。

#### 關鍵詞搜尋

一般詞語在標題和 URL 中搜尋：
```
python async
"精確短語"
react -tutorial         # 排除某個詞
```

#### 語彙過濾器

| 語彙 | 範例 | 說明 |
|---|---|---|
| `domain:` | `domain:github.com` | 依網域過濾 |
| `title:` | `title:python` | 僅在頁面標題中搜尋 |
| `url:` | `url:github` | 僅在 URL 中搜尋 |
| `after:` | `after:2024-01-01` | 日期範圍起始（含）|
| `before:` | `before:2024-12-31` | 日期範圍結束（含）|
| `browser:` | `browser:chrome` | 依瀏覽器類型過濾 |
| `device:` | `device:laptop` | 依設備名稱或 UUID 過濾 |
| `is:bookmarked` | `is:bookmarked` | 僅已收藏的紀錄 |
| `has:note` | `has:note` | 僅有批註的紀錄 |
| `tag:` | `tag:work` | 依書籤標籤過濾 |

#### 組合查詢

語彙和關鍵詞可自由組合：
```
domain:arxiv.org after:2024-01-01 深度學習
is:bookmarked tag:工作 專案管理
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — 從 WebDAV 恢復

從 WebDAV 備份恢復資料庫。

```bash
# 列出備份並互動選擇
hsync restore

# 自動恢復最新備份（合併模式）
hsync restore --latest

# 以 JSON 格式列出可用備份
hsync restore --list

# 取代模式：完全覆蓋本機資料庫
hsync restore --replace

# 同時恢復網站圖示快取
hsync restore --latest --restore-favicons
```

!!! info "合併 vs 取代"
    預設行為將備份紀錄與本機資料庫**合併** — 兩端的紀錄都保留並去除重複。僅當需要完全用備份覆蓋本機資料時，才使用 `--replace`。

---

### `db` — 資料庫維護

```bash
# VACUUM + ANALYZE（回收碎片空間）
hsync db vacuum

# 重建全文搜尋索引
hsync db rebuild-fts

# 正規化所有紀錄中的網域
hsync db normalize

# 顯示資料庫統計
hsync db stats
hsync db stats --json
```

| 子命令 | 說明 |
|---|---|
| `vacuum` | 執行 `VACUUM` 和 `ANALYZE` — 回收碎片空間，更新查詢最佳化器統計資訊 |
| `rebuild-fts` | 重建 FTS5 全文搜尋索引 — 當搜尋緩慢或結果缺失時使用 |
| `normalize` | 重新計算所有紀錄的網域（匯入原始資料庫後很有用）|
| `stats` | `hsync -S` 的別名 |

---

### `config` — 管理設定

無需開啟 GUI 即可讀寫設定。

```bash
# 列出所有鍵及其目前值
hsync config list

# 讀取單一值
hsync config get webdav.url

# 寫入值
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language zh_TW
```

**可設定的設定鍵：**

| 鍵 | 類型 | 說明 |
|---|---|---|
| `webdav.enabled` | bool | 啟用 WebDAV 備份 |
| `webdav.url` | string | WebDAV 伺服器 URL |
| `webdav.username` | string | WebDAV 使用者名稱 |
| `webdav.remote_path` | string | 備份遠端路徑（預設：`/HistorySync/`）|
| `webdav.max_backups` | int | 保留備份數量（預設：`10`）|
| `webdav.verify_ssl` | bool | 驗證 SSL 憑證（預設：`true`）|
| `webdav.auto_backup` | bool | 啟用定期自動備份 |
| `webdav.backup_favicons` | bool | 備份時包含網站圖示快取 |
| `scheduler.auto_sync_enabled` | bool | 啟用自動瀏覽器同步 |
| `scheduler.sync_interval_hours` | int | 同步間隔（小時）|
| `scheduler.auto_backup_enabled` | bool | 啟用定期 WebDAV 備份 |
| `scheduler.auto_backup_interval_hours` | int | 備份間隔（小時）|
| `scheduler.launch_on_startup` | bool | 登入時啟動 HistorySync |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | UI 語言代碼（如 `zh_TW`），留空則自動偵測 |

---

<a id="update-check-for-updates"></a>

### `update` — 檢查更新

檢查目前平台與安裝形態是否有可用的新版本 HistorySync。

```bash
# 人類可讀輸出
hsync update

# 機器可讀 JSON 輸出
hsync update --json

# 檢查非預設發布通道
hsync update --channel beta
hsync update --channel nightly
```

**選項：**

| 旗標 | 說明 |
|---|---|
| `--json` | 以 JSON 輸出更新中繼資料，方便腳本與 CI 使用 |
| `--channel CH` | 臨時覆寫本次檢查使用的通道：`stable` \| `beta` \| `nightly` |

**行為說明：**

- 使用與桌面版相同、依平台選擇的更新中繼資料。
- 當主要更新 API 無法使用時，會回退到 GitHub Releases 中繼資料。
- 會依目前安裝形態選擇對應產物，例如 installer、portable ZIP、AppImage 或 `.dmg`。

!!! note "CLI 只負責檢查"
    `hsync update` 負責回報是否有可用更新與相關中繼資料。真正的引導下載與安裝流程位於桌面版的 **設定 → 更新** 中。

---

## Shell 自動補全

`hsync` 透過 `argcomplete` 支援 Shell 自動補全。

=== "Bash"
    ```bash
    # 一次性全域設定
    activate-global-python-argcomplete --user

    # 或新增到 ~/.bashrc：
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # 新增到 ~/.zshrc：
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## 腳本與 CI 範例

```bash
# 同步並檢查結果
hsync -s -q && echo "同步成功" || echo "同步失敗"

# 將狀態 JSON 管道到 jq
hsync -S --json | jq .record_count

# 日誌寫入檔案
hsync -s --no-color 2>&1 | tee sync.log

# 定時同步 + 備份（cron 友善）
hsync -sb -q

# 匯出上週的 GitHub 頁面為 JSON
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"
```

---

## 結束碼

| 碼 | 含義 |
|---|---|
| `0` | 成功 |
| `1` | 錯誤（詳情印出到 stderr）|
