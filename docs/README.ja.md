<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center"><a href="../README.md">English</a> | <a href="./README.zh.md">中文</a> | 日本語<br></p>

# HistorySync
**HistorySync** は、強力なクロスプラットフォームのデスクトップアプリケーションです。複数のブラウザからのデータ集約、ミリ秒単位の全文検索、WebDAVへの自動バックアップなど、ブラウザの閲覧履歴を統合管理・クラウドバックアップするための完全かつ効率的なソリューションを提供し、あなたのデジタルフットプリントを完全にコントロールできるようにします。

Chromium系、Firefox系、およびSafariブラウザの基盤となるデータベースをネイティブにサポートし、優れたプライバシー保護とローカル管理エクスペリエンスを提供します。

---

## 📥 ダウンロード
Windows、macOS、Linux向けの最新バージョンは、**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** ページからダウンロードできます。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 主な機能

### 📂 万能なデータ集約 (30以上のブラウザをサポート)
*   **膨大なブラウザ互換性**: Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc。
*   **スマートな差分抽出**: 基盤となるSQLite WALメカニズムに基づく安全なスナップショット読み取りにより、ブラウザの実行中でも損失や競合なしに最新の履歴を抽出できます。
*   **スタンドアロンDBのインポート**: 独立した `History` または `places.sqlite` ファイルを手動でインポートし、古いPCやポータブルブラウザのデータを簡単に統合できます。

### 🔍 Spotlightスタイルの検索とナレッジベース
*   **クイックアクセスオーバーレイ**: 任意の画面で `Ctrl+Shift+H` を押すと、ミニマリストな検索オーバーレイが呼び出されます。ウィンドウを切り替えることなく、瞬時に履歴を検索してURLを開くことができます。
*   **高度なクエリDSL**: `domain:github.com`, `after:2024-01-01`, `is:bookmarked` などのトークンを使用してプロのように検索。あいまい一致のドロップダウンや、インラインのゴーストテキスト補完機能を備えています。
*   **ブックマークと注釈**: 履歴をナレッジベースに変えましょう。重要なページにタグやリッチテキストのメモ（注釈）を追加できます。

### 📊 豊富な統計と分析
*   **ビジュアルアクティビティダッシュボード**: GitHubスタイルの日別ヒートマップ、ブラウザシェアの円グラフ、24時間のアクティビティバーを通じて、ブラウジングの習慣を視覚的に理解できます。
*   **ワンクリックエクスポート**: 美しい統計グラフをワンクリックで高解像度のPNG/JPEG画像としてエクスポートできます。

### ☁️ クラウド同期と自動化
*   **WebDAVバックアップとマージ**: ローカルデータベースをパッケージ化し、任意のWebDAVクラウド（Nextcloudなど）にバックアップします。復元時には、複数のデバイス間の履歴をインテリジェントにマージ（統合）し、競合を解決します。
*   **ヘッドレスCLI (`hsync`)**: パワーユーザー向けのフル機能コマンドラインツール。スクリプトやCI/CDを介して、抽出、バックアップ、CSV/JSONエクスポートを自動化します。
*   **サイレントバックグラウンドモード**: システムトレイに最小化された状態で実行され、スケジュールされた抽出とバックアップをバックグラウンドで自動的に実行します。

### 🛡️ 究極のプライバシーとコントロール
*   **マスターパスワード**: 業界標準のHKDF-SHA256暗号化を使用して、WebDAVの認証情報や同期設定を保護します。
*   **ドメインブラックリストとURLフィルター**: 特定のドメインをワンクリックでブロック。関連する履歴は即座に削除され、今後の同期でも永久に無視されます。ブラウザの内部ページ（例: `chrome://`）も除外可能です。

## 📸 スクリーンショット

*ダッシュボードの概要*

<img width="1000" alt="Dashboard" src="assets/ui-dashboard.png" />

<details>
<summary><b>► クリックして他のスクリーンショットを表示</b></summary>

*統計とヒートマップ*

<img width="1000" alt="Statistics" src="assets/ui-stats.png" />

*履歴の検索と管理*

<img width="1000" alt="History" src="assets/ui-history.png" />

</details>

## 🛠️ 開発環境のセットアップ

### 前提条件
*   Python 3.10 以上
*   Git (オプション、リポジトリのクローン用)

### 手順
1.  **リポジトリのクローン (またはZIPのダウンロード)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **仮想環境の作成とアクティブ化 (推奨)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **依存関係のインストール**
    ```bash
    pip install -r requirements.txt
    ```

4.  **アプリケーションの実行**
    ```bash
    python -m src.main
    ```

## 🚀 クイックスタート

HistorySyncは、サイレントバックグラウンドサービスとしても、アクティブな管理ツールとしても使用できます。

### 1. 🔄 サイレントバックグラウンドモード (推奨)
*データを自動的にバックアップし、「一度設定したら忘れる」ことを望むユーザーに最適です。*
1.  **起動設定**: `設定 > スタートアップ` に移動し、「システム起動時に起動」を有効にします。
2.  **スケジュール**: `自動同期` で抽出間隔を設定します。
3.  **クラウド**: `WebDAV クラウドバックアップ` にWebDAVの認証情報を入力し、自動バックアップを有効にします。
4.  **実行**: メインウィンドウを閉じます。アプリはトレイに最小化され、バックグラウンドで静かにデータを保護します。

### 2. 🔍 アクティブ管理モード
*履歴の検索、ページの注釈付け、プライバシーデータの消去を頻繁に行うユーザーに最適です。*
1.  **クイック検索**: どこでも `Ctrl+Shift+H` を押して、Spotlightスタイルのオーバーレイを使用します。
2.  **ナレッジベース**: 重要なページをブックマークし、後で参照できるようにメモを追加します。
3.  **プライバシー**: 不要なレコードを選択して削除するか、「ドメインをブラックリストに追加」を選択して、特定のサイトの痕跡を永久に消去します。

## 🌐 サポートされているUI言語
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

## 🤝 貢献
あらゆる形の貢献を歓迎します！質問、機能の提案、またはバグを見つけた場合は、GitHub Issuesからお気軽にお知らせください。

## 📄 ライセンス
このプロジェクトは [Apache 2.0](../LICENSE) ライセンスの下でオープンソース化されており、著作権表示を保持することを条件に、自由な使用、変更、配布が許可されています。

## 📞 連絡先
- 著者：骰子掷上帝 (TheSkyC)
- メール：0x4fe6@gmail.com