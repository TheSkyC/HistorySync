---
title: 자주 묻는 질문 (FAQ)
description: HistorySync에 관한 자주 묻는 질문 — 설치, 동기화, 개인 정보 보호, WebDAV 등.
---

# 자주 묻는 질문

---

## 일반

### HistorySync가 내 브라우저 데이터를 제3자에게 업로드하나요?

**아니요.** HistorySync는 완전한 로컬 우선 방식입니다. 모든 기록 데이터는 **내 기기의** SQLite 데이터베이스에 저장됩니다. 유일한 네트워크 트래픽은 선택적인 WebDAV 백업뿐이며, 이는 *본인이* 직접 제어하는 서버(또는 자체 호스팅 서비스)로 전송됩니다. 분석, 원격 측정 또는 외부 호출은 절대 이루어지지 않습니다.

### 어떤 브라우저가 지원되나요?

HistorySync는 **30개 이상의 브라우저**를 기본 지원합니다:

**Chromium 기반:** Chrome, Edge, Brave, Vivaldi, Arc, Chromium, Opera, Opera GX, Yandex Browser, CentBrowser, Thorium 등.

**Firefox 기반:** Firefox, Firefox ESR, LibreWolf, Waterfox, Pale Moon, SeaMonkey, Basilisk.

**Safari:** macOS 전용.

**지역 특화 브라우저 (Windows/macOS/Linux):** QQ 브라우저, Sogou, UC 브라우저, Liebao, Maxthon, Twinkstar 등.

브라우저가 목록에 없다면 **설정 → 브라우저 → 사용자 지정 경로 추가**를 사용하여 수동으로 추가하거나, 스마트 스캔 기능을 시도해 보세요.

### 여러 컴퓨터에서 HistorySync를 사용할 수 있나요?

예! 각 기기에 HistorySync를 설치하고, 모든 기기에서 동일한 WebDAV 서버를 설정한 후 자동 동기화를 활성화하세요. 클라우드에서 복원하거나 자동 병합이 이루어질 때, 모든 기기의 레코드가 브라우저 타입, URL, 방문 타임스탬프를 기준으로 **지능적으로 중복 제거**됩니다.

---

## 동기화 및 추출

### 브라우저가 열려 있는 상태에서도 HistorySync가 작동하나요?

예. HistorySync는 **SQLite WAL(Write-Ahead Log) 스냅샷**을 사용합니다 — 읽기 전에 WAL 파일을 복사하므로 실행 중인 브라우저와 충돌이 발생하지 않습니다. 브라우저가 잠기거나 일시 중지되는 일은 없습니다.

### 동기화 후 일부 레코드가 누락된 이유는 무엇인가요?

몇 가지 가능한 원인이 있습니다:

- **사생활 보호/시크릿 브라우징** — 브라우저는 시크릿 기록을 디스크에 기록하지 않아 HistorySync가 볼 수 없습니다.
- **비활성화된 브라우저 프로필** — **설정 → 브라우저**에서 프로필이 비활성화되어 있지 않은지 확인하세요.
- **URL 필터링** — HistorySync는 내부 브라우저 URL(`chrome://`, `about:`, `file://` 등)과 차단 목록에 있는 도메인을 무시합니다.
- **첫 번째 동기화가 증분 방식** — **설정 → 유지 관리 → 전체 재동기화**를 시도하거나 GUI 시작 진입점 `python -m src.main --resync`를 사용해 모든 과거 레코드를 다시 읽어보세요.

### "전체 재동기화"란 무엇인가요?

일반 동기화는 **증분 방식**으로, 마지막 동기화 타임스탬프 이후의 레코드만 읽습니다. 전체 재동기화는 워터마크를 무시하고 모든 브라우저에서 모든 레코드를 다시 읽어 `visit_count`와 같이 변경되었을 수 있는 필드를 채웁니다. 언제든지 안전하게 실행할 수 있습니다 — 레코드는 중복 생성되지 않고 업서트(upsert)됩니다.

```bash
# GUI 시작 진입점(hsync CLI 아님)
python -m src.main --resync

# GUI에서: 설정 → 유지 관리 → 전체 재동기화
```

---

## 개인 정보 보호 및 보안

### 내 데이터는 어디에 저장되나요?

| 플랫폼 | 기본 위치 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

`--config-dir PATH`로 재정의하거나, `--portable` 모드를 사용하여 실행 파일 옆에 모든 것을 저장하세요.

### WebDAV 자격 증명은 어떻게 보호되나요?

자격 증명은 **절대 평문으로 저장되지 않습니다**. HistorySync는 `keyring`을 통해 OS 키체인에 저장된 마스터 키에서 HKDF를 사용하여 독립적인 암호화 및 인증 서브키를 파생시킵니다. 자세한 내용은 [보안 아키텍처](../dev/security.md)를 참조하세요.

### "소프트 숨기기" / 숨김 레코드란 무엇인가요?

소프트 숨기기는 레코드(또는 도메인의 모든 레코드)를 숨김으로 표시합니다 — 메인 기록 보기에서 사라지지만 데이터베이스에는 남아 있습니다. **기록 → 숨김 항목 표시**에서 확인할 수 있습니다. 민감한 페이지를 영구 삭제하지 않고 숨길 때 유용합니다.

### 도메인 차단 목록이란 무엇인가요?

차단 목록의 도메인은 **절대 가져오지 않으며**, 해당 도메인의 기존 레코드는 **영구적으로 삭제**됩니다. 레코드를 오른쪽 클릭한 후 **도메인 차단**을 선택하거나, **설정 → 개인 정보 보호 → 도메인 차단 목록**에서 목록을 관리하세요.

---

## WebDAV 및 클라우드 백업

### HistorySync와 호환되는 WebDAV 제공업체는 무엇인가요?

모든 표준 WebDAV 서버. 테스트된 서버: Nextcloud, Synology DSM, ownCloud, AList, Nginx WebDAV, Apache mod_dav, Caddy WebDAV. 제공업체별 안내는 [WebDAV 설정 가이드](webdav-setup.md)를 참조하세요.

### 백업은 몇 개나 유지되나요?

기본적으로 서버에 **10개의 백업**이 유지됩니다. 각 성공적인 업로드 후 오래된 것은 자동으로 삭제됩니다. `hsync config set webdav.max_backups N`으로 변경할 수 있습니다.

### "Connection refused" 오류로 백업이 실패했습니다 — 무엇을 확인해야 하나요?

1. WebDAV URL(프로토콜, 호스트명, 포트, 경로)을 확인합니다.
2. 사용자명과 비밀번호를 확인합니다 — Nextcloud의 경우 **앱 비밀번호**를 사용하세요.
3. 연결성을 테스트합니다: `curl -u user:pass https://your-server/dav/`.
4. 자체 서명 인증서를 사용하는 경우, `hsync config set webdav.verify_ssl false`를 설정하세요.

---

## 성능

### 수백만 건의 레코드에서 HistorySync가 느립니다 — 어떻게 해야 하나요?

다음 단계를 순서대로 시도해 보세요:

1. **`hsync db vacuum` 실행** — 단편화된 공간을 회수하고 쿼리 플래너 통계를 새로 고칩니다.
2. **`hsync db rebuild-fts` 실행** — 전체 텍스트 검색 인덱스를 재구축합니다.
3. 데이터베이스가 빠른 로컬 SSD에 있는지 확인하세요 — 네트워크 공유나 USB 드라이브는 피하세요.
4. 정규식 검색을 사용하는 경우 일반 키워드 검색으로 전환하는 것을 고려하세요 — 정규식은 SQL 푸시다운을 통해 더 빠르지만, 매우 복잡한 패턴은 여전히 느릴 수 있습니다.

### 데이터베이스는 얼마나 많은 디스크 공간을 사용하나요?

레코드 수와 저장된 페이지 메타데이터의 양에 따라 다릅니다. 대략적인 기준:

| 레코드 수 | 대략적인 크기 |
|---|---|
| 100,000 | ~20–40 MB |
| 500,000 | ~80–150 MB |
| 1,000,000 | ~150–300 MB |
| 5,000,000 | ~600 MB – 1.2 GB |

파일을 압축하려면 `hsync db vacuum`을 주기적으로 실행하세요.

---

## CLI (`hsync`)

### `hsync`를 시스템 명령으로 설치하려면 어떻게 하나요?

소스에서 실행하는 경우:
```bash
# Linux / macOS
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

사전 빌드 패키지를 사용하는 경우, 설치 프로그램이 일반적으로 `hsync`를 `PATH`에 자동으로 추가합니다.

### Docker 컨테이너 / CI 파이프라인에서 `hsync`를 사용할 수 있나요?

예. GUI 의존성을 피하기 위해 `--headless` 모드를 사용하세요:

```bash
python -m src.main --headless --sync --config-dir /data/config
```

또는 `hsync`를 직접 사용하세요:

```bash
hsync -s --config-dir /data/config -q
```

Qt가 디스플레이 오류를 발생시키면 `QT_QPA_PLATFORM=offscreen`을 설정하세요.

---

## 기여 및 개발

### 버그를 어떻게 보고하나요?

**[GitHub 버그 보고서 템플릿](https://github.com/TheSkyC/HistorySync/issues/new?template=bug_report.yml)**을 사용하세요. OS, HistorySync 버전, 관련 브라우저, 재현 단계를 포함하세요.

### 보안 취약점을 발견했습니다 — 어떻게 해야 하나요?

**공개 이슈를 열지 마세요.** 설명, 재현 단계, 잠재적 영향을 포함하여 **0x4fe6@gmail.com**으로 직접 이메일을 보내주세요. 72시간 이내에 응답을 받으실 수 있습니다.

### 새로운 브라우저 지원을 추가하려면 어떻게 하나요?

[기여 가이드](../dev/contributing.md)를 참조하세요. 브라우저 추출기는 `src/services/extractors/`에 있습니다. 대부분의 새로운 Chromium 포크는 `ChromiumExtractor`를 서브클래싱하여 몇 줄의 코드만으로 추가할 수 있습니다.
