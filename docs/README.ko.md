<div align="center">

![HistorySync Logo](https://img.shields.io/badge/HistorySync-409EFF?style=for-the-badge&logo=sync)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=flat-square)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
</div>
<p align="center">
  <a href="../README.md">English</a> | 
  <a href="./README.zh-CN.md">简体中文</a> | 
  <a href="./README.zh-TW.md">繁體中文</a> | 
  <a href="./README.ja.md">日本語</a> | 
  한국어 | 
  <a href="./README.ru.md">Русский</a> | 
  <a href="./README.fr.md">Français</a>
<br></p>

# HistorySync
**HistorySync**는 강력한 크로스 플랫폼 데스크톱 애플리케이션입니다. 다중 브라우저 데이터 통합부터 밀리초 단위의 전체 텍스트 검색, WebDAV 자동 백업 및 풍부한 통계에 이르기까지 브라우저 기록을 통합 관리하고 클라우드에 백업하기 위한 완벽하고 효율적인 솔루션을 제공하여 디지털 발자국을 완벽하게 제어할 수 있게 해줍니다.

Chromium 기반, Firefox 기반 및 Safari 브라우저의 기본 데이터베이스를 기본적으로 지원하며, 탁월한 개인정보 보호 및 원활한 로컬 관리 환경을 제공합니다.

---

## 📥 다운로드
Windows, macOS 및 Linux용 최신 버전은 **[GitHub Releases](https://github.com/TheSkyC/HistorySync/releases/latest)** 페이지에서 다운로드할 수 있습니다.

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/TheSkyC/HistorySync?style=for-the-badge)](https://github.com/TheSkyC/HistorySync/releases/latest)

## 🚀 핵심 기능

### 📂 강력한 데이터 통합 (30개 이상의 브라우저 지원)
*   **방대한 브라우저 호환성**: Chrome, Edge, Firefox, Safari, Brave, Vivaldi, Arc 및 수많은 지역/맞춤형 브라우저(QQ, Sogou, CentBrowser 등)를 기본적으로 지원합니다.
*   **스마트 증분 추출**: SQLite WAL 스냅샷을 안전하게 읽어 브라우저가 실행 중일 때도 손실이나 충돌 없이 최신 기록을 추출합니다.
*   **독립형 DB 가져오기**: 독립형 `History` 또는 `places.sqlite` 파일을 수동으로 가져와 이전 컴퓨터의 데이터를 쉽게 병합할 수 있습니다.

### 🔍 Spotlight 스타일의 빠른 검색 및 지식 기반
*   **빠른 액세스 오버레이**: 어디서나 `Ctrl+Shift+H`를 눌러 미니멀한 검색 오버레이를 호출합니다.
*   **새로운 단축키 엔진**: `pynput` 기반의 크로스 플랫폼 핫키 시스템으로 14개의 고도로 사용자 정의 가능한 단축키를 제공합니다.
*   **고급 쿼리 구문**: 토큰(`domain:github.com`, `after:2024-01-01` 등)을 사용하여 전문가처럼 검색하세요.
*   **북마크 및 주석**: 중요한 페이지에 태그와 리치 텍스트 메모를 추가하여 기록을 지식 기반으로 전환하세요.

### ⚡ 극한의 성능 및 모던 UI
*   **수백만 개의 데이터에서도 부드러운 스크롤**: 페이지네이션 로직을 재작성하여 2단계 페이지네이션과 Keyset 인덱스를 도입했습니다. 정규식 검색을 SQL 계층으로 밀어내어 대용량 데이터에서 스크롤 시 끊김 현상을 완전히 제거했습니다.
*   **적응형 인터페이스**: 비례 열 너비 분배 메커니즘을 도입하여 창 크기 조절이 부드럽습니다. 시스템 다크/라이트 테마의 실시간 전환을 완벽하게 지원합니다.
*   **풍부한 데이터 시각화**: GitHub 스타일의 일일 히트맵, 브라우저 점유율 파이 차트, 24시간 활동 막대 그래프를 통해 브라우징 습관을 시각적으로 이해할 수 있습니다.

### ☁️ 클라우드 동기화 및 자동화
*   **WebDAV 백업 및 병합**: **원자적 스트리밍 업로드**를 사용합니다. 클라우드에서 복원할 때 시스템은 여러 장치의 기록을 지능적으로 병합합니다.
*   **헤드리스 CLI (`hsync`)**: 파워 유저를 위한 모든 기능을 갖춘 명령줄 도구입니다. 백그라운드 메모리 사용량이 매우 적습니다.
*   **조용한 백그라운드 모드**: 시스템 트레이에 최소화되어 실행되며 예약된 추출 및 백업을 자동으로 수행합니다.

### 🛡️ 궁극의 개인정보 보호 및 제어
*   **숨김 모드 및 소프트 숨기기**: 전용 "숨겨진 기록" 보기. 특정 도메인의 소프트 숨기기를 지원합니다(기록은 데이터베이스에 남지만 기본 보기에서는 사라짐).
*   **보안 아키텍처 V2**: 독립적인 HKDF 암호화 및 인증 하위 키를 사용하여 WebDAV 자격 증명과 같은 민감한 구성을 보호합니다.
*   **도메인 블랙리스트 및 URL 필터**: 원클릭으로 특정 도메인을 차단합니다. 관련 기록은 즉시 삭제되며 향후 동기화에서도 영구적으로 무시됩니다.

## 📸 스크린샷

*데이터 대시보드 개요*

<img width="1000" alt="Dashboard" src="assets/ui-dashboard.png" />

<details>
<summary><b>► 더 많은 스크린샷 보기 클릭</b></summary>

*통계 및 히트맵*

<img width="1000" alt="Statistics" src="assets/ui-stats.png" />

*기록 검색 및 관리*

<img width="1000" alt="History" src="assets/ui-history.png" />

</details>

## 🛠️ 개발 환경 설정

### 전제 조건
*   Python 3.10 이상
*   Git (선택 사항, 리포지토리 복제용)

### 단계
1.  **리포지토리 복제 (또는 ZIP 다운로드)**
    ```bash
    git clone https://github.com/TheSkyC/HistorySync.git
    cd HistorySync
    ```

2.  **가상 환경 생성 및 활성화 (권장)**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **종속성 설치**
    ```bash
    pip install -r requirements.txt
    ```

4.  **실행**
    ```bash
    python -m src.main
    ```

## 🚀 빠른 시작

HistorySync는 유연한 작업 모드를 제공합니다:

### 1. 🔄 조용한 백그라운드 모드 (권장)
*데이터를 자동으로 백업하고 "한 번 설정하고 잊어버리기"를 원하는 사용자에게 이상적입니다.*
1.  **시작 설정**: `설정 > 시작`으로 이동하여 "시스템 시작 시 실행"을 활성화합니다.
2.  **일정**: `자동 동기화`에서 추출 간격을 설정합니다.
3.  **클라우드**: `WebDAV 클라우드 백업`에 WebDAV 자격 증명을 입력하고 자동 백업을 활성화합니다.
4.  **실행**: 메인 창을 닫습니다. 앱이 트레이로 최소화되어 데이터를 조용히 보호합니다.

### 2. 🔍 적극적인 관리 모드
*기록을 자주 검색하고, 메모를 작성하거나, 개인정보 데이터를 지우는 사용자에게 이상적입니다.*
1.  **빠른 검색**: 어디서나 `Ctrl+Shift+H`를 눌러 오버레이를 호출합니다.
2.  **지식 기반**: 중요한 페이지를 북마크하고 나중에 참조할 수 있도록 메모를 추가합니다.
3.  **개인정보**: 원치 않는 기록을 선택하여 삭제하거나 "도메인 블랙리스트"를 선택하여 특정 사이트의 흔적을 영구적으로 지웁니다.

## 🌐 지원되는 언어
이 도구는 다음 언어의 UI 인터페이스를 지원합니다:
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

## 🤝 기여
어떤 형태의 기여든 환영합니다. 개발 환경, 코드 규칙, DCO 서명 요구 사항은 먼저 [CONTRIBUTING.md](../CONTRIBUTING.md)를 확인해 주세요. 버그 제보, 기능 제안, 사용 관련 질문은 GitHub 이슈 템플릿을 우선 사용해 주세요.

## 📄 라이선스
이 프로젝트는 [Apache 2.0](../LICENSE) 라이선스에 따라 오픈 소스로 제공되며, 저작권 고지를 유지하는 조건으로 자유로운 사용, 수정 및 배포가 허용됩니다.

## 📞 연락처
- 작성자: TheSkyC
- 이메일: 0x4fe6@gmail.com