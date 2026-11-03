import pytest
from backend.core.jwt import create_access_token
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ..factories import create_department, create_user


@pytest.mark.parametrize('code', ['research_and_development', 'quality_assurance', 'production_management'])
def test_profile_response_includes_department_code(client: TestClient, db_session: Session, code: str) -> None:
  # given
  research = create_department(db_session, code=code, name='연구개발')
  requester = create_user(db_session, emp_id='EMP001', name='홍길동', department=research)
  headers = {'Authorization': f'Bearer {create_access_token(requester.id)}'}

  # when
  response = client.get('/api/v1/auth/me', headers=headers)

  # then
  assert response.status_code == 200
  assert response.json() == {
    'id': requester.id,
    'emp_id': 'EMP001',
    'name': '홍길동',
    'department': {'id': research.id, 'code': code, 'name': '연구개발'},
    'role': 'user',
    'is_active': True,
  }
