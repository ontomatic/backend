# 공통 작업 규칙

Codex와 Claude Code는 작업을 시작할 때 이 문서를 읽는다. 작업별 절차는 [workflows.md](workflows.md)를 따른다.

## 프로젝트 구조

- Python 3.12와 uv workspace를 사용한다. Python 버전은 `.python-version`, 의존성 버전은 `uv.lock`을 기준으로 한다.
- `packages/backend`: FastAPI API, 서비스, 저장소, 외부 연동, 문서 파서.
- `packages/frontend`: Streamlit 화면과 HTTP API 클라이언트.
- `packages/backend/tests`: backend 테스트. 현재 CSV 파서 테스트는 외부 서비스 없이 실행할 수 있다.
- `packages/backend/src/backend/db/migrations`: Alembic 마이그레이션과 revision 파일.
- `docker-compose.yaml`: 로컬 PostgreSQL과 RustFS 실행 구성.
- `.agents/scripts/check.py`: 공통 검증기의 실제 구현.
- `scripts/check.py`: 기존 명령을 유지하는 검증 진입점.

## 변경 범위와 코드 규칙

- 작업 전 `git status --short`와 관련 코드·테스트를 확인하고, 기존 사용자 변경을 보존한다.
- 요청 범위에 맞춰 수정하며 API·서비스·저장소·외부 연동 계층의 역할을 유지한다.
- `ruff.toml`의 들여쓰기 2칸, 작은따옴표, 줄 길이 120자 기준을 따른다. 새 함수에는 타입 힌트를 작성한다.
- 문서 파서는 텍스트·표 블록을 담은 `ParsedDocument`를 반환한다. 기존 반환 계약을 유지한다.
- 기존 workspace와 의존성을 사용한다. 의존성 변경이 필요한 작업에서는 해당 `pyproject.toml`과 `uv.lock`을 함께 관리한다.
- 동작을 바꾸면 관련 경계 사례를 포함하는 회귀 테스트를 보완한다.

## 설정과 문서 관리

- 실제 인증 정보는 로컬 `.env`에 둔다. 공유할 설정 항목은 `.env.example`로 관리하고, 비밀값을 코드·로그·보고·커밋에 넣지 않는다.
- 모델·인증·개인 권한은 각 AI 도구의 설정에서 관리한다.
- 설치·실행·DB 명령과 커밋 메시지 형식은 [README.md](../README.md)를 기준으로 한다. 상세 내용을 harness 문서에 중복 작성하지 않는다.
- AI 작업 규칙과 절차는 `.agents`에서 관리하고, 루트 `AGENTS.md`는 문서 안내와 공통 검증 명령을 제공하는 진입점으로 유지한다.
