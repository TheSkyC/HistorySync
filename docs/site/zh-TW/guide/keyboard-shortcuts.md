---
title: 鍵盤快捷鍵
description: HistorySync 全部 25 個可設定鍵盤快捷鍵 — 1 個全域熱鍵與 24 個應用程式內綁定。
---

# 鍵盤快捷鍵

HistorySync 提供 **25 個可設定的快捷鍵** — 1 個全域熱鍵和 24 個應用程式內綁定。所有快捷鍵均可在**設定 → 鍵盤快捷鍵**中修改。

---

## 全域熱鍵

此快捷鍵在系統範圍內有效 — 即使 HistorySync 在背景執行或最小化到系統匣，也能觸發。

| 操作 | 預設 | 說明 |
|---|---|---|
| **開啟速查懸浮視窗** | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | 喚出 / 隱藏 Spotlight 風格的搜尋懸浮視窗 |

!!! info "Linux / Wayland"
    `pynput` 的全域熱鍵**不支援 Wayland**。可使用 `--quick` 搭配桌面環境的系統級快捷鍵繫結作為替代：
    ```bash
    # 在 DE 設定中將此命令繫結到系統快捷鍵
    python -m src.main --quick
    ```

!!! info "macOS"
    全域熱鍵首次觸發時，macOS 會要求**輔助使用**權限。請在**系統設定 → 隱私權與安全性 → 輔助使用**中授權。

---

## 應用程式內快捷鍵

這些快捷鍵在 HistorySync 視窗獲得焦點時有效。

### 目前預設值

| 分類 | 預設快捷鍵 |
|---|---|
| **頁面導覽** | 儀表板 <kbd>Ctrl</kbd>+<kbd>1</kbd>、歷史 <kbd>Ctrl</kbd>+<kbd>2</kbd>、書籤 <kbd>Ctrl</kbd>+<kbd>3</kbd>、設定 <kbd>Ctrl</kbd>+<kbd>4</kbd>、日誌 <kbd>Ctrl</kbd>+<kbd>5</kbd>、統計 <kbd>Ctrl</kbd>+<kbd>6</kbd> |
| **全域操作** | 立即同步 <kbd>Ctrl</kbd>+<kbd>R</kbd>、聚焦搜尋 <kbd>Ctrl</kbd>+<kbd>F</kbd> |
| **歷史頁** | 開啟選取項 <kbd>Enter</kbd>、刪除選取項 <kbd>Delete</kbd>、複製 URL <kbd>Ctrl</kbd>+<kbd>C</kbd>、複製標題 + URL <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>、切換書籤 <kbd>Ctrl</kbd>+<kbd>B</kbd>、新增註記 <kbd>Ctrl</kbd>+<kbd>N</kbd>、開啟匯出 <kbd>Ctrl</kbd>+<kbd>E</kbd>、隱藏選取項預設未指派 |
| **書籤頁** | 開啟 <kbd>Enter</kbd>、複製 URL <kbd>Ctrl</kbd>+<kbd>C</kbd>、刪除 <kbd>Delete</kbd>、新增註記 <kbd>Ctrl</kbd>+<kbd>N</kbd>、在歷史中定位 <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| **統計頁** | 上一週期 <kbd>Alt</kbd>+<kbd>Left</kbd>、下一週期 <kbd>Alt</kbd>+<kbd>Right</kbd> |
| **設定頁** | 儲存 <kbd>Ctrl</kbd>+<kbd>S</kbd> |

設定對話框才是最終事實來源。留白的快捷鍵代表它預設未綁定，需要由你自行指派。

---

## 自訂快捷鍵

1. 進入**設定 → 鍵盤快捷鍵**。
2. 點擊要修改的快捷鍵。
3. 按下新的組合鍵。
4. 點擊**儲存**。

要**停用**某個快捷鍵，點擊它後按 <kbd>Backspace</kbd> 或 <kbd>Delete</kbd> 清除。

!!! warning "快捷鍵衝突"
    如果兩個操作使用相同的組合鍵，最後設定的那個生效。設定對話框會對衝突顯示警告圖示。

---

## 速查懸浮視窗內的快捷鍵

這些快捷鍵在懸浮視窗（`Ctrl+Shift+H` 面板）內有效：

| 操作 | 按鍵 |
|---|---|
| **瀏覽結果** | <kbd>↑</kbd> / <kbd>↓</kbd> |
| **開啟選取的 URL** | <kbd>Enter</kbd> |
| **在新標籤頁開啟**（如果瀏覽器支援）| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> |
| **關閉懸浮視窗** | <kbd>Esc</kbd> |
| **清空搜尋** | <kbd>Ctrl</kbd>+<kbd>A</kbd> 然後 <kbd>Delete</kbd> |
