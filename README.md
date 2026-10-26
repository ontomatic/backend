# Ontomatic

## 1. Getting Started

### 1.1. Prerequisites

- git
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [docker](https://www.docker.com/)

### 1.2 Clone Repository

```text
git clone https://github.com/ontomatic/Ontomatic.git
cd Ontomatic
uv sync --all-packages --locked
```

### 1.3. Setting Environment Variables

Windows PowerShell:

```powershell
Copy-Item packages/backend/.env.example packages/backend/.env -NoClobber
Copy-Item packages/frontend/.env.example packages/frontend/.env -NoClobber
```

Windows Git Bash 또는 macOS zsh:

```sh
cp -n packages/backend/.env.example packages/backend/.env
cp -n packages/frontend/.env.example packages/frontend/.env
```

backend의 `.env`에는 다음 값을 설정한다.

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`: 로컬 DB 접속 정보. 기본 호스트·포트는 `localhost:5432`이다.
- `JWT_SECRET_KEY`: 로컬 인증에 사용할 충분히 긴 난수 키.
- `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`: RustFS 접속 정보. Compose와 backend가 같은 값을 사용한다.
- `S3_ENDPOINT_URL`, `S3_BUCKET`: 기본값은 `http://localhost:9000`, `ontomatic`이다.
- LLM 기능을 사용할 때는 `LLM_PROVIDER`와 해당 제공자의 연결 정보도 설정한다. Langfuse는 필요할 때 활성화한다.

frontend의 `.env`에는 `API_URL`을 설정한다. 기본값은 `http://localhost:8000`이다.

## 2. Run

### 2.1. Database and RustFS

```text
docker compose up -d
docker compose ps
```

PostgreSQL과 RustFS가 정상 실행되는지 확인한 뒤 현재 마이그레이션을 적용한다.

```text
uv run --package backend alembic -c packages/backend/alembic.ini upgrade head
uv run --package backend alembic -c packages/backend/alembic.ini current
```

파일 업로드를 사용하려면 RustFS 콘솔 `http://localhost:9001`에서 `S3_BUCKET`과 같은 이름의 버킷을 준비한다.
최초 관리자 계정이 필요하면 마이그레이션 적용 후 아래 명령을 실행한다.

```text
uv run --package backend python packages/backend/cli/create_admin.py
```

### 2.2. Run Backend & Frontend

첫 번째 터미널에서 API를 실행한다.

```text
uv run --package backend api
```

두 번째 터미널에서 저장소 루트에서 열고 Streamlit을 실행한다.

```text
uv run streamlit run packages/frontend/app.py
```

## 3. Manage Database Migration

### 3.1. 현재 이력 확인

```text
uv run --package backend alembic -c packages/backend/alembic.ini heads
uv run --package backend alembic -c packages/backend/alembic.ini history
uv run --package backend alembic -c packages/backend/alembic.ini current
```

- `heads`: 코드에 있는 최신 revision
- `history`: 변경 이력
- `current`: 현재 DB 적용 상태

### 3.2. 스키마 변경 추가

1. 기존 migration을 로컬 DB에 적용한 뒤 모델을 수정한다.
2. 새 모델은 `backend.models`에서 import되어 `Base.metadata`에 등록되는지 확인한다.
3. 아래 명령으로 변경 초안을 생성한다. `-m`에는 변경 목적을 나타내는 짧은 설명을 쓴다.

```text
uv run --package backend alembic -c packages/backend/alembic.ini revision --autogenerate -m "add document metadata"
```

### 3.3. 적용과 되돌리기 검증

생성한 migration을 로컬 DB에 적용하고 모델과 DB가 일치하는지 확인한다.

```text
uv run --package backend alembic -c packages/backend/alembic.ini upgrade head
uv run --package backend alembic -c packages/backend/alembic.ini check
```

되돌리기는 폐기 가능한 로컬 검증 DB에서 확인한다. `downgrade`는 테이블·컬럼을 삭제해 데이터를 잃을 수 있다.
공유·운영 DB에는 검증용 되돌리기를 실행하지 않는다.

```text
uv run --package backend alembic -c packages/backend/alembic.ini downgrade -1
uv run --package backend alembic -c packages/backend/alembic.ini upgrade head
```

## 4. Validation

```text
uv run python scripts/check.py
```

Ruff 코드 검사 → 포맷 확인 → backend pytest

## 6. Commit Msg

앞으로 작성하는 커밋은 [Conventional Commits](https://www.conventionalcommits.org/ko/v1.0.0/) 형식을 따른다.
타입과 범위는 영문 소문자, 요약과 본문은 한국어로 작성한다. 범위는 필요한 경우에만 적는다.

```text
<type>(<scope>): <변경 내용을 설명하는 한국어 요약>
```

| 타입 | 용도 |
| --- | --- |
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 동작을 유지하는 구조 개선 |
| `docs` | 문서 변경 |
| `test` | 테스트 추가·보정 |
| `chore` | 개발 도구·설정·의존성 관리 |

범위에는 `backend`, `frontend`, `parser`, `db`, `harness`처럼 변경 대상을 쓴다.
요약은 한 줄로 작성하고 끝에 마침표를 붙이지 않는다. `Feat:`나 `feat;` 대신 소문자 타입과 콜론으로 통일한다.

```text
feat(backend): 파일 업로드 완료 처리 추가
test(parser): CSV 구조화 반환값 검증
docs(harness): 로컬 개발 절차 정리
```
