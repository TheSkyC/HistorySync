---
title: HistorySync — 統一瀏覽器歷史紀錄管理
description: HistorySync 完整文件 — 強大的跨平台瀏覽器歷史紀錄管理與 WebDAV 雲端備份桌面應用程式。
hide:
  - navigation
  - toc
---

<div class="hs-hero" markdown>

# HistorySync

**支援 30+ 瀏覽器的統一歷史紀錄管理與雲端備份**

<div class="hs-badges" markdown>

[![Release](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)](https://github.com/TheSkyC/HistorySync/releases/latest)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TheSkyC/HistorySync/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)

</div>

<div class="hs-button-group" markdown>

[下載最新版本 :material-download:](#下載){ .md-button .md-button--primary }
[在 GitHub 上查看 :material-github:](https://github.com/TheSkyC/HistorySync){ .md-button }

</div>

</div>

## HistorySync 是什麼？

**HistorySync** 是一款功能強大的跨平台桌面應用程式，讓您徹底掌控自己的瀏覽資料。它將所有瀏覽器的歷史紀錄聚合到同一個可搜尋的資料庫中，並安全地備份到雲端。

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
<strong>30+ 瀏覽器</strong>
<p>原生支援 Chrome、Edge、Firefox、Safari、Brave、Vivaldi、Arc 以及數十款國內外瀏覽器。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
<strong>Spotlight 速查</strong>
<p>隨時按下 <code>Ctrl+Shift+H</code> 喚出即時搜尋懸浮視窗。配合進階查詢語法，毫秒級定位任意頁面。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
<strong>WebDAV 雲端同步</strong>
<p>原子化串流上傳，支援任意 WebDAV 伺服器。恢復時智慧合併多設備資料。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
<strong>百萬級資料效能</strong>
<p>Keyset 分頁 + SQL 層正規表示式搜尋，即使在海量資料集上也能流暢捲動。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong>無頭 CLI（<code>hsync</code>）</strong>
<p>從命令列自動化執行同步、備份、匯出和搜尋，完美適配定時任務和 CI。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
<strong>隱私優先</strong>
<p>HKDF 加密憑證、網域黑名單、軟隱藏功能，以及專屬隱藏紀錄視圖。</p>
</div>

</div>

---

## 下載

<div class="hs-download-grid" markdown>

<div class="hs-dl-card" markdown>
**Windows**

[安裝程式 (.exe)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-setup.exe){ .md-button .md-button--primary }
[可攜版 (.zip)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-portable.zip){ .md-button }
</div>

<div class="hs-dl-card" markdown>
**macOS**

[磁碟映像 (.dmg)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-macos-arm64.dmg){ .md-button .md-button--primary }
</div>

<div class="hs-dl-card" markdown>
**Linux**

[AppImage]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-linux-x86_64.AppImage){ .md-button .md-button--primary }
[.deb 套件]({{ gh_repo }}/releases/download/v{{ app_version }}/historysync_{{ app_version }}_amd64.deb){ .md-button }
</div>

</div>

> 所有安裝套件均在 **[GitHub Releases]({{ gh_repo }}/releases/latest)** 頁面。上方按鈕始終指向最新版本。

---

## 快速導覽

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
<strong><a href="guide/quick-start/">快速上手</a></strong>
<p>五分鐘完成設定，開啟自動背景同步。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong><a href="guide/cli-reference/">CLI 命令參考</a></strong>
<p><code>hsync</code> 命令列工具完整參考手冊。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
<strong><a href="guide/webdav-setup/">WebDAV 設定</a></strong>
<p>主流 WebDAV 服務商的逐步設定指南。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path d="M14 5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM2 4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><path d="M13 10.25a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm0-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5 0A.25.25 0 0 1 8.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 8 8.75zm2 0a.25.25 0 0 1 .25-.25h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5a.25.25 0 0 1-.25-.25zm1 2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5-2A.25.25 0 0 1 6.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 6 8.75zm-2 0A.25.25 0 0 1 4.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 4 8.75zm-2 0A.25.25 0 0 1 2.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 2 8.75zm11-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0A.25.25 0 0 1 9.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 9 6.75zm-2 0A.25.25 0 0 1 7.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 7 6.75zm-2 0A.25.25 0 0 1 5.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 5 6.75zm-3 0A.25.25 0 0 1 2.25 6h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5A.25.25 0 0 1 2 6.75zm0 4a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm2 0a.25.25 0 0 1 .25-.25h5.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-5.5a.25.25 0 0 1-.25-.25z"/></svg>
<strong><a href="guide/keyboard-shortcuts/">鍵盤快捷鍵</a></strong>
<p>全部 25 個可設定快捷鍵，含 1 個全域熱鍵與 24 個應用程式內綁定。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M6 3.5A1.5 1.5 0 0 1 7.5 2h1A1.5 1.5 0 0 1 10 3.5v1A1.5 1.5 0 0 1 8.5 6v1H14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0v-1A.5.5 0 0 1 2 7h5.5V6A1.5 1.5 0 0 1 6 4.5zM8.5 5a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5zM0 11.5A1.5 1.5 0 0 1 1.5 10h1A1.5 1.5 0 0 1 4 11.5v1A1.5 1.5 0 0 1 2.5 14h-1A1.5 1.5 0 0 1 0 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5A1.5 1.5 0 0 1 7.5 10h1a1.5 1.5 0 0 1 1.5 1.5v1A1.5 1.5 0 0 1 8.5 14h-1A1.5 1.5 0 0 1 6 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5a1.5 1.5 0 0 1 1.5-1.5h1a1.5 1.5 0 0 1 1.5 1.5v1a1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5z"/></svg>
<strong><a href="dev/architecture/">架構概覽</a></strong>
<p>MVVM 分層圖與模組概述，面向貢獻者。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
<strong><a href="dev/contributing/">貢獻指南</a></strong>
<p>DCO 簽署、程式碼規範與 PR 工作流程。</p>
</div>

</div>
