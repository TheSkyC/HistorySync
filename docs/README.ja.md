<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center">
  <a href="../README.md">English</a> | 
  <a href="./README.zh-CN.md">简体中文</a> | 
  <a href="./README.zh-TW.md">繁體中文</a> | 
  日本語 | 
  <a href="./README.ko.md">한국어</a> | 
  <a href="./README.ru.md">Русский</a> | 
  <a href="./README.fr.md">Français</a>
<br></p>

# HistorySync
**HistorySync** は、強力なクロスプラットフォームのデスクトップアプリケーションです。複数のブラウザからのデータ集約、ミリ秒単位の全文検索、WebDAVへの自動バックアップ、豊富な統計機能など、ブラウザの閲覧履歴を統合管理・クラウドバックアップするための完全かつ効率的なソリューションを提供し、あなたのデジタルフットプリントを完全にコントロールできるようにします。

Chromium系、Firefox系、およびSafariブラウザの基盤となるデータベースをネイティブにサポートし、優れたプライバシー保護とローカル管理エクスペリエンスを提供します。

---

## 📥 ダウンロード
Windows、macOS、Linux向けの最新バージョンは、**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** ページからダウンロードできます。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 主な機能

### 📂 万能なデータ集約 (30以上のブラウザをサポート)
*   **膨大なブラウザ互換性**: Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc などの主流ブラウザに加え、多数の派生ブラウザ（QQ, Sogou, CentBrowserなど）をネイティブサポート。
*   **スマートな差分抽出**: SQLite WALメカニズムに基づく安全なスナップショット読み取りにより、ブラウザの実行中でも損失や競合なしに最新の履歴を抽出できます。
*   **スタンドアロンDBのインポート**: 独立した `History` または `places.sqlite` ファイルを手動でインポートし、古いPCやポータブルブラウザのデータを簡単に統合できます。

### 🔍 Spotlightスタイルの検索とナレッジベース
*   **クイックアクセスオーバーレイ**: 任意の画面で `Ctrl+Shift+H` を押すと、ミニマリストな検索オーバーレイが呼び出されます。
*   **新しいホットキーエンジン**: `pynput` に基づくクロスプラットフォームのホットキーシステム。14の高度にカスタマイズ可能なショートカットを提供します。
*   **高度なクエリDSL**: `domain:github.com`, `after:2024-01-01` などのトークンを使用してプロのように検索。あいまい一致のドロップダウンやゴーストテキスト補完機能を備えています。
*   **ブックマークと注釈**: 重要なページにタグやリッチテキストのメモを追加し、履歴をナレッジベースに変えましょう。

### ⚡ 究極のパフォーマンスとモダンなUI
*   **数百万件のデータでも滑らかなスクロール**: ページネーションロジックを書き直し、2段階ページネーションとKeysetインデックスを導入。正規表現検索をSQLレイヤーに押し下げることで、高速スクロール時のカクつきを完全に排除しました。
*   **アダプティブインターフェース**: 比例列幅割り当てメカニズムを導入し、ウィンドウのサイズ変更がスムーズに。システムのダーク/ライトテーマのリアルタイム切り替えを完全にサポートします。
*   **豊富なデータ視覚化**: GitHubスタイルの日別ヒートマップ、ブラウザシェアの円グラフ、24時間のアクティビティバーを通じて、ブラウジングの習慣を視覚的に理解できます。

### ☁️ クラウド同期と自動化
*   **WebDAVバックアップとマージ**: **アトミックなストリームアップロード**を採用。クラウドから復元する際、システムは複数のデバイス間の履歴をインテリジェントにマージします。
*   **ヘッドレスCLI (`hsync`)**: パワーユーザー向けのフル機能コマンドラインツール。バックグラウンドでのメモリ使用量が非常に低いです。
*   **サイレントバックグラウンドモード**: システムトレイに最小化された状態で実行され、スケジュールされた抽出とバックアップを自動的に実行します。

### 🛡️ 究極のプライバシーとコントロール
*   **非表示モードとソフト非表示**: 専用の「非表示レコード」ビュー。特定のドメインのソフト非表示をサポートします（レコードはデータベースに残りますが、メインビューからは消えます）。
*   **セキュリティアーキテクチャ V2**: 独立したHKDF暗号化および認証サブキーを使用して、WebDAV資格情報などの機密設定を保護します。
*   **ドメインブラックリストとURLフィルター**: 特定のドメインをワンクリックでブロック。関連する履歴は即座に削除され、今後の同期でも永久に無視されます。

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
このツールは以下の言語のUIインターフェースを提供しています。
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
あらゆる形の貢献を歓迎します。開発環境、コーディング規約、DCO 署名要件については、まず [CONTRIBUTING.md](../CONTRIBUTING.md) をご確認ください。バグ報告、機能提案、利用に関する質問は、GitHub の issue テンプレートを優先してご利用ください。

## 📄 ライセンス
このプロジェクトは [Apache 2.0](../LICENSE) ライセンスの下でオープンソース化されており、著作権表示を保持することを条件に、自由な使用、変更、配布が許可されています。

## 📞 連絡先
- 著者：TheSkyC
- メール：0x4fe6@gmail.com