# 공통 개발 지침

Python 3.12와 uv workspace를 사용하는 FastAPI backend·Streamlit frontend 프로젝트이다.
Codex와 Claude Code는 이 문서를 공통 진입점으로 사용하며, 상세 지침은 `.agents`에서 관리한다.
아래 경로와 명령은 저장소 루트를 기준으로 한다.

## 작업 시작 시 읽을 문서

1. 모든 작업을 시작할 때 [.agents/rules.md](.agents/rules.md)를 직접 열어 공통 규칙을 확인한다.
2. 새 변경 작업은 [start-task-workflow](.agents/skills/start-task-workflow/SKILL.md)를 먼저 읽고 main 준비·상세 문답·브랜치 생성·단계별 승인 절차를 따른다. 같은 작업의 후속 요청은 현재 브랜치와 진행 상태에서 이어간다.
3. [.agents/workflows.md](.agents/workflows.md)에서 해당 작업의 구현·리뷰·DB 변경·커밋·검증·인계 절차를 읽는다.
4. 설치·실행·DB 명령과 커밋 메시지 형식이 필요하면 [README.md](README.md)의 해당 절을 확인한다.

## 공통 검증

```text
uv run python scripts/check.py
```

작업 완료 전에 공통 검증과 변경 내용에 필요한 추가 검증을 수행하고 결과를 보고한다.
