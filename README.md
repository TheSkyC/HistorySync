<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center">English | <a href="./docs/README.zh.md">中文</a> | <a href="./docs/README.ja.md">日本語</a><br></p>

# HistorySync
**HistorySync** is a powerful, cross-platform desktop application designed to unify, manage, and back up your browser history. From multi-browser data aggregation and millisecond full-text search to automated WebDAV backups and rich statistics, it gives you complete ownership over your digital footprint.

It natively supports the underlying databases of Chromium-based, Firefox-based, and Safari browsers, offering exceptional privacy protection and a seamless local management experience.

---

## 📥 Download
You can download the latest versions for Windows, macOS, and Linux from the **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** page.

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 Core Features

### 📂 Omnipotent Data Aggregation (30+ Browsers)
*   **Massive Browser Compatibility**: Natively supports Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc.
*   **Smart Incremental Extraction**: Safely reads SQLite WAL snapshots, allowing lossless, conflict-free extraction even while your browsers are running.
*   **Portable DB Import**: Manually import standalone `History` or `places.sqlite` files to easily merge data from old computers or portable browsers.

### 🔍 Spotlight-style Search & Knowledge Base
*   **Quick Access Overlay**: Press `Ctrl+Shift+H` anywhere to summon a minimalist search overlay. Instantly retrieve history and open URLs without switching windows.
*   **Advanced Query DSL**: Search like a pro using tokens (`domain:github.com`, `after:2024-01-01`, `is:bookmarked`). Features fuzzy-matching dropdowns and ghost-text inline completion.
*   **Bookmarks & Annotations**: Turn your history into a knowledge base. Add tags and rich-text notes to important pages.

### 📊 Rich Statistics & Analytics
*   **Visual Activity Dashboard**: Understand your browsing habits through a GitHub-style daily heatmap, browser market-share pie charts, and 24-hour activity bars.
*   **One-Click Export**: Export your beautiful statistics as high-resolution PNG/JPEG images.

### ☁️ Cloud Sync & Automation
*   **WebDAV Backup & Merge**: Pack and back up your local database to any WebDAV cloud (Nextcloud, ownCloud, etc.). Restoring intelligently merges records across multiple devices.
*   **Headless CLI (`hsync`)**: A fully-featured command-line tool for power users. Automate extractions, backups, and CSV/JSON exports via scripts or CI/CD.
*   **Silent Background Mode**: Runs minimized in the system tray, performing scheduled extractions and backups automatically.

### 🛡️ Ultimate Privacy & Control
*   **Master Password**: Secure your WebDAV credentials and sync configurations with industrial-grade HKDF-SHA256 encryption.
*   **Domain Blacklist & URL Filters**: One-click ban specific domains. They are instantly deleted and permanently ignored in future syncs. Filter out internal browser URLs (e.g., `chrome://`).

## 📸 Screenshots

*Data Dashboard Overview*

<img width="1000" alt="Dashboard" src="docs/assets/ui-dashboard.png" />

<details>
<summary><b>► Click to view more screenshots</b></summary>

*Visual Statistics & Heatmap*

<img width="1000" alt="Statistics" src="docs/assets/ui-stats.png" />

*History Search & Management*

<img width="1000" alt="History" src="docs/assets/ui-history.png" />

</details>

## 🛠️ Development Setup

### Prerequisites
*   Python 3.10 or higher
*   Git (optional, for cloning the repository)

### Steps
1.  **Clone the repository (or download ZIP)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **Create and activate a virtual environment (Recommended)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the application**
    ```bash
    python -m src.main
    ```

## 🚀 Quick Start

HistorySync can be used as a silent background service or an active management tool:

### 1. 🔄 Silent Background Mode (Recommended)
*Ideal for users who want to "set it and forget it" for automated backups.*
1.  **Startup**: Go to `Settings > Startup` and enable "Launch at system startup".
2.  **Schedule**: Set your extraction interval under `Auto Sync`.
3.  **Cloud**: Enter your WebDAV credentials in `WebDAV Cloud Backup` and enable auto-backup.
4.  **Run**: Close the main window. The app will minimize to the tray and quietly protect your data.

### 2. 🔍 Active Management Mode
*Ideal for users who frequently search history, annotate pages, or clear privacy data.*
1.  **Quick Search**: Press `Ctrl+Shift+H` to use the Spotlight-style overlay anywhere.
2.  **Knowledge Base**: Bookmark important pages and add notes for future reference.
3.  **Privacy**: Select unwanted records and delete them, or choose "Blacklist Domain" to wipe a site's traces permanently.

## 🌐 Supported UI Languages
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

## 🤝 Contributing
Contributions of any kind are welcome! If you have any questions, feature suggestions, or find a bug, please feel free to submit them via GitHub Issues.

## 📄 License
This project is open-sourced under the [Apache 2.0](LICENSE) license, allowing free use, modification, and distribution, provided the copyright notice is retained.

## 📞 Contact
- Author: TheSkyC
- Email: 0x4fe6@gmail.com