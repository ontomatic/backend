from backend.core.jwt import create_access_token
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .factories import create_department, create_user


def test_existing_profile_response_is_preserved(client: TestClient, db_session: Session) -> None:
  # given
  research = create_department(db_session, code='research', name='연구개발')
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
    'department': {'id': research.id, 'name': '연구개발'},
    'role': 'user',
    'is_active': True,
  }
