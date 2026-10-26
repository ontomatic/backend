import pytest
from backend.core.jwt import create_access_token
from backend.models import UserRole
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .factories import create_user


@pytest.mark.parametrize('role', [UserRole.USER, UserRole.DEPARTMENT_ADMIN])
@pytest.mark.parametrize(
  ('method', 'path', 'body'),
  [
    ('GET', '/api/v1/admin/users', None),
    ('GET', '/api/v1/admin/departments', None),
    (
      'POST',
      '/api/v1/admin/users',
      {'emp_id': 'NEW001', 'name': '사용자', 'department_id': 1, 'password': 'InitialPass123!'},
    ),
    ('PATCH', '/api/v1/admin/users/999', {'name': '수정 사용자'}),
  ],
  ids=['list-users', 'list-departments', 'create-user', 'update-user'],
)
def test_admin_routes_require_system_admin(
  client: TestClient, db_session: Session, role: UserRole, method: str, path: str, body: dict[str, object] | None
) -> None:
  # given
  requester = create_user(db_session, emp_id='REQUESTER001', role=role)
  headers = {'Authorization': f'Bearer {create_access_token(requester.id)}'}

  # when
  response = client.request(method, path, json=body, headers=headers)

  # then
  assert response.status_code == 403
  assert response.json()['code'] == 'FORBIDDEN'


@pytest.mark.parametrize('authorization', [None, 'Bearer invalid'], ids=['missing-token', 'invalid-token'])
def test_admin_route_requires_authentication(client: TestClient, authorization: str | None) -> None:
  # given
  headers = {} if authorization is None else {'Authorization': authorization}

  # when
  response = client.get('/api/v1/admin/users', headers=headers)

  # then
  assert response.status_code == 401
  assert response.json()['code'] == 'INVALID_CREDENTIALS'


def test_inactive_admin_is_rejected(client: TestClient, db_session: Session) -> None:
  # given
  requester = create_user(db_session, emp_id='INACTIVE001', role=UserRole.SYSTEM_ADMIN, is_active=False)
  headers = {'Authorization': f'Bearer {create_access_token(requester.id)}'}

  # when
  response = client.get('/api/v1/admin/users', headers=headers)

  # then
  assert response.status_code == 401
  assert response.json()['code'] == 'INVALID_CREDENTIALS'
