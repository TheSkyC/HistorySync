<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center"><a href="../README.md">English</a> | 中文 | <a href="./README.ja.md">日本語</a><br></p>

# HistorySync
**HistorySync** 是一款功能强大的跨平台桌面应用程序。它提供了一套完整、高效的浏览器历史记录统一管理与云端备份解决方案，从多浏览器数据聚合，到毫秒级全文检索，再到 WebDAV 自动化备份，让你彻底掌控自己的浏览数据。

本工具完全兼容 Chromium 系、Firefox 系以及 Safari 浏览器的底层数据库，并提供极佳的隐私保护和本地化管理体验。

---

## 📥 下载
您可以从 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 页面下载最新版本。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 核心特性

### 📂 全能的数据聚合 (支持 30+ 浏览器)
*   **海量浏览器支持**：原生支持 Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc 以及众多国产/定制浏览器（QQ、搜狗、星愿、百分、猎豹等）。
*   **智能增量提取**：基于底层 SQLite WAL 机制的安全快照读取，支持增量提取，即使浏览器正在运行也能无损、无冲突地获取最新记录。
*   **游离数据库导入**：支持手动导入独立的 `History` 或 `places.sqlite` 文件，轻松合并旧电脑或便携版浏览器的数据。

### 🔍 Spotlight 风格速查与知识库
*   **全局速查悬浮窗**：无论在任何软件中，按下 `Ctrl+Shift+H` 即可唤出极简搜索框，瞬间检索历史并打开网页。
*   **高级查询语法**：支持类似搜索引擎的语法（如 `domain:github.com`, `after:2024-01-01`），并带有模糊匹配的下拉提示与内联幽灵文本补全。
*   **书签与批注**：历史记录不再是流水账。为重要网页添加标签（Tags）和富文本批注（Notes），将其转化为个人知识库。

### 📊 丰富的数据可视化统计
*   **活动仪表盘**：通过 GitHub 风格的年度活跃度热力图、浏览器份额饼图、24小时活跃度柱状图，直观了解你的数字生活轨迹。
*   **一键导出**：支持将精美的统计图表一键导出为高清 PNG/JPEG 长图。

### ☁️ 云端同步与自动化
*   **WebDAV 备份与合并**：将本地数据库打包备份至任意 WebDAV 云盘。从云端恢复时，系统会智能合并跨设备的记录，完美解决冲突。
*   **无头命令行 (`hsync`)**：专为极客打造的 CLI 工具。完美支持无头环境下的数据提取、备份、结构化查询与 CSV/JSON 导出。
*   **后台静默调度**：支持开机自启并最小化到系统托盘，按照自定义的时间间隔在后台自动完成提取与云端备份。

### 🛡️ 极致的隐私与掌控
*   **主密码保护**：使用 HKDF-SHA256 算法加密 WebDAV 凭证等敏感配置，执行敏感操作前需验证会话。
*   **域名黑名单与 URL 过滤**：一键拉黑特定域名，不仅立即删除相关记录，未来的同步也会自动将其过滤。

## 📸 截图

*数据仪表盘概览*

<img width="1000" alt="Dashboard" src="assets/ui-dashboard.png" />

<details>
<summary><b>► 点击查看更多截图</b></summary>

*可视化统计与热力图*

<img width="1000" alt="Statistics" src="assets/ui-stats.png" />

*历史记录检索与管理*

<img width="1000" alt="History" src="assets/ui-history.png" />

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
1.  **配置启动**: 进入 `设置 > 开机启动`，勾选“开机自启”。
2.  **设置定时**: 在 `自动同步` 中设置自动提取的间隔。
3.  **配置云盘**: 在 `WebDAV 云端备份` 中填入你的 WebDAV 账号，并开启自动备份。
4.  **后台运行**: 关闭主窗口，程序将最小化到系统托盘，在后台默默守护你的浏览数据。

### 2. 🔍 主动管理模式
*适用于需要经常查找历史记录、做笔记、清理隐私数据的用户。*
1.  **全局速查**: 随时随地按下 `Ctrl+Shift+H` 唤出悬浮窗查找历史。
2.  **知识沉淀**: 为有价值的网页添加书签和批注，方便日后回顾。
3.  **隐私清理**: 选中不想保留的记录，右键选择“删除”；或者直接选择“拉黑该域名”，一劳永逸地清理特定网站的痕迹。

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
*   **Italiano** (`it_IT`)

## 🤝 贡献
欢迎任何形式的贡献！如果您有任何问题、功能建议或发现 Bug，请随时通过 GitHub Issues 提交。

## 📄 许可证
本项目基于 [Apache 2.0](../LICENSE) 开源，允许自由使用、修改和分发，但需保留版权声明。

## 📞 联系
- 作者：骰子掷上帝 (TheSkyC)
- 邮箱：0x4fe6@gmail.com