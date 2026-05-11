---
title: インストール
description: Windows、macOS、Linux への HistorySync のインストール方法 — ビルド済みパッケージとソースからのインストール両方に対応。
---

# インストール

HistorySync は **Windows**、**macOS**、**Linux** で動作します。ご自身に合った方法をお選びください。

---

## ビルド済みパッケージ（推奨）

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** ページから最新リリースをダウンロードしてください。

=== "Windows"

    | パッケージ | 備考 |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | フルインストーラー。スタートメニューへの追加と自動起動の設定が可能 |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | ポータブル版 — 任意の場所に展開してそのまま実行可能、インストール不要 |

    インストーラーを実行し、画面の指示に従ってください。追加の依存関係は必要ありません。

=== "macOS"

    | パッケージ | 備考 |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | ドラッグ＆ドロップでインストール |

    1. `.dmg` ファイルを開きます。
    2. **HistorySync** を `アプリケーション` フォルダにドラッグします。
    3. 初回起動時に macOS がセキュリティの警告を表示することがあります。**開く** をクリックして続行してください。

    !!! note "アクセシビリティの権限"
        グローバルホットキー `Ctrl+Shift+H` を使用するには **アクセシビリティ** の権限が必要です。初回使用時に macOS がプロンプトを表示します。**システム設定 → プライバシーとセキュリティ → アクセシビリティ** で権限を付与してください。

=== "Linux"

    | パッケージ | 備考 |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | 最新の Linux ディストリビューションで動作 |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | 汎用 tar アーカイブ、あらゆる Linux ディストリビューションに対応 |
    | `historysync_X.Y.Z_amd64.deb` | Debian/Ubuntu 系ディストリビューション向け |

    **AppImage:**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb`:**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # 不足している依存関係を修正
    ```

    !!! warning "Linux/Wayland でのグローバルホットキー"
        `pynput` を使用したグローバルホットキーは **Wayland では非対応** です。Wayland セッションでは `Ctrl+Shift+H` のオーバーレイショートカットは機能しません。回避策として `--quick` とシステムレベルのキーバインドを組み合わせてご利用ください（[キーボードショートカット](keyboard-shortcuts.md) を参照）。

---

## ソースからインストール

最新の開発コードを実行したい場合や、プロジェクトにコントリビュートしたい場合はこの方法を使用してください。

### 必要条件

- **Python 3.10 以上**（Python 3.12 推奨 — CI 環境と一致）
- **Git**

### 手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. 仮想環境を作成して有効化（強く推奨）
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. ランタイム依存関係をインストール
pip install -r requirements.txt

# 4. アプリケーションを起動
python -m src.main
```

### `hsync` CLI のインストール（オプション）

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** ページからビルド済みの `hsync` バイナリをダウンロードできます：

| パッケージ | プラットフォーム |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Windows インストーラー |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows ポータブル |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS（Apple Silicon） |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

または、ヘッドレス CLI は Python で直接起動できます：

```bash
python -m src.cli --help
```

`PATH` 上に `hsync` コマンドとしてインストールするには：

```bash
# シンプルなラッパースクリプトを作成（Linux / macOS）
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## インストールの確認

GUI を起動してタイトルバーでバージョン番号を確認するか、次のコマンドを実行してください：

```bash
# GUI
python -m src.main --version

# CLI
python -m src.cli --version
# またはインストール済みの場合：
hsync --version
```

---

## アップグレード

Releases ページから新しいバイナリをダウンロードして、既存のバイナリと置き換えるだけです。HistorySync は設定とデータベースをアプリケーションバイナリとは別の場所に保存するため、アップグレードによってデータが変更されることはありません。

デフォルトのデータ保存場所：

| プラットフォーム | ディレクトリ |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

`--config-dir` オプションでこの場所を変更したり、`--portable` モードを使用してすべてのデータを実行ファイルのそばに保存することもできます。

---

## アンインストール

1. アプリケーションのバイナリ・AppImage・パッケージを削除します。
2. すべてのブラウジングデータと設定を削除する場合は、上記のデータディレクトリも任意で削除してください。

!!! warning
    データディレクトリの削除は元に戻せません。履歴を保持したい場合は、先にデータベースをバックアップしてください。
