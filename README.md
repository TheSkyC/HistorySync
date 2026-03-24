<div align="center">

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
  <p align="center">中文 | <a href="./docs/README.en.md">English</a> | <a href="./docs/README.ja.md">日本語</a><br></p>

# HistorySync
**HistorySync** 是一款功能强大的跨平台桌面应用程序。它提供了一套完整、高效的浏览器历史记录统一管理与云端备份解决方案，从多浏览器数据聚合，到毫秒级全文检索，再到 WebDAV 自动化备份，让你彻底掌控自己的浏览数据。

本工具完全兼容 Chromium 系、Firefox 系以及 Safari 浏览器的底层数据库，并提供极佳的隐私保护和本地化管理体验。

---

## 📥 下载
您可以从 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 页面下载最新版本。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)


## 🚀 核心特性

### 📂 全能的数据聚合
*   **多浏览器支持**：原生支持 Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc 等十余种主流浏览器。
*   **智能增量提取**：基于底层 SQLite WAL 机制的安全快照读取，支持增量提取，即使浏览器正在运行也能无损、无冲突地获取最新记录。
*   **游离数据库导入**：支持手动导入独立的 `History` 或 `places.sqlite` 文件，轻松合并旧电脑或便携版浏览器的数据。

### 🖥️ 现代化的交互界面
*   **高性能虚拟列表**：针对百万级历史记录优化的虚拟滚动表格，内存占用极低，滚动丝滑流畅。
*   **自适应主题**：内置精心调色的 Dark / Light 主题，支持跟随系统自动切换。

### ☁️ 云端同步与自动化
*   **WebDAV 备份**：支持将本地数据库打包备份至任意 WebDAV 云盘（如 Nextcloud, 坚果云等）。
*   **数据完整性校验**：备份文件采用 ZIP 压缩，并内置 SHA-256 哈希清单，恢复时自动校验，杜绝数据损坏。
*   **后台静默调度**：支持开机自启并最小化到系统托盘，按照自定义的时间间隔在后台自动完成提取与云端备份。

### 🛡️ 极致的隐私与掌控
*   **毫秒级全文检索**：底层采用 SQLite FTS5 引擎，支持对标题和 URL 进行极速的关键词搜索。
*   **域名黑名单**：一键拉黑特定域名，不仅立即删除相关记录，未来的同步也会自动将其过滤。
*   **记录隐藏**：支持将特定记录在 UI 中“隐藏”而不删除，保护个人隐私。


## 📸 截图
*数据仪表盘*

*历史记录检索与管理*

<details>
<summary><b>► 点击查看更多截图</b></summary>

*WebDAV 云端备份设置*

</details>


## 🛠️ 开发环境设置

### 前提条件
*   Python 3.10 或更高版本
*   Git (可选，用于克隆仓库)

### 步骤
1.  **克隆仓库 (或下载 ZIP)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **创建并激活虚拟环境 (推荐)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```

4.  **运行**
    ```bash
    python -m src.main
    ```

## 🚀 快速上手

HistorySync 提供灵活的工作模式，你可以把它当作一个后台服务，也可以当作一个主动管理工具：

### 1. 🔄 后台静默模式 (推荐)
*适用于希望“设置一次，永远忘记”，让数据自动备份的用户。*

1.  **配置启动**: 进入 `设置 > 开机设置`，勾选“开机自启”。
2.  **设置定时**: 在 `自动备份` 中设置自动提取的间隔。
3.  **配置云盘**: 在 `WebDAV 云端备份` 中填入你的 WebDAV 账号，并开启自动备份。
4.  **后台运行**: 关闭主窗口，程序将最小化到系统托盘，在后台默默守护你的浏览数据。

### 2. 🔍 主动管理模式
*适用于需要经常查找历史记录、清理隐私数据的用户。*

1.  **全局搜索**: 在 `历史记录` 页面，使用顶部的搜索框和日期范围快速定位看过的网页。
2.  **隐私清理**: 选中不想保留的记录，右键选择“删除”；或者直接选择“拉黑该域名”，一劳永逸地清理特定网站的痕迹。
3.  **数据库维护**: 随着数据量增加，可以在 `设置 > 数据库维护` 中点击 `压缩与优化` 来整理碎片，释放磁盘空间。

## 🌐 支持的语言
本工具支持以下语言的 UI 界面：
*   **English** (`en_US`)
*   **简体中文** (`zh_CN`)
*   **繁體中文** (`zh_TW`)
*   **日本語** (`ja_JP`)
*   **한국어** (`ko_KR`)
*   **Français** (`fr_FR`)
*   **Deutsch** (`de_DE`)
*   **Русский** (`ru_RU`)
*   **Español** (`es_ES`)
*   **Português** (`pt_BR`)
*   **Italiano** (`it_IT`)
*   **Polski** (`pl_PL`)
*   **Türkçe** (`tr_TR`)

## 🤝 贡献
欢迎任何形式的贡献！如果您有任何问题、功能建议或发现 Bug，请随时通过 GitHub Issues 提交。

## 📄 许可证
本项目基于 [Apache 2.0](LICENSE) 开源，允许自由使用、修改和分发，但需保留版权声明。

## 📞 联系
- 作者：骰子掷上帝 (TheSkyC)
- 邮箱：0x4fe6@gmail.com