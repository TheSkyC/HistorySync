---
title: 貢獻指南
description: HistorySync 的開發環境設定、程式碼風格、DCO 簽署與 PR 工作流程。
---

# 貢獻指南

歡迎各種形式的貢獻！修復錯誤（Bug）、新增瀏覽器擷取器、改進文件、翻譯和補充測試覆蓋率都非常歡迎。

---

## 開始之前

1. **瀏覽開放的 [Issues](https://github.com/TheSkyC/HistorySync/issues)** — 尋找 `good first issue` 或 `help wanted` 標籤。
2. 在開始重大工作之前**在 Issue 中留言**，避免重複勞動。
3. 對於小修復（錯字、單行 Bug），可直接開 PR，無需先建立 Issue。

---

## 開發環境設定

### 前提條件

| 工具 | 版本 |
|---|---|
| Python | **3.12** 建議（與 CI 環境一致）|
| Git | 任何較新版本 |

### 步驟

```bash
# 1. Fork 儲存庫後複製您的 Fork
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. 建立並啟動虛擬環境
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. 安裝執行時期相依套件
pip install -r requirements.txt

# 4. 安裝開發與測試相依套件
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. （建議）安裝 pre-commit 掛鉤
pre-commit install

# 6. 驗證安裝
python -m src.main --fresh
```

---

## 程式碼風格

本專案使用 **[Ruff](https://github.com/astral-sh/ruff)** 進行程式碼檢查和格式化，設定檔為 `ruff.toml`。

```bash
# 檢查問題
ruff check .

# 自動修復（可修復的問題）
ruff check . --fix

# 格式化程式碼
ruff format .

# 手動執行所有 pre-commit 掛鉤
pre-commit run --all-files
```

**一般程式碼風格說明：**

- 遵循正在編輯的檔案中已有的模式。
- GUI 程式碼（PySide6）與業務邏輯**嚴格分離** — Service 層不得匯入 Qt。
- 優先清晰，而非炫技。
- 修改公開 API 時新增或更新文件字串（docstring）。

---

## 執行測試

```bash
# 執行全套測試
pytest

# 執行特定測試檔案
pytest tests/test_chromium_extractor.py

# 詳細輸出
pytest -v

# 含覆蓋率報告
pytest --cov=src --cov-report=term-missing

# 與 CI 相同的程式碼檢查
ruff check src/ tests/
ruff format --check src/ tests/
```

所有測試必須通過後 PR 才能合併。如果新增了功能，請附上對應的測試。

---

## 提交訊息規範

使用清晰的命令式提交訊息：

```
<類型>(<範圍>): <主旨>
```

**範例：**
```
fix(extractor): 修復 Chromium 擷取時 WAL 檔案缺失的處理
feat(browser): 新增 macOS 上的 Arc 瀏覽器支援
docs(webdav): 記錄合併行為
test(search): 為查詢 DSL 解析器新增單元測試
chore(dev): 更新 Ruff 至 0.15
```

**類型：** `fix`、`feat`、`refactor`、`docs`、`test`、`chore`、`perf`、`style`、`ci`、`build`

**規則：**
- 主旨行 ≤ 72 個字元。
- 使用小寫命令式動詞（`add`、`fix`、`remove` — 而非 `added`、`fixes`）。
- 對不明顯的變更，在正文中解釋*原因*。

---

## 開發者來源證書（DCO）

**每次提交都必須簽署。未簽署提交的 PR 不會被合併。**

```bash
git commit -s -m "fix: 修復 WAL 檔案缺失處理"
# 自動附加：Signed-off-by: 您的姓名 <your@email.com>
```

確保 Git 身分已設定：
```bash
git config --global user.name "您的姓名"
git config --global user.email "your@email.com"
```

### 忘記簽署了怎麼辦？

```bash
# 僅最後一次提交
git commit --amend --no-edit --signoff
git push --force-with-lease

# 多次提交（最後 N 次）
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## PR 工作流程

1. **從 `main` 建立分支：**
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **進行修改** — 保持每次提交專注且原子化。

3. **本機執行測試和程式碼檢查。**

4. **推送並對 `main` 開 PR。**

5. 遵守 PR 規範：
   - 每個 PR 只包含一個或一組相關修改。
   - 清楚描述*修改了什麼*以及*為什麼*。
   - 使用 `Closes #123` 關聯相關 Issue。
   - UI 修改附上截圖/錄影。
   - 每次提交都必須簽署。

6. **及時回應審查意見。**

---

## 我們特別歡迎

- **新瀏覽器擷取器** — 支援更多 Chromium/Firefox 分支。
- **錯誤修復** — 特別是平台相關問題（macOS 路徑、Linux 權限、Windows UAC）。
- **效能最佳化** — 查詢最佳化、擷取速度、記憶體佔用。
- **翻譯** — 更新 `src/resources/locales/` 下的 `.po` 檔案。
- **文件** — 改進本文件站、新增行內文件字串、修復錯字。

**請先討論（編碼前先開 Issue）：**

- 重大架構變更。
- 新的第三方相依套件。
- WebDAV 同步協定或資料庫表結構的變更。
