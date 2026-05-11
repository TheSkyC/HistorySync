---
title: 기여하기
description: HistorySync 기여자를 위한 개발 환경 설정, 코드 스타일, DCO 서명, PR 워크플로우.
---

# HistorySync에 기여하기

관심을 가져주셔서 감사합니다! 버그 수정, 새로운 브라우저 추출기, 문서 개선, 번역, 테스트 커버리지 향상을 특히 환영합니다.

---

## 시작하기

1. 열려 있는 **[이슈](https://github.com/TheSkyC/HistorySync/issues)**를 둘러보세요 — `good first issue`나 `help wanted` 레이블을 찾아보세요.
2. 중요한 작업을 시작하기 전에 **이슈에 댓글**을 달아 중복 작업을 방지하세요.
3. 오타 수정이나 한 줄 버그 수정 같은 소규모 수정은 사전 이슈 없이 바로 PR을 열어도 됩니다.

---

## 개발 환경 설정

### 사전 요구 사항

| 도구 | 필요 버전 |
|---|---|
| Python | **3.12** 권장 (CI 환경과 일치) |
| Git | 최신 버전 |

> HistorySync는 Python 3.10+를 지원하지만, 린팅, 테스트, 잠긴 의존성과 환경을 맞추려면 기여 시 **3.12**를 사용하세요.

### 설치 단계

```bash
# 1. GitHub에서 저장소를 포크한 후 포크를 클론합니다
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. 가상 환경 생성 및 활성화
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. 런타임 의존성 설치
pip install -r requirements.txt

# 4. 개발 및 테스트 의존성 설치
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. (권장) pre-commit 훅 설치
pre-commit install

# 6. 설정 확인
python -m src.main --fresh
```

---

## 코드 스타일

이 프로젝트는 린팅과 포맷팅에 **[Ruff](https://github.com/astral-sh/ruff)**를 사용합니다. 설정은 `ruff.toml`에 있습니다.

```bash
# 문제 확인
ruff check .

# 가능한 경우 자동 수정
ruff check . --fix

# 코드 포맷
ruff format .

# 모든 pre-commit 훅 수동 실행
pre-commit run --all-files
```

**일반적인 스타일 참고사항:**

- 편집 중인 파일의 기존 패턴을 따르세요.
- GUI 코드(PySide6)와 비즈니스 로직을 **엄격하게 분리**하세요 — 서비스는 Qt를 임포트해서는 안 됩니다.
- 영리함보다 명확성을 선호하세요.
- 공개 API를 변경할 때는 독스트링을 추가하거나 업데이트하세요.

---

## 테스트 실행

```bash
# 전체 테스트 스위트 실행
pytest

# 특정 테스트 파일 실행
pytest tests/test_chromium_extractor.py

# 상세 출력
pytest -v

# 커버리지 포함 (requirements-test.txt에 포함된 pytest-cov 필요)
pytest --cov=src --cov-report=term-missing

# CI와 동일한 린트 검사
ruff check src/ tests/
ruff format --check src/ tests/
```

PR이 병합되기 전에 모든 테스트가 통과해야 합니다. 새로운 기능을 추가하는 경우 해당 테스트도 포함해 주세요.

---

## 커밋 가이드라인

명확하고 명령형 커밋 메시지를 사용하세요:

```
<type>(<scope>): <subject>
```

**예시:**
```
fix(extractor): handle missing WAL file during Chromium extraction
feat(browser): add Arc browser support on macOS
docs(webdav): document merge behaviour
test(search): add unit tests for query DSL parser
chore(dev): update Ruff to 0.15
```

**타입:** `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`, `build`

**규칙:**
- 제목 줄은 72자 이하.
- 소문자 명령형 동사 사용 (`add`, `fix`, `remove` — `added`, `fixes` 사용 금지).
- 자명하지 않은 변경에는 본문을 추가하여 *이유*를 설명하세요.

---

## 개발자 원본 인증서 (DCO)

**모든 커밋에 서명이 필요합니다. 서명되지 않은 커밋이 포함된 PR은 병합되지 않습니다.**

```bash
git commit -s -m "fix: handle missing WAL file"
# 다음이 추가됩니다: Signed-off-by: Your Name <your@email.com>
```

Git 신원이 설정되어 있는지 확인하세요:
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### 서명을 잊은 경우?

```bash
# 마지막 커밋만
git commit --amend --no-edit --signoff
git push --force-with-lease

# 여러 커밋 (마지막 N개)
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## PR 워크플로우

1. `main`에서 **브랜치 생성**:
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **변경 사항 적용** — 커밋은 집중적이고 원자적으로 유지하세요.

3. 로컬에서 **테스트 및 린트 실행**.

4. `main`을 대상으로 **푸시 및 PR 열기**:
   ```bash
   git push origin your-branch-name
   ```

5. PR 규칙 준수:
   - PR당 하나의 변경 또는 관련된 변경 사항 집합.
   - *무엇이* 변경되었고 *왜* 변경되었는지 명확한 설명.
   - `Closes #123`으로 관련 이슈를 링크하세요.
   - UI 변경의 경우 스크린샷/녹화 추가.
   - 모든 커밋에 서명 필수.

6. 리뷰 피드백에 **신속하게 응답**하세요.

---

## 환영하는 기여 유형

**특히 환영합니다:**

- **새로운 브라우저 추출기** — 추가적인 Chromium/Firefox 포크 지원.
- **버그 수정** — 특히 플랫폼별 문제 (macOS 경로, Linux 권한, Windows UAC).
- **성능 개선** — 쿼리 최적화, 추출 속도, 메모리 사용량.
- **UI/UX 개선** — 접근성, 키보드 내비게이션, 테마 일관성.
- **테스트 커버리지** — 현재 테스트되지 않은 코드 경로에 대한 새로운 테스트.
- **문서화** — 이 사이트 개선, 인라인 독스트링 추가, 오타 수정.
- **번역** — `src/resources/locales/` 아래의 `.po` 파일 업데이트.

**먼저 논의하세요 (코딩 전에 이슈를 열어주세요):**

- 주요 아키텍처 변경.
- 새로운 서드파티 의존성.
- WebDAV 동기화 프로토콜 또는 데이터베이스 스키마 변경.

---

## 보안 취약점

**보안 취약점에 대해 공개 이슈를 열지 마세요.**

설명, 재현 단계, 잠재적 영향을 포함하여 **0x4fe6@gmail.com**으로 비공개 이메일을 보내주세요. 72시간 이내에 응답을 드릴 것입니다.

---

## 라이선스

풀 리퀘스트를 제출함으로써 귀하의 기여가 **Apache 2.0** 라이선스 하에 제공되는 것에 동의하고 모든 커밋에 대한 DCO를 인증합니다.
