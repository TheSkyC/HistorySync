---
title: 安裝
description: 如何在 Windows、macOS 和 Linux 上安裝 HistorySync — 預建安裝套件與原始碼安裝兩種方式。
---

# 安裝

HistorySync 支援 **Windows**、**macOS** 和 **Linux**。請選擇最適合您的安裝方式。

---

## 預建安裝套件（建議）

從 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 頁面下載最新版本。

=== "Windows"

    | 安裝套件 | 說明 |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | 完整安裝程式，新增開始功能表項目，支援開機自動啟動 |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | 可攜版 — 解壓即用，無需安裝 |

    執行安裝程式並依照精靈操作。無需額外相依套件。

=== "macOS"

    | 安裝套件 | 說明 |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | 拖放式安裝 |

    1. 開啟 `.dmg` 檔案。
    2. 將 **HistorySync** 拖入 `應用程式` 資料夾。
    3. 首次啟動時，macOS 可能顯示安全性提示 — 點擊 **開啟** 繼續。

    !!! note "輔助使用權限"
        全域快捷鍵 `Ctrl+Shift+H` 需要**輔助使用**權限。macOS 會在首次使用時提示授權。請在 **系統設定 → 隱私權與安全性 → 輔助使用** 中授權。

=== "Linux"

    | 安裝套件 | 說明 |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | 適用於任何現代 Linux 發行版 |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | 通用 tar 壓縮包，適用於任何 Linux 發行版 |
    | `historysync_X.Y.Z_amd64.deb` | 適用於 Debian/Ubuntu 系發行版 |

    **AppImage：**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb`：**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # 修復缺失相依套件
    ```

    !!! warning "Linux/Wayland 全域快捷鍵"
        `pynput` 的全域快捷鍵**不支援 Wayland**。在 Wayland 工作階段中，`Ctrl+Shift+H` 懸浮視窗快捷鍵將無法使用。可使用 `--quick` 搭配系統級快捷鍵繫結作為替代方案（參見[鍵盤快捷鍵](keyboard-shortcuts.md)）。

---

## 原始碼安裝

適合希望執行最新開發版本或參與貢獻的使用者。

### 前提條件

- **Python 3.10+**（建議 Python 3.12 — 與 CI 環境一致）
- **Git**

### 步驟

```bash
# 1. 複製儲存庫
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. 建立並啟動虛擬環境（強烈建議）
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. 安裝執行時期相依套件
pip install -r requirements.txt

# 4. 執行應用程式
python -m src.main
```

### 安裝 `hsync` CLI（選用）

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 頁面提供預建的 `hsync` 二進位檔案：

| 安裝套件 | 平台 |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Windows 安裝程式 |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows 可攜版 |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS（Apple Silicon） |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

也可以直接透過 Python 呼叫無頭 CLI：

```bash
python -m src.cli --help
```

將其安裝為系統 `hsync` 命令（Linux / macOS）：

```bash
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## 驗證安裝

啟動 GUI 並檢查標題列中的版本號，或執行：

```bash
# GUI
python -m src.main --version

# CLI
hsync --version
```

---

## 升級

用 Releases 頁面上的新版本替換現有的安裝套件。HistorySync 將設定和資料庫與應用程式分開儲存，升級不會影響任何資料。

從 1.4.0 開始，打包版桌面應用也內建了**應用程式內更新系統**：

- **Windows 安裝版**可以直接交給安裝程式接管升級流程。
- **macOS `.dmg` 版本**可以下載並自動開啟磁碟映像。
- **可攜版、AppImage 與封存版**會下載並驗證對應安裝包，然後在檔案總管中定位檔案，方便你安全替換目前程式。
- **系統套件管理安裝**，例如 `.deb`，仍建議透過套件管理器或 Releases 頁面升級。

你可以在 **設定 → 更新 → 檢查更新** 中觸發，也可以在偵測到新版本後透過更新橫幅進入詳情頁。

如果偏好終端機方式，也可以執行：

```bash
hsync update
hsync update --json
hsync update --channel beta
```

預設資料目錄：

| 平台 | 目錄 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

可透過 `--config-dir` 覆寫，或使用 `--portable` 模式將所有資料儲存在執行檔旁邊。

!!! tip "可攜模式"
    可攜安裝和基於 `.portable` 標記檔的執行方式，會把設定和資料庫保存在執行檔旁邊。更新系統也會盡量為這類安裝選擇 portable 風格的發布產物。

---

## 解除安裝

1. 刪除應用程式二進位檔 / AppImage / 安裝套件。
2. 選用：刪除上述資料目錄以徹底清除所有瀏覽資料和設定。

!!! warning
    刪除資料目錄是不可逆操作。如需保留歷史資料，請先備份資料庫。
