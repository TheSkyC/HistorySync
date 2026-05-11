---
title: コントリビュート
description: HistorySync コントリビューター向けの開発環境のセットアップ、コードスタイル、DCO サインオフ、プルリクエストのワークフロー。
---

# HistorySync へのコントリビュート

コントリビュートへの関心をお寄せいただきありがとうございます！バグ修正、新しいブラウザエクストラクター、ドキュメントの改善、翻訳、テストカバレッジの拡充を特に歓迎します。

---

## はじめに

1. **[Issues](https://github.com/TheSkyC/HistorySync/issues) を確認** — `good first issue` や `help wanted` などのラベルを探してみてください。
2. 重複作業を避けるために、大きな作業を始める前に **Issue にコメント** してください。
3. 小さな修正（タイポ、1行バグ）については、事前の Issue なしに直接 PR を開いて構いません。

---

## 開発環境のセットアップ

### 必要条件

| ツール | 必要なバージョン |
|---|---|
| Python | **3.12** 推奨（CI 環境と一致） |
| Git | 最新バージョンであれば何でも可 |

> HistorySync は Python 3.10 以上をサポートしていますが、コントリビュート時はリンティング、テスト、ロックされた依存関係の環境に合わせるため **3.12** を使用してください。

### 手順

```bash
# 1. GitHub でリポジトリをフォークし、フォークをクローン
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. 仮想環境を作成して有効化
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. ランタイム依存関係をインストール
pip install -r requirements.txt

# 4. 開発・テスト依存関係をインストール
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. （推奨）pre-commit フックをインストール
pre-commit install

# 6. セットアップを確認
python -m src.main --fresh
```

---

## コードスタイル

このプロジェクトはリンティングとフォーマットに **[Ruff](https://github.com/astral-sh/ruff)** を使用しています。設定は `ruff.toml` にあります。

```bash
# 問題をチェック
ruff check .

# 可能な場合は自動修正
ruff check . --fix

# コードをフォーマット
ruff format .

# すべての pre-commit フックを手動で実行
pre-commit run --all-files
```

**スタイル全般のメモ：**

- 編集しているファイルの既存パターンに従ってください。
- GUI コード（PySide6）とビジネスロジックを**厳密に分離**してください — サービスは Qt をインポートしてはなりません。
- 巧妙さより明確さを優先してください。
- パブリック API を変更する場合は、ドックストリングを追加または更新してください。

---

## テストの実行

```bash
# テストスイート全体を実行
pytest

# 特定のテストファイルを実行
pytest tests/test_chromium_extractor.py

# 詳細な出力
pytest -v

# カバレッジ付き（requirements-test.txt に含まれる pytest-cov が必要）
pytest --cov=src --cov-report=term-missing

# CI と同じリントチェック
ruff check src/ tests/
ruff format --check src/ tests/
```

PR がマージされる前に、すべてのテストがパスしている必要があります。新機能を追加する場合は、対応するテストも含めてください。

---

## コミットガイドライン

明確な命令形のコミットメッセージを使用してください：

```
<type>(<scope>): <subject>
```

**例：**
```
fix(extractor): handle missing WAL file during Chromium extraction
feat(browser): add Arc browser support on macOS
docs(webdav): document merge behaviour
test(search): add unit tests for query DSL parser
chore(dev): update Ruff to 0.15
```

**タイプ:** `fix`、`feat`、`refactor`、`docs`、`test`、`chore`、`perf`、`style`、`ci`、`build`

**ルール：**
- 件名は 72 文字以内。
- 小文字の命令形動詞を使用する（`add`、`fix`、`remove` — `added`、`fixes` ではなく）。
- 明らかでない変更については、*なぜ* そうしたのかを本文で説明してください。

---

## Developer Certificate of Origin（DCO）

**すべてのコミットにサインオフが必要です。署名されていないコミットを含む PR はマージされません。**

```bash
git commit -s -m "fix: handle missing WAL file"
# 以下が追加されます: Signed-off-by: Your Name <your@email.com>
```

Git の identity が設定されていることを確認してください：
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### サインオフを忘れた場合は？

```bash
# 直前のコミットのみ
git commit --amend --no-edit --signoff
git push --force-with-lease

# 複数のコミット（直近 N 件）
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## プルリクエストのワークフロー

1. `main` から**ブランチを作成**します：
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **変更を加えます** — コミットは焦点を絞ってアトミックに保ちましょう。

3. ローカルで**テストとリント**を実行します。

4. `main` に対して **PR をプッシュして開きます**：
   ```bash
   git push origin your-branch-name
   ```

5. PR のルールに従ってください：
   - PR ごとに 1 つの変更または関連する一連の変更のみ。
   - *何が*変更されたのか、*なぜ*変更されたのかを明確に説明する。
   - `Closes #123` で関連 Issue をリンクする。
   - UI の変更にはスクリーンショット・録画を添付する。
   - すべてのコミットにサインオフが必要。

6. **レビューのフィードバックに迅速に対応**してください。

---

## 求めていること

**特に歓迎：**

- **新しいブラウザエクストラクター** — Chromium/Firefox フォークの追加サポート。
- **バグ修正** — 特にプラットフォーム固有の問題（macOS パス、Linux 権限、Windows UAC）。
- **パフォーマンスの改善** — クエリの最適化、取得速度、メモリ使用量。
- **UI/UX の改善** — アクセシビリティ、キーボードナビゲーション、テーマの一貫性。
- **テストカバレッジ** — 現在テストされていないコードパスへの新しいテスト。
- **ドキュメント** — このサイトの改善、インラインのドックストリングの追加、タイポの修正。
- **翻訳** — `src/resources/locales/` 以下の `.po` ファイルの更新。

**事前に相談してください（コーディング前に Issue を開いてください）：**

- 大きなアーキテクチャの変更。
- 新しいサードパーティ依存関係。
- WebDAV 同期プロトコルまたはデータベーススキーマへの変更。

---

## セキュリティの脆弱性

**セキュリティの脆弱性には公開 Issue を開かないでください。**

**0x4fe6@gmail.com** にメールで非公開に報告してください。説明、再現手順、潜在的な影響を含めてください。72 時間以内に返信します。

---

## ライセンス

プルリクエストを提出することにより、あなたのコントリビュートが **Apache 2.0** でライセンスされることに同意し、すべてのコミットの DCO を証明することになります。
