---
title: 安装
description: 如何在 Windows、macOS 和 Linux 上安装 HistorySync — 预构建安装包与源码安装两种方式。
---

# 安装

HistorySync 支持 **Windows**、**macOS** 和 **Linux**。请选择最适合你的安装方式。

---

## 预构建安装包（推荐）

从 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 页面下载最新版本。

=== "Windows"

    | 安装包 | 说明 |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | 完整安装程序，添加开始菜单条目，支持开机自启 |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | 便携版 — 解压即用，无需安装 |

    运行安装程序并按照向导操作。无需额外依赖。

=== "macOS"

    | 安装包 | 说明 |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | 拖拽式安装 |

    1. 打开 `.dmg` 文件。
    2. 将 **HistorySync** 拖入 `应用程序` 文件夹。
    3. 首次启动时，macOS 可能显示安全提示 — 点击 **打开** 继续。

    !!! note "辅助功能权限"
        全局快捷键 `Ctrl+Shift+H` 需要**辅助功能**权限。macOS 会在首次使用时提示授权。请在 **系统设置 → 隐私与安全 → 辅助功能** 中授权。

=== "Linux"

    | 安装包 | 说明 |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | 适用于任何现代 Linux 发行版 |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | 通用 tar 包，适用于任何 Linux 发行版 |
    | `historysync_X.Y.Z_amd64.deb` | 适用于 Debian/Ubuntu 系发行版 |

    **AppImage：**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb`：**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # 修复缺失依赖
    ```

    !!! warning "Linux/Wayland 全局快捷键"
        `pynput` 的全局快捷键**不支持 Wayland**。在 Wayland 会话中，`Ctrl+Shift+H` 悬浮窗快捷键将无法使用。可使用 `--quick` 配合系统级快捷键绑定作为替代方案（参见[键盘快捷键](keyboard-shortcuts.md)）。

---

## 源码安装

适合希望运行最新开发版本或参与贡献的用户。

### 前提条件

- **Python 3.10+**（推荐 Python 3.12 — 与 CI 环境一致）
- **Git**

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. 创建并激活虚拟环境（强烈推荐）
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. 安装运行时依赖
pip install -r requirements.txt

# 4. 运行应用
python -m src.main
```

### 安装 `hsync` CLI（可选）

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 页面提供预构建的 `hsync` 二进制文件：

| 安装包 | 平台 |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Windows 安装程序 |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows 便携版 |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS（Apple Silicon） |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

也可以直接通过 Python 调用无头 CLI：

```bash
python -m src.cli --help
```

将其安装为系统 `hsync` 命令（Linux / macOS）：

```bash
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## 验证安装

启动 GUI 并检查标题栏中的版本号，或运行：

```bash
# GUI
python -m src.main --version

# CLI
hsync --version
```

---

## 升级

用 Releases 页面上的新版本替换现有的安装包。HistorySync 将配置和数据库与应用程序分开存储，升级不会影响任何数据。

默认数据目录：

| 平台 | 目录 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

可通过 `--config-dir` 覆盖，或使用 `--portable` 模式将所有数据保存在可执行文件旁边。

---

## 卸载

1. 删除应用程序二进制文件 / AppImage / 安装包。
2. 可选：删除上述数据目录以彻底清除所有浏览数据和设置。

!!! warning
    删除数据目录是不可逆操作。如需保留历史数据，请先备份数据库。
