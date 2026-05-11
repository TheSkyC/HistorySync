---
title: 키보드 단축키
description: HistorySync의 25가지 구성 가능한 키보드 단축키 — 전역 단축키 1개와 앱 내 바인딩 24개.
---

# 키보드 단축키

HistorySync는 **25가지 구성 가능한 단축키**를 제공합니다 — 전역 단축키 1개와 앱 내 단축키 24개. 모두 **설정 → 키보드 단축키**에서 변경할 수 있습니다.

---

## 전역 단축키

이 단축키는 시스템 전역에서 작동합니다 — HistorySync가 백그라운드에 있거나 트레이로 최소화된 경우에도 실행됩니다.

| 동작 | 기본값 | 설명 |
|---|---|---|
| **빠른 접근 오버레이 열기** | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | 스포트라이트 스타일 검색 오버레이 호출/숨기기 |

!!! info "Linux / Wayland"
    `pynput`을 통한 전역 단축키는 **Wayland에서 지원되지 않습니다**. 임시 해결책으로 `--quick` 옵션을 시스템 수준 키 바인딩과 함께 사용하세요:
    ```bash
    # DE 설정에서 이 명령을 시스템 단축키에 바인딩하세요
    python -m src.main --quick
    ```

!!! info "macOS"
    전역 단축키가 처음 실행될 때 macOS가 **접근성** 권한을 요청합니다. **시스템 설정 → 개인 정보 보호 및 보안 → 손쉬운 사용**에서 허용하세요.

---

## 앱 내 단축키

HistorySync 창이 포커스 상태일 때 활성화되는 단축키입니다.

### 현재 기본값

| 분류 | 기본 단축키 |
|---|---|
| **페이지 탐색** | 대시보드 <kbd>Ctrl</kbd>+<kbd>1</kbd>, 기록 <kbd>Ctrl</kbd>+<kbd>2</kbd>, 북마크 <kbd>Ctrl</kbd>+<kbd>3</kbd>, 설정 <kbd>Ctrl</kbd>+<kbd>4</kbd>, 로그 <kbd>Ctrl</kbd>+<kbd>5</kbd>, 통계 <kbd>Ctrl</kbd>+<kbd>6</kbd> |
| **전역 동작** | 지금 동기화 <kbd>Ctrl</kbd>+<kbd>R</kbd>, 검색 포커스 <kbd>Ctrl</kbd>+<kbd>F</kbd> |
| **기록 페이지** | 선택 항목 열기 <kbd>Enter</kbd>, 선택 항목 삭제 <kbd>Delete</kbd>, URL 복사 <kbd>Ctrl</kbd>+<kbd>C</kbd>, 제목 + URL 복사 <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>, 북마크 전환 <kbd>Ctrl</kbd>+<kbd>B</kbd>, 메모 추가 <kbd>Ctrl</kbd>+<kbd>N</kbd>, 내보내기 열기 <kbd>Ctrl</kbd>+<kbd>E</kbd>, 숨기기 전환은 기본 미할당 |
| **북마크 페이지** | 열기 <kbd>Enter</kbd>, URL 복사 <kbd>Ctrl</kbd>+<kbd>C</kbd>, 삭제 <kbd>Delete</kbd>, 메모 추가 <kbd>Ctrl</kbd>+<kbd>N</kbd>, 기록에서 위치 찾기 <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| **통계 페이지** | 이전 기간 <kbd>Alt</kbd>+<kbd>Left</kbd>, 다음 기간 <kbd>Alt</kbd>+<kbd>Right</kbd> |
| **설정 페이지** | 저장 <kbd>Ctrl</kbd>+<kbd>S</kbd> |

설정 대화상자가 최종 기준입니다. 비어 있는 단축키는 기본적으로 바인딩되지 않았으며, 필요하면 직접 지정해야 합니다.

---

## 단축키 커스터마이징

1. **설정 → 키보드 단축키**로 이동합니다.
2. 변경하려는 단축키를 클릭합니다.
3. 새로운 키 조합을 누릅니다.
4. **저장**을 클릭합니다.

단축키를 **비활성화**하려면 해당 단축키를 클릭한 후 <kbd>Backspace</kbd> 또는 <kbd>Delete</kbd>를 눌러 지웁니다.

!!! warning "충돌"
    두 동작이 동일한 키 조합을 공유하면 가장 최근에 설정된 것이 우선합니다. 설정 다이얼로그에서 충돌에 대한 경고 아이콘이 표시됩니다.

---

## 빠른 접근 오버레이 단축키

오버레이 내부(`Ctrl+Shift+H` 패널)에서 작동하는 단축키입니다:

| 동작 | 키 |
|---|---|
| **결과 내비게이션** | <kbd>↑</kbd> / <kbd>↓</kbd> |
| **선택한 URL 열기** | <kbd>Enter</kbd> |
| **새 탭에서 열기** (브라우저가 지원하는 경우) | <kbd>Ctrl</kbd>+<kbd>Enter</kbd> |
| **오버레이 닫기** | <kbd>Esc</kbd> |
| **검색 지우기** | <kbd>Ctrl</kbd>+<kbd>A</kbd> 후 <kbd>Delete</kbd> |
