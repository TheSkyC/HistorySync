<div align="center">

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
  <p align="center"><a href="../README.md">中文</a> | <a href="./README.en.md">English</a> | 日本語<br></p>

# HistorySync
**HistorySync** は、強力なクロスプラットフォーム・デスクトップアプリケーションです。複数のブラウザデータの集約、ミリ秒単位の全文検索、WebDAVによる自動バックアップなど、ブラウザ履歴の一元管理とクラウドバックアップのための完全かつ効率的なソリューションを提供し、閲覧データを完全にコントロールすることを可能にします。

Chromium系、Firefox、Safariブラウザの基盤となるデータベースと完全に互換性があり、優れたプライバシー保護とローカライズされた管理体験を提供します。

---

## 📥 ダウンロード
最新バージョンは **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** ページからダウンロードできます。

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)


## 🚀 主な機能

### 📂 万能なデータ集約
*   **マルチブラウザ対応**: Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc など、10種類以上の主要ブラウザをネイティブサポート。
*   **インテリジェントな増分抽出**: SQLite WALメカニズムに基づく安全なスナップショット読み取り。ブラウザが実行中でも、データの損失や競合なしに最新の履歴を増分抽出できます。
*   **外部データベースのインポート**: 独立した `History` や `places.sqlite` ファイルを手動でインポートでき、古いPCやポータブル版ブラウザのデータを簡単に統合できます。

### 🖥️ モダンなインターフェース
*   **高性能な仮想リスト**: 数百万件の履歴データに最適化された仮想スクロールテーブル。メモリ使用量が極めて少なく、滑らかなスクロールを実現。
*   **アダプティブテーマ**: 丁寧に調整されたダーク/ライトテーマを内蔵。システムのテーマ設定に合わせた自動切り替えに対応。

### ☁️ クラウド同期と自動化
*   **WebDAVバックアップ**: ローカルデータベースをZIP圧縮し、任意のWebDAVクラウドストレージ（Nextcloud、堅果雲など）にバックアップ可能。
*   **データの完全性検証**: バックアップファイルにはSHA-256ハッシュリストが内蔵されており、復元時に自動検証を行うことでデータの破損を防ぎます。
*   **バックグラウンド・スケジューリング**: OS起動時の自動実行とシステムトレイへの最小化に対応。設定した間隔でバックグラウンドで自動的に抽出とクラウドバックアップを行います。

### 🛡️ 究極のプライバシーとコントロール
*   **ミリ秒単位の全文検索**: SQLite FTS5エンジンを採用し、タイトルやURLに対する超高速なキーワード検索が可能。
*   **ドメイン・ブラックリスト**: 特定のドメインをワンクリックでブラックリストに登録。関連する履歴を即座に削除し、今後の同期からも自動的に除外します。
*   **履歴の非表示**: 特定の記録を削除せずにUI上で「非表示」にすることができ、個人のプライバシーを保護します。


## 📸 スクリーンショット
*データダッシュボード*
<img width="1053" height="757" alt="image" src="https://github.com/user-attachments/assets/4d08b181-a76c-43fa-bb5e-db4cdc0d9106" />

*履歴の検索と管理*
<img width="1053" height="757" alt="image" src="https://github.com/user-attachments/assets/611262a7-c568-41bd-a06f-7bc7fc18d78d" />

<details>
<summary><b>► クリックして詳細なスクリーンショットを表示</b></summary>
<img width="1053" height="757" alt="image" src="https://github.com/user-attachments/assets/ff1f6973-7dd4-4e29-bfe8-0e7138d39275" />

*WebDAVクラウドバックアップ設定*

</details>


## 🛠️ 開発環境の設定

### 前提条件
*   Python 3.10 以上
*   Git (任意、リポジトリのクローン用)

### 手順
1.  **リポジトリのクローン (または ZIP のダウンロード)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **仮想環境の作成と有効化 (推奨)**
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

4.  **実行**
    ```bash
    python -m src.main
    ```

## 🚀 クイックスタート

HistorySync は柔軟な動作モードを提供します。バックグラウンドサービスとしても、アクティブな管理ツールとしても利用可能です。

### 1. 🔄 バックグラウンド・サイレントモード (推奨)
*「一度設定すれば、あとはお任せ」で自動バックアップを行いたいユーザー向け。*

1.  **起動設定**: `設定 > 起動設定` で「システム起動時に実行」にチェックを入れます。
2.  **タイマー設定**: `自動同期` で抽出の間隔を設定します。
3.  **クラウド設定**: `WebDAVクラウドバックアップ` にWebDAVアカウント情報を入力し、自動バックアップを有効にします。
4.  **バックグラウンド実行**: メインウィンドウを閉じると、プログラムはシステムトレイに最小化され、バックグラウンドでデータを守り続けます。

### 2. 🔍 アクティブ管理モード
*頻繁に履歴を検索したり、プライバシーデータを整理したりしたいユーザー向け。*

1.  **グローバル検索**: `履歴` ページで、上部の検索ボックスと日付範囲を使用して、閲覧したページを素早く特定します。
2.  **プライバシーの整理**: 残したくない記録を選択して右クリックから「削除」するか、「ドメインをブラックリストに登録」して特定のサイトの痕跡を完全に消去します。
3.  **データベースの保守**: データ量が増えてきたら、`設定 > データベースの保守` で `圧縮と最適化` をクリックして断片化を解消し、ディスク容量を解放します。

## 🌐 サポートされている言語
UIは以下の言語をサポートしています：
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
あらゆる形式の貢献を歓迎します！質問、機能提案、バグ報告がある場合は、GitHub Issues からお気軽にお問い合わせください。

## 📄 ライセンス
このプロジェクトは [Apache 2.0](LICENSE) ライセンスの下でオープンソースとして公開されています。

## 📞 お問い合わせ
- 著者: TheSkyC
- メール: 0x4fe6@gmail.com