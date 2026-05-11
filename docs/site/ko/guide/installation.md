---
title: 설치
description: Windows, macOS, Linux에서 HistorySync를 설치하는 방법 — 사전 빌드 패키지와 소스 설치 모두 안내합니다.
---

# 설치

HistorySync는 **Windows**, **macOS**, **Linux**에서 실행됩니다. 상황에 맞는 설치 방법을 선택하세요.

---

## 사전 빌드 패키지 (권장)

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 페이지에서 최신 릴리스를 다운로드하세요.

=== "Windows"

    | 패키지 | 설명 |
    |---|---|
    | `HistorySync-vX.Y.Z-windows-x64-setup.exe` | 전체 설치 프로그램, 시작 메뉴 항목 추가 및 선택적 자동 시작 지원 |
    | `HistorySync-vX.Y.Z-windows-x64-portable.zip` | 포터블 — 어디서든 압축 해제 후 바로 실행, 설치 불필요 |

    설치 프로그램을 실행하고 화면의 안내를 따르세요. 별도의 추가 의존성은 필요하지 않습니다.

=== "macOS"

    | 패키지 | 설명 |
    |---|---|
    | `HistorySync-vX.Y.Z-macos-arm64.dmg` | 드래그 앤 드롭 설치 |

    1. `.dmg` 파일을 엽니다.
    2. **HistorySync**를 `응용 프로그램` 폴더로 드래그합니다.
    3. 처음 실행 시 macOS 보안 경고가 표시될 수 있습니다 — **열기**를 클릭하여 계속 진행하세요.

    !!! note "접근성 권한"
        전역 단축키 `Ctrl+Shift+H`를 사용하려면 **접근성** 권한이 필요합니다. 처음 사용 시 macOS가 권한을 요청합니다. **시스템 설정 → 개인 정보 보호 및 보안 → 손쉬운 사용**에서 접근 권한을 허용하세요.

=== "Linux"

    | 패키지 | 설명 |
    |---|---|
    | `HistorySync-vX.Y.Z-linux-x86_64.AppImage` | 모든 최신 Linux 배포판에서 실행 |
    | `HistorySync-vX.Y.Z-linux-x86_64.tar.gz` | 모든 Linux 배포판용 범용 tar 아카이브 |
    | `historysync_X.Y.Z_amd64.deb` | Debian/Ubuntu 기반 배포판용 |

    **AppImage:**
    ```bash
    chmod +x HistorySync-*.AppImage
    ./HistorySync-*.AppImage
    ```

    **Debian/Ubuntu `.deb`:**
    ```bash
    sudo dpkg -i HistorySync-*.deb
    sudo apt-get install -f   # 누락된 의존성 수정
    ```

    !!! warning "Linux/Wayland에서의 전역 단축키"
        `pynput`을 통한 전역 단축키는 **Wayland에서 지원되지 않습니다**. Wayland 세션에서는 `Ctrl+Shift+H` 오버레이 단축키가 작동하지 않습니다. 임시 해결책으로 `--quick` 옵션을 시스템 수준 키 바인딩과 함께 사용하는 것을 고려하세요 ([키보드 단축키](keyboard-shortcuts.md) 참조).

---

## 소스에서 설치

최신 개발 코드를 실행하거나 프로젝트에 기여하려는 경우에 사용하세요.

### 사전 요구 사항

- **Python 3.10+** (Python 3.12 권장 — CI 환경과 일치)
- **Git**

### 설치 단계

```bash
# 1. 저장소 클론
git clone https://github.com/TheSkyC/HistorySync.git
cd HistorySync

# 2. 가상 환경 생성 및 활성화 (강력 권장)
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. 런타임 의존성 설치
pip install -r requirements.txt

# 4. 애플리케이션 실행
python -m src.main
```

### `hsync` CLI 설치 (선택 사항)

**[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 페이지에서 사전 빌드된 `hsync` 바이너리를 다운로드할 수 있습니다:

| 패키지 | 플랫폼 |
|---|---|
| `hsync-vX.Y.Z-windows-x64-setup.exe` | Windows 설치 프로그램 |
| `hsync-vX.Y.Z-windows-x64.zip` | Windows 포터블 |
| `hsync-vX.Y.Z-macos-arm64.tar.gz` | macOS (Apple Silicon) |
| `hsync-vX.Y.Z-linux-x86_64.tar.gz` | Linux x86-64 |

또는 헤드리스 CLI는 Python으로 직접 호출할 수 있습니다:

```bash
python -m src.cli --help
```

`PATH`에 `hsync` 명령으로 설치하려면:

```bash
# 간단한 래퍼 스크립트 생성 (Linux / macOS)
echo '#!/bin/sh\npython -m src.cli "$@"' > /usr/local/bin/hsync
chmod +x /usr/local/bin/hsync
```

---

## 설치 확인

GUI를 실행하고 제목 표시줄에서 버전 번호를 확인하거나 다음을 실행하세요:

```bash
# GUI
python -m src.main --version

# CLI
python -m src.cli --version
# 또는 설치된 경우:
hsync --version
```

---

## 업그레이드

Releases 페이지에서 새 버전의 바이너리로 기존 것을 교체하기만 하면 됩니다. HistorySync는 설정 파일과 데이터베이스를 애플리케이션 바이너리와 별도로 저장하므로, 업그레이드 시 데이터에는 영향을 미치지 않습니다.

기본 데이터 위치:

| 플랫폼 | 디렉토리 |
|---|---|
| Windows | `%APPDATA%\HistorySync\` |
| macOS | `~/Library/Application Support/HistorySync/` |
| Linux | `~/.config/HistorySync/` |

`--config-dir` 옵션으로 경로를 재정의하거나, `--portable` 모드를 사용하여 실행 파일 옆에 모든 데이터를 저장할 수 있습니다.

---

## 제거

1. 애플리케이션 바이너리 / AppImage / 패키지를 제거합니다.
2. 선택적으로 위에 나열된 데이터 디렉토리를 삭제하면 모든 브라우저 데이터와 설정이 제거됩니다.

!!! warning
    데이터 디렉토리 삭제는 되돌릴 수 없습니다. 기록을 보존하려면 데이터베이스를 먼저 백업하세요.
