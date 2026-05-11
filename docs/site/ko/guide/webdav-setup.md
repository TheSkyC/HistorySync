---
title: WebDAV 설정
description: HistorySync의 WebDAV 클라우드 백업 단계별 설정 가이드 — Nextcloud, Synology, Alist, Nginx 등을 다룹니다.
---

# WebDAV 설정

HistorySync는 **WebDAV**를 사용하여 브라우저 기록 데이터베이스를 클라우드에 백업하고 복원합니다. WebDAV와 호환되는 서버라면 무엇이든 사용할 수 있으며, 이 페이지에서는 가장 많이 사용되는 옵션들을 다룹니다.

---

## 작동 방식

1. HistorySync가 `history.db`(및 선택적으로 파비콘 캐시)를 **압축**합니다.
2. **원자적 스트리밍** 방식으로 원격 WebDAV 경로에 아카이브를 업로드합니다 — 업로드가 성공한 후에만 기존 백업이 교체됩니다.
3. 최대 `max_backups`개의 복사본이 유지되며, 오래된 것은 자동으로 삭제됩니다.
4. 복원 시 HistorySync가 선택된 백업을 다운로드하고 로컬 데이터베이스와 레코드를 **병합**합니다 (`--replace` 모드에서는 교체).

---

## 빠른 설정 (GUI)

1. **설정 → WebDAV 클라우드 백업**을 엽니다.
2. 다음 필드를 입력합니다:
   - **URL** — 경로를 포함한 전체 URL, 예: `https://cloud.example.com/remote.php/dav/files/alice/`
   - **사용자명 / 비밀번호** — WebDAV 자격 증명
   - **원격 경로** — 백업용 하위 폴더 (기본값: `HistorySync/`)
   - **최대 백업 수** — 유지할 스냅샷 수 (기본값: 10)
3. **연결 테스트**를 클릭합니다.
4. **자동 백업**을 활성화하고 간격을 설정합니다.

---

## 빠른 설정 (CLI)

```bash
hsync config set webdav.enabled true
hsync config set webdav.url "https://cloud.example.com/remote.php/dav/files/alice/"
hsync config set webdav.username "alice"

# 비밀번호는 GUI에서 설정하거나, 필요하면 config.json을 미리 채우세요.
# hsync config는 현재 webdav.password 키를 노출하지 않습니다.

hsync config set webdav.remote_path "HistorySync/"
hsync config set webdav.max_backups 7
hsync config set webdav.auto_backup true
hsync config set scheduler.auto_backup_enabled true
hsync config set scheduler.auto_backup_interval_hours 12

# 테스트
hsync -b
```

---

## 제공업체별 가이드

### Nextcloud

Nextcloud의 WebDAV URL 형식:
```
https://<your-nextcloud-domain>/remote.php/dav/files/<username>/
```

1. Nextcloud에 로그인합니다.
2. **설정 → 보안 → 기기 및 세션**으로 이동하여 **앱 비밀번호**를 생성합니다 (메인 비밀번호 대신 권장).
3. HistorySync에서 위의 URL과 Nextcloud 사용자명, 앱 비밀번호를 사용합니다.
4. 선택 사항: 전용 폴더(예: `HistorySync`)를 먼저 만들고 `remote_path`를 `HistorySync/`로 설정합니다.

!!! tip "Nextcloud 앱 비밀번호"
    앱 비밀번호를 사용하면 자격 증명이 유출되더라도 HistorySync가 계정의 다른 항목에 접근할 수 없습니다. 강력히 권장합니다.

---

### Synology DSM (QuickConnect / 직접 연결)

**Synology DSM에서 WebDAV 활성화:**

1. **제어판 → 파일 서비스 → WebDAV**를 엽니다.
2. **WebDAV** 또는 **WebDAV HTTPS**를 활성화합니다 (HTTPS 강력 권장).
3. 포트를 확인합니다 (기본값: HTTP 5005, HTTPS 5006).

**HistorySync URL 형식:**
```
https://<synology-ip-or-quickconnect>:5006/
```

원격 경로를 쓰기 권한이 있는 공유 폴더로 설정하세요, 예: `homes/alice/HistorySync/`.

!!! warning "자체 서명 인증서"
    Synology는 기본적으로 자체 서명 인증서를 사용합니다. 다음 중 하나를 선택하세요:
    - DSM에 Let's Encrypt 인증서 설치 (권장), 또는
    - `webdav.verify_ssl`을 `false`로 설정 (`hsync config set webdav.verify_ssl false`)

---

### AList (WebDAV를 통한 S3 / OneDrive / Google Drive)

[AList](https://alist.nn.ci/)는 많은 클라우드 스토리지 제공업체를 WebDAV로 노출하는 오픈 소스 파일 관리자입니다.

```
https://<your-alist-domain>/dav/
```

AList 사용자명과 비밀번호를 사용하세요. `remote_path`를 구성된 스토리지 내 경로로 설정합니다, 예: `OneDrive/HistorySync/`.

---

### Nginx WebDAV

자체 Nginx WebDAV 서버를 운영하는 경우:

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

### Cloudflare R2 (rclone을 통해)

R2는 네이티브 WebDAV 엔드포인트를 제공하지 않지만, `rclone serve webdav`로 프록시할 수 있습니다:

```bash
rclone serve webdav r2:my-bucket --addr :8080 --user alice --pass secret
```

그런 다음 `webdav.url`을 `http://localhost:8080/`으로 설정합니다.

---

## 문제 해결

### "Connection refused" / "Timeout"

- URL을 확인하세요 — 프로토콜(`https://`)과 포트가 올바른지 확인합니다.
- 서버에 접근 가능한지 확인합니다: `curl -u user:pass https://your-server/dav/`.

### "401 Unauthorized"

- 사용자명과 비밀번호를 다시 확인하세요.
- Nextcloud: 로그인 비밀번호 대신 **앱 비밀번호**를 사용하세요.
- 계정이 원격 경로에 쓰기 권한을 가지고 있는지 확인합니다.

### "SSL: CERTIFICATE_VERIFY_FAILED"

- 서버가 자체 서명 또는 만료된 인증서를 사용하고 있습니다.
- 인증서를 수정하거나, `hsync config set webdav.verify_ssl false`로 설정하세요 (신뢰할 수 있는 내부 네트워크 전용).

### 백업은 성공하지만 복원 시 백업이 표시되지 않음

- `webdav.remote_path`를 확인하세요 — 백업 시 사용한 경로와 일치해야 합니다.
- `hsync restore --list`를 실행하여 서버에서 `hsync`가 찾는 내용을 확인합니다.

### 대용량 백업이 너무 오래 걸리거나 타임아웃 발생

- HistorySync는 스트리밍 업로드를 사용하므로 파일 크기에 관계없이 메모리 사용량이 낮습니다.
- 서버의 요청 타임아웃이 짧다면 늘리세요 (예: Nginx `client_body_timeout 300s;`).
- 수동 실행 대신 예약 백업을 사용하는 것을 고려하세요 (`-w` 플래그 또는 `scheduler.auto_backup_interval_hours`).

---

## 보안 참고 사항

- WebDAV **자격 증명은 HKDF 파생 서브키를 사용하여 디스크에 암호화되어 저장**됩니다. [보안 아키텍처](../dev/security.md)를 참조하세요.
- **HTTPS**를 항상 사용하세요 — 일반 HTTP는 전송 중인 자격 증명과 기록 데이터를 노출합니다.
- 제공업체가 지원하는 경우 메인 계정 비밀번호 대신 앱별 비밀번호를 사용하는 것을 권장합니다.
- 스토리지가 제한적인 경우 `max_backups`를 작은 값으로 설정하세요. 기본값은 **5**입니다.
