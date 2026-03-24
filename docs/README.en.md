<div align="center">

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
  <p align="center"><a href="../README.md">中文</a> | English | <a href="./README.ja.md">日本語</a><br></p>

# HistorySync
**HistorySync** is a powerful cross-platform desktop application. It provides a complete and efficient solution for unified browser history management and cloud backup—from multi-browser data aggregation and millisecond-level full-text search to automated WebDAV backups, giving you total control over your browsing data.

Fully compatible with the underlying databases of Chromium-based browsers, Firefox, and Safari, it offers an exceptional privacy-first and localized management experience.

---

## 📥 Download
You can download the latest version from the **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** page.

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)


## 🚀 Core Features

### 📂 Versatile Data Aggregation
*   **Multi-Browser Support**: Native support for over a dozen major browsers including Chrome, Edge, Firefox, Safari, Brave, Vivaldi, and Arc.
*   **Smart Incremental Extraction**: Secure snapshot reading based on the SQLite WAL mechanism. Supports incremental extraction to get the latest records without data loss or conflicts, even while the browser is running.
*   **Standalone DB Import**: Manually import independent `History` or `places.sqlite` files to easily merge data from old computers or portable browser versions.

### 🖥️ Modern Interface
*   **High-Performance Virtual List**: A virtual scrolling table optimized for millions of records, featuring extremely low memory usage and silky-smooth scrolling.
*   **Adaptive Themes**: Built-in meticulously crafted Dark / Light themes with support for automatic system switching.

### ☁️ Cloud Sync & Automation
*   **WebDAV Backup**: Package and back up your local database to any WebDAV cloud storage (e.g., Nextcloud, Nutstore, etc.).
*   **Data Integrity Verification**: Backups are ZIP-compressed with a built-in SHA-256 hash manifest, automatically verified during restoration to prevent data corruption.
*   **Silent Background Scheduling**: Supports auto-start on boot and minimizing to the system tray, automatically performing extraction and cloud backups at custom intervals in the background.

### 🛡️ Ultimate Privacy & Control
*   **Millisecond Full-Text Search**: Powered by the SQLite FTS5 engine, enabling lightning-fast keyword searches across titles and URLs.
*   **Domain Blacklist**: Blacklist specific domains with one click to immediately delete related records and automatically filter them out in future syncs.
*   **Hidden Records**: "Hide" specific records in the UI without deleting them to protect personal privacy.


## 📸 Screenshots
*Data Dashboard*

*History Search & Management*

<details>
<summary><b>► Click to view more screenshots</b></summary>

*WebDAV Cloud Backup Settings*

</details>


## 🛠️ Development Setup

### Prerequisites
*   Python 3.10 or higher
*   Git (Optional, for cloning the repository)

### Steps
1.  **Clone the Repository (or download ZIP)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **Create and Activate Virtual Environment (Recommended)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run**
    ```bash
    python -m src.main
    ```

## 🚀 Quick Start

HistorySync offers flexible working modes. You can use it as a background service or an active management tool:

### 1. 🔄 Silent Background Mode (Recommended)
*For users who want to "set it and forget it" and let data back up automatically.*

1.  **Configure Startup**: Go to `Settings > Startup Settings` and check "Launch at system startup".
2.  **Set Interval**: Set the automatic extraction interval in `Auto Sync`.
3.  **Configure Cloud**: Enter your WebDAV credentials in `WebDAV Cloud Backup` and enable auto-backup.
4.  **Run in Background**: Close the main window; the program will minimize to the tray and protect your data silently.

### 2. 🔍 Active Management Mode
*For users who frequently need to find history or clean up private data.*

1.  **Global Search**: On the `History` page, use the top search box and date range to quickly locate visited pages.
2.  **Privacy Cleanup**: Select records you don't want to keep, right-click and select "Delete"; or choose "Blacklist Domain" to remove traces of specific sites forever.
3.  **DB Maintenance**: As data grows, click `Vacuum & Optimize` in `Settings > Database Maintenance` to defragment and free up disk space.

## 🌐 Supported Languages
The UI supports the following languages:
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

## 🤝 Contributing
Contributions of any kind are welcome! If you have questions, suggestions, or find bugs, feel free to submit them via GitHub Issues.

## 📄 License
This project is open-sourced under the [Apache 2.0](LICENSE) license.

## 📞 Contact
- Author: TheSkyC
- Email: 0x4fe6@gmail.com