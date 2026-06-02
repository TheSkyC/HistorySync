---
title: CLI リファレンス
description: hsync コマンドラインツールの完全リファレンス — すべてのフラグ、サブコマンド、高度なクエリ DSL。
---

# CLI リファレンス — `hsync`

`hsync` は HistorySync の **ヘッドレス CLI** です。GUI なしでアプリケーションのすべての機能を提供し、定期タスク、スクリプト、CI 環境に最適です。

---

## グローバルオプション

すべてのコマンドおよびサブコマンドで使用できるオプションです。

| フラグ | 短縮形 | 説明 |
|---|---|---|
| `--version` | | バージョンを表示して終了 |
| `--config-dir PATH` | | カスタムの設定・データディレクトリを使用 |
| `--portable` | | `hsync` バイナリのそばにすべてのデータを保存 |
| `--verbose` | `-v` | デバッグレベルのログを有効化 |
| `--quiet` | `-q` | 進捗出力を抑制し、エラーのみ stderr に出力 |
| `--no-color` | | ANSI カラーを無効化（環境変数 `NO_COLOR` でも可） |
| `--dry-run` | | 何も書き込まずに検出・検証のみ実行 |

---

## クラシックアクションフラグ

サブコマンド不要で使用できる、ワンショットアクション用フラグです。

### `-s` / `--sync` — ブラウザ履歴を取得

ブラウザの履歴をローカルデータベースにインポートします。

```bash
hsync -s
hsync --sync

# 特定のブラウザのみ同期
hsync -s --browsers chrome,firefox

# 30分ごとに繰り返し同期（ウォッチモード）
hsync -s -w 30
```

**同期オプション：**

| フラグ | 説明 |
|---|---|
| `--browsers LIST` | カンマ区切りのブラウザタイプ（デフォルト：検出されたすべて）。例: `chrome,firefox,edge` |
| `-w MINUTES` / `--watch MINUTES` | `MINUTES` 分ごとに同期を繰り返す。<kbd>Ctrl</kbd>+<kbd>C</kbd> で停止。 |

### `-b` / `--backup` — WebDAV バックアップ

ローカルデータベースの圧縮スナップショットを WebDAV にアップロードします。

```bash
hsync -b
hsync --backup

# 同期してからバックアップを一度に実行
hsync -sb
```

!!! note "事前に WebDAV の設定が必要です"
    `--backup` を使用する前に `hsync config set webdav.enabled true` を実行し、URL、ユーザー名、パスワードを設定してください。

<a id="export"></a>

### `-e FILE` / `--export FILE` — 履歴をエクスポート

ブラウジング履歴をファイルにエクスポートします。形式はファイル拡張子から自動判定されます。

```bash
# CSV への基本エクスポート
hsync -e history.csv

# フィルターを指定して JSON にエクスポート
hsync -e history.json --keyword python --after 2024-01-01

# ファビコン埋め込み付き HTML レポート
hsync -e report.html --format html --embed-icons

# ドメインでフィルタリング
hsync -e out.csv --domain github.com --domain stackoverflow.com

# カラムをカスタマイズ
hsync -e out.csv --columns title,url,visit_time,browser_type

# 正規表現キーワードフィルター
hsync -e out.json --keyword "^https://github" --regex

# 日付範囲の指定
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**エクスポートオプション：**

| フラグ | 説明 |
|---|---|
| `--format FMT` | `csv` \| `json` \| `html`（デフォルト：拡張子から推定） |
| `--columns COLS` | カンマ区切りのカラム名。使用可能: `id`, `title`, `url`, `visit_time`, `visit_count`, `browser_type`, `profile_name`, `domain`, `metadata`, `typed_count`, `first_visit_time`, `transition_type`, `visit_duration` |
| `--embed-icons` | ファビコンを Base64 データ URI として埋め込む（HTML エクスポートのみ） |
| `--keyword TEXT` | 全文キーワードフィルター |
| `--regex` | `--keyword` を Python 正規表現として扱う |
| `--browser TYPE` | ブラウザタイプでフィルター（例: `chrome`, `firefox`, `edge`） |
| `--after DATE` | `YYYY-MM-DD` 以降のレコードを含める（その日を含む） |
| `--before DATE` | `YYYY-MM-DD` 以前のレコードを含める（その日を含む） |
| `--domain HOST` | 特定ドメインにフィルター。繰り返し指定可能: `--domain a.com --domain b.com` |

### `-S` / `--status` — データベース統計

データベースの統計情報を表示します。

```bash
hsync -S
hsync --status

# 機械可読な JSON 形式
hsync -S --json

# スクリプト向けの簡潔な1行表示
hsync -S -q
```

**出力例：**
```
データベース状態
──────────────────────────────────────────────
     パス          :  /home/user/.config/HistorySync/history.db
     サイズ        :  124.3 MB
     レコード数    :  1,482,037
     ドメイン数    :  8,421
     FTS インデックス :  31.2 MB
     ブラウザ      :  chrome, firefox, edge, brave
     最終同期      :  2026-05-09 14:32:07
     最終バックアップ :  2026-05-09 12:00:00
```

### `-i` / `--interactive` — ガイド付きメニュー

インタラクティブなターミナルメニューを起動します — 初めて使用する方に最適です。

```bash
hsync -i
hsync --interactive
```

---

## サブコマンド

### `search` — 履歴を検索

構造化クエリ構文で履歴レコードを検索します。

```bash
# 最新の 20 件を表示
hsync search

# 最新の 100 件を表示
hsync search --limit 100

# シンプルなキーワード検索
hsync search python

# キーボードナビゲーション付きのインタラクティブモード
hsync search -i

# 構造化クエリ
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**オプション：**

| フラグ | デフォルト | 説明 |
|---|---|---|
| `--limit N` | `20` | 最大結果数 |
| `--format FMT` | `table` | 出力形式: `table` \| `json` \| `tsv` \| `csv` |
| `--columns COLS` | `title,url,visit_time,browser_type` | 表示するカラム |
| `--open` | | 最初の結果 URL をデフォルトブラウザで開く |
| `-i` / `--interactive` | | インタラクティブなキーボードナビゲーションモード |

---

<a id="query-dsl"></a>

### クエリ DSL

`search` サブコマンドと GUI の検索バーは、どちらも豊富なクエリ言語をサポートしています。

#### キーワード検索

通常の単語でタイトルと URL にまたがって検索します：
```
python async
"完全一致フレーズ"
react -tutorial         # 特定の単語を除外
```

#### トークンフィルター

| トークン | 例 | 説明 |
|---|---|---|
| `domain:` | `domain:github.com` | ドメインでフィルター |
| `title:` | `title:python` | ページタイトルのみ検索 |
| `url:` | `url:github` | URL のみ検索 |
| `after:` | `after:2024-01-01` | 日付範囲の開始（その日を含む） |
| `before:` | `before:2024-12-31` | 日付範囲の終了（その日を含む） |
| `browser:` | `browser:chrome` | ブラウザタイプでフィルター |
| `device:` | `device:laptop` | デバイス名または UUID でフィルター |
| `is:bookmarked` | `is:bookmarked` | ブックマーク済みレコードのみ |
| `has:note` | `has:note` | メモ付きレコードのみ |
| `tag:` | `tag:work` | タグでブックマークをフィルター |

#### トークンの組み合わせ

トークンとキーワードは自由に組み合わせることができます：
```
domain:arxiv.org after:2024-01-01 deep learning
is:bookmarked tag:work project management
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — WebDAV から復元

WebDAV バックアップからデータベースを復元します。

```bash
# バックアップ一覧を表示して対話的に選択
hsync restore

# 最新のバックアップを自動的に復元（マージ）
hsync restore --latest

# 利用可能なバックアップを JSON 形式で一覧表示
hsync restore --list

# 置き換えモード：ローカルデータベースを完全に上書き
hsync restore --replace

# ファビコンキャッシュも復元する
hsync restore --latest --restore-favicons
```

**オプション：**

| フラグ | 説明 |
|---|---|
| `--latest` | プロンプトなしで最新のバックアップを自動的に使用 |
| `--list` | 利用可能なバックアップを JSON 形式で一覧表示して終了 |
| `--replace` | 置き換えモード：マージではなくローカルデータベースを上書き |
| `--restore-favicons` | バックアップからファビコンキャッシュも復元 |

!!! info "マージと置き換え"
    デフォルトの動作は、バックアップのレコードをローカルデータベースと**マージ**します — 両方のレコードが保持され、重複は除去されます。ローカルデータをバックアップで完全に上書きしたい場合のみ `--replace` を使用してください。

---

### `db` — データベースのメンテナンス

```bash
# VACUUM + ANALYZE（断片化したスペースを回収）
hsync db vacuum

# 全文検索インデックスを再構築
hsync db rebuild-fts

# すべてのレコードのドメイン名を正規化
hsync db normalize

# データベース統計を表示
hsync db stats
hsync db stats --json
```

**サブコマンド：**

| サブコマンド | 説明 |
|---|---|
| `vacuum` | `VACUUM` と `ANALYZE` を実行 — 断片化したスペースを回収し、クエリプランナーの統計を更新 |
| `rebuild-fts` | FTS5 全文検索インデックスを再構築 — 検索が遅い、または結果が欠けている場合に使用 |
| `normalize` | すべてのレコードのドメイン名を再計算（未加工のデータベースインポート後に有用） |
| `stats` | `hsync -S` のエイリアス |

---

### `config` — 設定の管理

GUI を開かずに設定値を読み書きします。

```bash
# すべてのキーと現在の値を一覧表示
hsync config list

# 単一の値を読み取る
hsync config get webdav.url

# 値を書き込む
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language ja_JP
```

**設定可能なキー：**

| キー | 型 | 説明 |
|---|---|---|
| `webdav.enabled` | bool | WebDAV バックアップを有効化 |
| `webdav.url` | string | WebDAV サーバーの URL |
| `webdav.username` | string | WebDAV ユーザー名 |
| `webdav.remote_path` | string | バックアップ用リモートパス（デフォルト: `/HistorySync/`） |
| `webdav.max_backups` | int | 保持するバックアップ数（デフォルト: `10`） |
| `webdav.verify_ssl` | bool | SSL 証明書を検証（デフォルト: `true`） |
| `webdav.auto_backup` | bool | スケジュール自動バックアップを有効化 |
| `webdav.backup_favicons` | bool | バックアップにファビコンキャッシュを含める |
| `scheduler.auto_sync_enabled` | bool | ブラウザの自動同期を有効化 |
| `scheduler.sync_interval_hours` | int | 同期間隔（時間単位） |
| `scheduler.auto_backup_enabled` | bool | スケジュール WebDAV バックアップを有効化 |
| `scheduler.auto_backup_interval_hours` | int | バックアップ間隔（時間単位） |
| `scheduler.launch_on_startup` | bool | ログイン時に HistorySync を起動 |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | UI 言語コード（例: `ja_JP`）。空の場合は自動検出。 |

---

<a id="update-check-for-updates"></a>

### `update` — アップデートを確認

現在のプラットフォームとインストール形態で、新しい HistorySync リリースが利用可能かどうかを確認します。

```bash
# 人間向けの出力
hsync update

# 機械向けの JSON 出力
hsync update --json

# 既定以外のリリースチャネルを確認
hsync update --channel beta
hsync update --channel nightly
```

**オプション:**

| フラグ | 説明 |
|---|---|
| `--json` | スクリプトや CI 向けに更新メタデータを JSON で出力 |
| `--channel CH` | 今回の確認に使うチャネルを上書き: `stable` \| `beta` \| `nightly` |

**動作:**

- desktop アプリと同じ、プラットフォーム依存の更新メタデータを使用します。
- 主要な更新 API が利用できない場合は GitHub Releases のメタデータにフォールバックします。
- インストーラ、ポータブル ZIP、AppImage、`.dmg` など、現在のインストール形態に合ったアーティファクトを選びます。

!!! note "CLI は確認のみ"
    `hsync update` は更新の有無とメタデータを報告するだけです。実際のガイド付きダウンロードとインストールは、desktop アプリの **設定 → 更新** から行います。

---

## シェル補完

`hsync` は `argcomplete` によるシェル補完をサポートしています。

=== "Bash"
    ```bash
    # グローバルに一度だけ設定
    activate-global-python-argcomplete --user

    # または ~/.bashrc に追加：
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # ~/.zshrc に追加：
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## スクリプトと CI の使用例

```bash
# 同期して結果を確認
hsync -s -q && echo "sync ok" || echo "sync failed"

# ステータス JSON を jq に渡す
hsync -S --json | jq .record_count

# ログをファイルに出力
hsync -s --no-color 2>&1 | tee sync.log

# 同期 + バックアップ（cron 向け）
hsync -sb -q

# 過去 1 週間の GitHub ページを JSON にエクスポート
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"

# スケジュールタスク向けのヘッドレス同期（Python のメインモジュールから）
python -m src.main --headless --sync
```

---

## 終了コード

| コード | 意味 |
|---|---|
| `0` | 成功 |
| `1` | エラー（詳細は stderr に出力） |
