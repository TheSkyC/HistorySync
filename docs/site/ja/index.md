---
title: HistorySync — 統合ブラウザ履歴管理
description: HistorySync の完全なドキュメント — 30以上のブラウザに対応した、強力なクロスプラットフォームデスクトップアプリです。ブラウザ履歴の管理と WebDAV クラウドバックアップをサポートします。
hide:
  - navigation
  - toc
---

<div class="hs-hero" markdown>

<p>
  <img src="../assets/historysync-banner.svg" alt="HistorySync banner" width="360">
</p>

**30以上のブラウザに対応した統合ブラウザ履歴管理・クラウドバックアップツール**

<div class="hs-badges" markdown>

[![Release](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)](https://github.com/TheSkyC/HistorySync/releases/latest)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TheSkyC/HistorySync/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)

</div>

<div class="hs-button-group" markdown>

[最新版をダウンロード :material-download:](#ダウンロード){ .md-button .md-button--primary }
[GitHub で見る :material-github:](https://github.com/TheSkyC/HistorySync){ .md-button }

</div>

</div>

## HistorySync とは？

**HistorySync** は、ブラウジングデータを完全に自分で管理できる、強力なクロスプラットフォームデスクトップアプリケーションです。すべてのブラウザの履歴を一つの検索可能なデータベースに集約し、クラウドに安全にバックアップします。

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
<strong>30以上のブラウザに対応</strong>
<p>Chrome、Edge、Firefox、Safari、Brave、Vivaldi、Arc など、地域限定ブラウザを含む多数のブラウザをネイティブサポート。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
<strong>スポットライト検索</strong>
<p>どのアプリからでも <code>Ctrl+Shift+H</code> を押すだけで、即座に検索オーバーレイを呼び出せます。高度なクエリ DSL で何でも瞬時に検索できます。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>
<strong>WebDAV クラウド同期</strong>
<p>任意の WebDAV サーバーへのアトミックストリーミングアップロード。復元時のインテリジェントなマルチデバイスマージ機能付き。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
<strong>100万件レコード対応のパフォーマンス</strong>
<p>キーセットページネーションと SQL レイヤーの正規表現検索により、大規模なデータセットでも滑らかなスクロールを実現。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong>ヘッドレス CLI（<code>hsync</code>）</strong>
<p>コマンドラインから同期・バックアップ・エクスポート・検索を自動化できます。定期タスクや CI 環境に最適です。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
<strong>プライバシーファースト</strong>
<p>HKDF 暗号化された認証情報、ドメインブラックリスト、ソフト非表示機能、専用の非表示レコードビューを搭載。</p>
</div>

</div>

---

## ダウンロード

<div class="hs-download-grid" markdown>

<div class="hs-dl-card" markdown>
**Windows**

[インストーラー (.exe)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-setup.exe){ .md-button .md-button--primary }
[ポータブル (.zip)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-windows-x64-portable.zip){ .md-button }
</div>

<div class="hs-dl-card" markdown>
**macOS**

[ディスクイメージ (.dmg)]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-macos-arm64.dmg){ .md-button .md-button--primary }
</div>

<div class="hs-dl-card" markdown>
**Linux**

[AppImage]({{ gh_repo }}/releases/download/v{{ app_version }}/HistorySync-v{{ app_version }}-linux-x86_64.AppImage){ .md-button .md-button--primary }
[.deb パッケージ]({{ gh_repo }}/releases/download/v{{ app_version }}/historysync_{{ app_version }}_amd64.deb){ .md-button }
</div>

</div>

> すべてのパッケージは **[GitHub Releases]({{ gh_repo }}/releases/latest)** ページにあります。上のボタンは常に最新バージョンを指しています。

---

## クイックリンク

<div class="hs-grid">

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
<strong><a href="guide/quick-start/">クイックスタート</a></strong>
<p>5分以内に自動バックグラウンド同期を設定して使い始めましょう。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
<strong><a href="guide/cli-reference/">CLI リファレンス</a></strong>
<p><code>hsync</code> コマンドラインツールの完全リファレンス。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
<strong><a href="guide/webdav-setup/">WebDAV 設定</a></strong>
<p>主要な WebDAV プロバイダーごとの設定ガイド。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path d="M14 5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM2 4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><path d="M13 10.25a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm0-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5 0A.25.25 0 0 1 8.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 8 8.75zm2 0a.25.25 0 0 1 .25-.25h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5a.25.25 0 0 1-.25-.25zm1 2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-5-2A.25.25 0 0 1 6.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 6 8.75zm-2 0A.25.25 0 0 1 4.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 4 8.75zm-2 0A.25.25 0 0 1 2.25 8h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 2 8.75zm11-2a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm-2 0A.25.25 0 0 1 9.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 9 6.75zm-2 0A.25.25 0 0 1 7.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 7 6.75zm-2 0A.25.25 0 0 1 5.25 6h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5A.25.25 0 0 1 5 6.75zm-3 0A.25.25 0 0 1 2.25 6h1.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-1.5A.25.25 0 0 1 2 6.75zm0 4a.25.25 0 0 1 .25-.25h.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-.5a.25.25 0 0 1-.25-.25zm2 0a.25.25 0 0 1 .25-.25h5.5a.25.25 0 0 1 .25.25v.5a.25.25 0 0 1-.25.25h-5.5a.25.25 0 0 1-.25-.25z"/></svg>
<strong><a href="guide/keyboard-shortcuts/">キーボードショートカット</a></strong>
<p>グローバルホットキー 1 個とアプリ内バインド 24 個を含む、25 個の設定可能なショートカット。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon hs-card-icon--fill" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M6 3.5A1.5 1.5 0 0 1 7.5 2h1A1.5 1.5 0 0 1 10 3.5v1A1.5 1.5 0 0 1 8.5 6v1H14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0v-1A.5.5 0 0 1 2 7h5.5V6A1.5 1.5 0 0 1 6 4.5zM8.5 5a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5zM0 11.5A1.5 1.5 0 0 1 1.5 10h1A1.5 1.5 0 0 1 4 11.5v1A1.5 1.5 0 0 1 2.5 14h-1A1.5 1.5 0 0 1 0 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5A1.5 1.5 0 0 1 7.5 10h1a1.5 1.5 0 0 1 1.5 1.5v1A1.5 1.5 0 0 1 8.5 14h-1A1.5 1.5 0 0 1 6 12.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5zm4.5.5a1.5 1.5 0 0 1 1.5-1.5h1a1.5 1.5 0 0 1 1.5 1.5v1a1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5zm1.5-.5a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5z"/></svg>
<strong><a href="dev/architecture/">アーキテクチャ</a></strong>
<p>コントリビューター向けの MVVM 層ダイアグラムとモジュール概要。</p>
</div>

<div class="hs-card">
<svg class="hs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
<strong><a href="dev/contributing/">コントリビュート</a></strong>
<p>DCO サインオフ、コーディングスタイル、プルリクエストのワークフロー。</p>
</div>

</div>
