---
title: CLI 참조
description: hsync 명령줄 도구의 전체 참조 — 모든 플래그, 서브 명령어, 고급 쿼리 DSL.
---

# CLI 참조 — `hsync`

`hsync`는 HistorySync의 **헤드리스 CLI**입니다. GUI 없이 애플리케이션의 모든 기능을 제공하므로 예약 작업, 스크립트, CI 환경에 이상적입니다.

---

## 전역 옵션

모든 명령어 및 서브 명령어에서 사용할 수 있는 옵션입니다.

| 플래그 | 단축 | 설명 |
|---|---|---|
| `--version` | | 버전을 출력하고 종료 |
| `--config-dir PATH` | | 사용자 지정 설정/데이터 디렉토리 사용 |
| `--portable` | | `hsync` 바이너리 옆에 모든 데이터 저장 |
| `--verbose` | `-v` | 디버그 수준 로깅 활성화 |
| `--quiet` | `-q` | 진행 상황 출력 억제; 오류만 stderr에 출력 |
| `--no-color` | | ANSI 색상 비활성화 (`NO_COLOR` 환경 변수도 사용 가능) |
| `--dry-run` | | 아무것도 쓰지 않고 탐색/검증만 수행 |

---

## 클래식 액션 플래그

서브 명령어 없이 플래그로 바로 실행하는 단일 동작입니다.

### `-s` / `--sync` — 브라우저 기록 추출

브라우저 기록을 로컬 데이터베이스로 가져옵니다.

```bash
hsync -s
hsync --sync

# 특정 브라우저만 동기화
hsync -s --browsers chrome,firefox

# 30분마다 동기화 (감시 모드)
hsync -s -w 30
```

**동기화 옵션:**

| 플래그 | 설명 |
|---|---|
| `--browsers LIST` | 쉼표로 구분된 브라우저 타입 (기본값: 감지된 모든 브라우저). 예: `chrome,firefox,edge` |
| `-w MINUTES` / `--watch MINUTES` | 매 `MINUTES`분마다 동기화 반복. <kbd>Ctrl</kbd>+<kbd>C</kbd>로 중지. |

### `-b` / `--backup` — WebDAV 백업

로컬 데이터베이스의 압축 스냅샷을 WebDAV에 업로드합니다.

```bash
hsync -b
hsync --backup

# 한 번에 동기화 후 백업
hsync -sb
```

!!! note "WebDAV를 먼저 설정해야 합니다"
    `--backup`을 사용하기 전에 `hsync config set webdav.enabled true`를 실행하고 URL, 사용자명, 비밀번호를 설정하세요.

<a id="export"></a>

### `-e FILE` / `--export FILE` — 기록 내보내기

브라우저 기록을 파일로 내보냅니다. 형식은 파일 확장자에서 자동으로 유추됩니다.

```bash
# CSV로 기본 내보내기
hsync -e history.csv

# 필터를 적용하여 JSON으로 내보내기
hsync -e history.json --keyword python --after 2024-01-01

# 파비콘이 포함된 HTML 보고서
hsync -e report.html --format html --embed-icons

# 도메인 필터링
hsync -e out.csv --domain github.com --domain stackoverflow.com

# 사용자 지정 열
hsync -e out.csv --columns title,url,visit_time,browser_type

# 정규식 키워드 필터
hsync -e out.json --keyword "^https://github" --regex

# 날짜 범위
hsync -e out.csv --after 2024-01-01 --before 2024-12-31
```

**내보내기 옵션:**

| 플래그 | 설명 |
|---|---|
| `--format FMT` | `csv` \| `json` \| `html` (기본값: 확장자에서 유추) |
| `--columns COLS` | 쉼표로 구분된 열 목록. 사용 가능: `id`, `title`, `url`, `visit_time`, `visit_count`, `browser_type`, `profile_name`, `domain`, `metadata`, `typed_count`, `first_visit_time`, `transition_type`, `visit_duration` |
| `--embed-icons` | 파비콘을 Base64 데이터 URI로 삽입 (HTML 내보내기 전용) |
| `--keyword TEXT` | 전체 텍스트 키워드 필터 |
| `--regex` | `--keyword`를 Python 정규식으로 처리 |
| `--browser TYPE` | 브라우저 타입으로 필터링 (예: `chrome`, `firefox`, `edge`) |
| `--after DATE` | `YYYY-MM-DD` 이후 레코드 포함 (해당 날짜 포함) |
| `--before DATE` | `YYYY-MM-DD` 이전 레코드 포함 (해당 날짜 포함) |
| `--domain HOST` | 도메인 필터. 반복 사용 가능: `--domain a.com --domain b.com` |

### `-S` / `--status` — 데이터베이스 통계

데이터베이스 통계를 출력합니다.

```bash
hsync -S
hsync --status

# 기계가 읽을 수 있는 JSON 형식
hsync -S --json

# 스크립트용 간단한 한 줄 출력
hsync -S -q
```

**출력 예시:**
```
데이터베이스 상태
──────────────────────────────────────────────
     경로          :  /home/user/.config/HistorySync/history.db
     크기          :  124.3 MB
     레코드 수     :  1,482,037
     도메인 수     :  8,421
     FTS 인덱스    :  31.2 MB
     브라우저      :  chrome, firefox, edge, brave
     마지막 동기화 :  2026-05-09 14:32:07
     마지막 백업   :  2026-05-09 12:00:00
```

### `-i` / `--interactive` — 대화형 메뉴

대화형 터미널 메뉴를 시작합니다 — 처음 사용하는 분들께 좋습니다.

```bash
hsync -i
hsync --interactive
```

---

## 서브 명령어

### `search` — 기록 검색

구조화된 쿼리 구문으로 기록 레코드를 검색합니다.

```bash
# 최근 20개 레코드 탐색
hsync search

# 최근 100개 탐색
hsync search --limit 100

# 단순 키워드 검색
hsync search python

# 키보드 내비게이션을 포함한 대화형 모드
hsync search -i

# 구조화된 쿼리
hsync search "domain:github.com python"
hsync search "after:2024-01-01 browser:chrome" --limit 50
hsync search "is:bookmarked tag:work" --format json
hsync search "react -tutorial" --open
```

**옵션:**

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `--limit N` | `20` | 최대 결과 수 |
| `--format FMT` | `table` | 출력 형식: `table` \| `json` \| `tsv` \| `csv` |
| `--columns COLS` | `title,url,visit_time,browser_type` | 표시할 열 |
| `--open` | | 첫 번째 결과 URL을 기본 브라우저에서 열기 |
| `-i` / `--interactive` | | 대화형 키보드 내비게이션 모드 |

---

<a id="query-dsl"></a>

### 쿼리 DSL

검색 서브 명령어와 GUI 검색 창 모두 풍부한 쿼리 언어를 지원합니다.

#### 키워드 검색

일반 단어로 제목 및 URL 전체를 검색합니다:
```
python async
"정확한 구문"
react -tutorial         # 특정 단어 제외
```

#### 토큰 필터

| 토큰 | 예시 | 설명 |
|---|---|---|
| `domain:` | `domain:github.com` | 도메인으로 필터링 |
| `title:` | `title:python` | 페이지 제목에서만 검색 |
| `url:` | `url:github` | URL에서만 검색 |
| `after:` | `after:2024-01-01` | 날짜 범위 시작 (해당 날짜 포함) |
| `before:` | `before:2024-12-31` | 날짜 범위 끝 (해당 날짜 포함) |
| `browser:` | `browser:chrome` | 브라우저 타입으로 필터링 |
| `device:` | `device:laptop` | 기기 이름 또는 UUID로 필터링 |
| `is:bookmarked` | `is:bookmarked` | 북마크된 레코드만 |
| `has:note` | `has:note` | 주석이 있는 레코드만 |
| `tag:` | `tag:work` | 태그로 북마크 필터링 |

#### 토큰 조합

토큰과 키워드를 자유롭게 조합할 수 있습니다:
```
domain:arxiv.org after:2024-01-01 deep learning
is:bookmarked tag:work project management
browser:firefox -youtube after:2025-01-01
```

---

### `restore` — WebDAV에서 복원

WebDAV 백업에서 데이터베이스를 복원합니다.

```bash
# 백업 목록을 보고 대화형으로 선택
hsync restore

# 최신 백업을 자동으로 복원 (병합)
hsync restore --latest

# 사용 가능한 백업을 JSON으로 나열
hsync restore --list

# 대체 모드: 로컬 데이터베이스를 완전히 덮어씌우기
hsync restore --replace

# 파비콘 캐시도 복원
hsync restore --latest --restore-favicons
```

**옵션:**

| 플래그 | 설명 |
|---|---|
| `--latest` | 확인 없이 가장 최근 백업을 자동으로 사용 |
| `--list` | 사용 가능한 백업을 JSON 형식으로 나열하고 종료 |
| `--replace` | 대체 모드: 병합 대신 로컬 데이터베이스를 덮어씌우기 |
| `--restore-favicons` | 백업에서 파비콘 캐시도 복원 |

!!! info "병합 vs 대체"
    기본 동작은 백업 레코드를 로컬 데이터베이스와 **병합**합니다 — 양쪽의 레코드가 유지되고 중복이 제거됩니다. 백업으로 로컬 데이터를 완전히 덮어쓰려는 경우에만 `--replace`를 사용하세요.

---

### `db` — 데이터베이스 유지 관리

```bash
# VACUUM + ANALYZE (단편화된 공간 회수)
hsync db vacuum

# 전체 텍스트 검색 인덱스 재구축
hsync db rebuild-fts

# 모든 레코드의 도메인 이름 정규화
hsync db normalize

# 데이터베이스 통계 표시
hsync db stats
hsync db stats --json
```

**서브 명령어:**

| 서브 명령어 | 설명 |
|---|---|
| `vacuum` | `VACUUM` 및 `ANALYZE` 실행 — 단편화된 공간 회수, 쿼리 플래너 통계 업데이트 |
| `rebuild-fts` | FTS5 전체 텍스트 검색 인덱스 재구축 — 검색이 느리거나 결과가 누락된 경우 사용 |
| `normalize` | 모든 레코드의 도메인 이름 재계산 (원시 데이터베이스 가져오기 후 유용) |
| `stats` | `hsync -S`의 별칭 |

---

### `config` — 설정 관리

GUI를 열지 않고 설정 값을 읽고 씁니다.

```bash
# 모든 키와 현재 값 목록
hsync config list

# 단일 값 읽기
hsync config get webdav.url

# 값 쓰기
hsync config set webdav.enabled true
hsync config set webdav.url https://dav.example.com/historysync/
hsync config set scheduler.sync_interval_hours 2
hsync config set theme dark
hsync config set language ko_KR
```

**설정 가능한 키:**

| 키 | 타입 | 설명 |
|---|---|---|
| `webdav.enabled` | bool | WebDAV 백업 활성화 |
| `webdav.url` | string | WebDAV 서버 URL |
| `webdav.username` | string | WebDAV 사용자명 |
| `webdav.remote_path` | string | 백업용 원격 경로 (기본값: `/HistorySync/`) |
| `webdav.max_backups` | int | 유지할 백업 수 (기본값: `10`) |
| `webdav.verify_ssl` | bool | SSL 인증서 검증 (기본값: `true`) |
| `webdav.auto_backup` | bool | 예약 자동 백업 활성화 |
| `webdav.backup_favicons` | bool | 백업에 파비콘 캐시 포함 |
| `scheduler.auto_sync_enabled` | bool | 자동 브라우저 동기화 활성화 |
| `scheduler.sync_interval_hours` | int | 동기화 간격 (시간) |
| `scheduler.auto_backup_enabled` | bool | 예약 WebDAV 백업 활성화 |
| `scheduler.auto_backup_interval_hours` | int | 백업 간격 (시간) |
| `scheduler.launch_on_startup` | bool | 로그인 시 HistorySync 시작 |
| `theme` | string | `dark` \| `light` \| `system` |
| `language` | string | UI 언어 코드 (예: `ko_KR`). 비어 있으면 자동 감지. |

---

<a id="update-check-for-updates"></a>

### `update` — 업데이트 확인

현재 플랫폼과 설치 형태에서 더 새로운 HistorySync 릴리스가 있는지 확인합니다.

```bash
# 사람이 읽기 좋은 출력
hsync update

# 기계가 읽기 좋은 JSON 출력
hsync update --json

# 기본이 아닌 릴리스 채널 확인
hsync update --channel beta
hsync update --channel nightly
```

**옵션:**

| 플래그 | 설명 |
|---|---|
| `--json` | 스크립트와 CI를 위해 업데이트 메타데이터를 JSON으로 출력 |
| `--channel CH` | 이번 확인에 사용할 채널을 덮어쓰기: `stable` \| `beta` \| `nightly` |

**동작 방식:**

- desktop 앱과 동일한 플랫폼 인식 업데이트 메타데이터를 사용합니다.
- 기본 업데이트 API를 사용할 수 없으면 GitHub Releases 메타데이터로 대체합니다.
- 설치 프로그램, 포터블 ZIP, AppImage, `.dmg` 등 현재 설치 형태에 맞는 아티팩트를 선택합니다.

!!! note "CLI는 확인만 수행"
    `hsync update`는 업데이트 가능 여부와 메타데이터만 보고합니다. 실제 안내형 다운로드 및 설치 흐름은 desktop 앱의 **설정 → 업데이트**에 있습니다.

---

## 셸 자동 완성

`hsync`는 `argcomplete`를 통한 셸 자동 완성을 지원합니다.

=== "Bash"
    ```bash
    # 한 번만 전역 설정
    activate-global-python-argcomplete --user

    # 또는 ~/.bashrc에 추가:
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Zsh"
    ```zsh
    # ~/.zshrc에 추가:
    autoload -U bashcompinit && bashcompinit
    eval "$(register-python-argcomplete hsync)"
    ```

=== "Fish"
    ```fish
    register-python-argcomplete --shell fish hsync \
      > ~/.config/fish/completions/hsync.fish
    ```

---

## 스크립팅 및 CI 예시

```bash
# 동기화 후 결과 확인
hsync -s -q && echo "sync ok" || echo "sync failed"

# 상태 JSON을 jq로 파이프
hsync -S --json | jq .record_count

# 로그를 파일로 저장
hsync -s --no-color 2>&1 | tee sync.log

# 동기화 + 백업 (cron 친화적)
hsync -sb -q

# 지난 주의 GitHub 페이지를 JSON으로 내보내기
hsync -e github_week.json \
  --domain github.com \
  --after "$(date -d '7 days ago' +%Y-%m-%d)"

# Python 메인 모듈에서 헤드리스 동기화 (예약 작업용)
python -m src.main --headless --sync
```

---

## 종료 코드

| 코드 | 의미 |
|---|---|
| `0` | 성공 |
| `1` | 오류 (세부 사항은 stderr에 출력) |
