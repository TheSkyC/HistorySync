---
title: WebDAV 設定
description: HistorySync の WebDAV クラウドバックアップを設定するためのステップバイステップガイド — Nextcloud、Synology、Alist、Nginx などに対応。
---

# WebDAV 設定

HistorySync は **WebDAV** を使用して、ブラウジング履歴データベースをクラウドにバックアップ・復元します。WebDAV に対応したサーバーであればどれでも使用できます。このページでは、よく使われるプロバイダーの設定手順を説明します。

---

## 仕組み

1. HistorySync が `history.db`（オプションでファビコンキャッシュも）を **ZIP** 圧縮します。
2. **アトミックストリーミング** でアーカイブをリモートの WebDAV パスにアップロードします — アップロードが成功した後にのみ古いバックアップが置き換えられます。
3. 最大 `max_backups` 件のコピーが保持され、古いものは自動的に削除されます。
4. 復元時、HistorySync は選択したバックアップをダウンロードし、そのレコードをローカルデータベースと**マージ**します（`--replace` モードの場合は置き換え）。

---

## クイック設定（GUI）

1. **設定 → WebDAV クラウドバックアップ** を開きます。
2. 各フィールドを入力します：
   - **URL** — パスを含む完全な URL。例: `https://cloud.example.com/remote.php/dav/files/alice/`
   - **ユーザー名 / パスワード** — WebDAV の認証情報
   - **リモートパス** — バックアップ用サブフォルダー（デフォルト: `HistorySync/`）
   - **最大バックアップ数** — 保持するスナップショット数（デフォルト: 10）
3. **接続テスト** をクリックします。
4. **自動バックアップ** を有効にして間隔を設定します。

---

## クイック設定（CLI）

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"

# パスワードは GUI で設定するか、必要なら config.json を事前投入してください。
# hsync config では現在 webdav.password キーを公開していません。

hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# テスト実行
hsync -b
```

---

## プロバイダー別設定ガイド

### Nextcloud

Nextcloud の WebDAV URL の形式：
```
https://<your-nextcloud-domain>/remote.php/dav/files/<username>/
```

1. Nextcloud にログインします。
2. **設定 → セキュリティ → デバイスとセッション** に移動し、**アプリパスワード** を作成します（メインパスワードより推奨）。
3. HistorySync の URL に上記の形式を使用し、Nextcloud のユーザー名とアプリパスワードを入力します。
4. オプション：専用フォルダー（例: `HistorySync`）を先に作成し、`remote_path` を `HistorySync/` に設定します。

!!! tip "Nextcloud のアプリパスワード"
    アプリパスワードを使用すると、認証情報が漏洩した場合でも HistorySync はアカウントの他の部分にアクセスできません。強く推奨します。

---

### Synology DSM（QuickConnect / ダイレクト）

**Synology DSM で WebDAV を有効化する方法：**

1. **コントロールパネル → ファイルサービス → WebDAV** を開きます。
2. **WebDAV** または **WebDAV HTTPS** を有効にします（HTTPS を強く推奨）。
3. ポートを確認します（デフォルト: HTTP は 5005、HTTPS は 5006）。

**HistorySync の URL 形式：**
```
https://<synology-ip-or-quickconnect>:5006/
```

書き込み権限のある共有フォルダーへのリモートパスを設定します。例: `homes/alice/HistorySync/`

!!! warning "自己署名証明書"
    Synology はデフォルトで自己署名証明書を使用しています。次のいずれかの対応が必要です：
    - DSM で Let's Encrypt 証明書をインストールする（推奨）
    - `webdav.verify_ssl` を `false` に設定する（`hsync config set webdav.verify_ssl false`）

---

### AList（WebDAV 経由の S3 / OneDrive / Google Drive）

[AList](https://alist.nn.ci/) は多くのクラウドストレージプロバイダーを WebDAV として公開するオープンソースのファイルマネージャーです。

```
https://<your-alist-domain>/dav/
```

AList のユーザー名とパスワードを使用します。`remote_path` には設定済みストレージ内のパスを指定します。例: `OneDrive/HistorySync/`

---

### Nginx WebDAV

Nginx WebDAV サーバーをセルフホストする場合：

```nginx
location /dav/ {
    root /var/webdav;
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_ext_methods PROPFIND OPTIONS;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
    auth_basic "WebDAV";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

HistorySync の URL: `https://<your-domain>/dav/`

---

### Apache WebDAV

```apache
<Location /dav>
    DAV On
    AuthType Basic
    AuthName "WebDAV"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user
</Location>
```

---

### Cloudflare R2（rclone 経由）

R2 はネイティブ WebDAV エンドポイントを持ちませんが、`rclone serve webdav` でプロキシできます：

```bash
rclone serve webdav r2:my-bucket --addr :8080 --user alice --pass secret
```

`webdav.url` を `http://localhost:8080/` に設定します。

---

## トラブルシューティング

### 「接続が拒否されました」/ 「タイムアウト」

- URL を確認してください — プロトコル（`https://`）とポートが正しいことを確認します。
- マシンからサーバーに到達できるか確認します: `curl -u user:pass https://your-server/dav/`

### 「401 Unauthorized」

- ユーザー名とパスワードを再確認してください。
- Nextcloud の場合：ログインパスワードではなく **アプリパスワード** を使用してください。
- アカウントがリモートパスへの書き込み権限を持っているか確認してください。

### 「SSL: CERTIFICATE_VERIFY_FAILED」

- サーバーが自己署名証明書または期限切れ証明書を使用しています。
- 証明書を修正するか、`hsync config set webdav.verify_ssl false` を設定してください（信頼できる内部ネットワークのみ）。

### バックアップは成功するが、復元でバックアップが表示されない

- `webdav.remote_path` を確認してください — バックアップ時に使用したパスと一致している必要があります。
- `hsync restore --list` を実行して、`hsync` がサーバー上で何を検出するか確認してください。

### 大きなバックアップが時間がかかりすぎる / タイムアウトする

- HistorySync はストリーミングアップロードを使用しているため、ファイルサイズに関わらずメモリ使用量は少量です。
- サーバーのリクエストタイムアウトが短い場合は延長してください（例: Nginx の `client_body_timeout 300s;`）。
- 手動での実行よりも、スケジュール実行（`-w` フラグまたは `scheduler.auto_backup_interval_hours`）を検討してください。

---

## セキュリティについて

- WebDAV の **認証情報は HKDF 派生サブキーを使用して暗号化** されてディスクに保存されます。詳細は [セキュリティアーキテクチャ](../dev/security.md) をご参照ください。
- 認証情報と履歴データを保護するため、必ず **HTTPS** を使用してください。平文の HTTP は通信経路上で情報を公開します。
- プロバイダーがサポートしている場合、メインアカウントのパスワードよりもアプリ専用パスワードを使用してください。
- ストレージが限られている場合は `max_backups` を小さな値に設定してください。デフォルトは **5** です。
