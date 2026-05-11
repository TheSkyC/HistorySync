---
title: WebDAV Setup
description: Step-by-step configuration for WebDAV cloud backup in HistorySync — covers Nextcloud, Synology, Alist, Nginx, and more.
---

# WebDAV Setup

HistorySync uses **WebDAV** to back up and restore your browsing history database to and from the cloud. Any WebDAV-compatible server works — this page covers the most popular options.

---

## How It Works

1. HistorySync **zips** your `history.db` (and optionally the favicon cache).
2. It uploads the archive to the remote WebDAV path using **atomic streaming** — the old backup is only replaced after the upload succeeds.
3. Up to `max_backups` copies are kept; older ones are pruned automatically.
4. When restoring, HistorySync downloads the chosen backup and **merges** its records with your local database (or replaces it in `--replace` mode).

---

## Quick Configuration (GUI)

1. Open **Settings → WebDAV Cloud Backup**.
2. Fill in the fields:
   - **URL** — full URL including path, e.g. `https://cloud.example.com/remote.php/dav/files/alice/`
   - **Username / Password** — your WebDAV credentials
   - **Remote Path** — subfolder for backups (default: `HistorySync/`)
   - **Max Backups** — how many snapshots to keep (default: 10)
3. Click **Test Connection**.
4. Enable **Auto Backup** and set an interval.

---

## Quick Configuration (CLI)

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"

# Set the password in the GUI or edit config.json if you need to preseed it.
# The hsync config command does not currently expose a webdav.password key.

hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# Test it
hsync -b
```

---

## Provider-Specific Guides

### Nextcloud

Nextcloud's WebDAV URL format:
```
https://<your-nextcloud-domain>/remote.php/dav/files/<username>/
```

1. Log in to Nextcloud.
2. Go to **Settings → Security → Devices & sessions** and create an **App Password** (recommended over your main password).
3. In HistorySync, use the URL above with your Nextcloud username and app password.
4. Optional: create a dedicated folder first (e.g. `HistorySync`) and set `remote_path` to `HistorySync/`.

!!! tip "Nextcloud app password"
    Using an app password means HistorySync cannot access anything else in your account if the credential leaks. Highly recommended.

---

### Synology DSM (QuickConnect / Direct)

**Enable WebDAV in Synology DSM:**

1. Open **Control Panel → File Services → WebDAV**.
2. Enable **WebDAV** or **WebDAV HTTPS** (HTTPS is strongly recommended).
3. Note the port (default: 5005 for HTTP, 5006 for HTTPS).

**HistorySync URL format:**
```
https://<synology-ip-or-quickconnect>:5006/
```

Set the remote path to a shared folder you have write access to, e.g. `homes/alice/HistorySync/`.

!!! warning "Self-signed certificates"
    Synology uses a self-signed certificate by default. Either:
    - Install a Let's Encrypt certificate in DSM (recommended), or
    - Set `webdav.verify_ssl` to `false` (`hsync config set webdav.verify_ssl false`)

---

### AList (S3 / OneDrive / Google Drive via WebDAV)

[AList](https://alist.nn.ci/) is an open-source file manager that exposes many cloud storage providers as WebDAV.

```
https://<your-alist-domain>/dav/
```

Use your AList username and password. Set `remote_path` to a path within your configured storage, e.g. `OneDrive/HistorySync/`.

---

### Nginx WebDAV

If you self-host an Nginx WebDAV server:

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

HistorySync URL: `https://<your-domain>/dav/`

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

### Cloudflare R2 (via rclone)

R2 does not expose a native WebDAV endpoint, but you can proxy it with `rclone serve webdav`:

```bash
rclone serve webdav r2:my-bucket --addr :8080 --user alice --pass secret
```

Then set `webdav.url` to `http://localhost:8080/`.

---

## Troubleshooting

### "Connection refused" / "Timeout"

- Check the URL — make sure the protocol (`https://`) and port are correct.
- Verify the server is reachable from your machine: `curl -u user:pass https://your-server/dav/`.

### "401 Unauthorized"

- Double-check username and password.
- For Nextcloud: use an **App Password**, not your login password.
- Confirm the account has write permission to the remote path.

### "SSL: CERTIFICATE_VERIFY_FAILED"

- The server is using a self-signed or expired certificate.
- Either fix the certificate, or set `hsync config set webdav.verify_ssl false` (only for trusted internal networks).

### Backup succeeds but restore shows no backups

- Check `webdav.remote_path` — it must match the path used when backing up.
- Run `hsync restore --list` to see what `hsync` finds on the server.

### Large backup takes too long / times out

- HistorySync uses streaming uploads, so memory usage stays low regardless of file size.
- If the server has a small request timeout, increase it (e.g. Nginx `client_body_timeout 300s;`).
- Consider running backups on a schedule (`-w` flag or `scheduler.auto_backup_interval_hours`) rather than manually.

---

## Security Notes

- WebDAV **credentials are stored encrypted** on disk using HKDF-derived subkeys. See [Security Architecture](../dev/security.md).
- Always use **HTTPS** — plain HTTP exposes your credentials and history data in transit.
- Prefer app-specific passwords over your main account password where the provider supports it.
- Set `max_backups` to a small number if storage is limited. Default is **10**.
