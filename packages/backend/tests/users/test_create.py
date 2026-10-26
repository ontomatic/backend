import pytest
from backend.core.jwt import decode_access_token
from backend.core.password import verify_password
from backend.models import User, UserRole
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..factories import create_department, create_user


def test_create_user_and_login(
  admin_client: TestClient, db_session: Session, user_create_body: dict[str, object]
) -> None:
  # given
  user_create_body.update(emp_id='  New001  ', name='  신규 사용자  ', password='  InitialPass123!  ')
  password = str(user_create_body['password'])

  # when
  response = admin_client.post('/api/v1/admin/users', json=user_create_body)
  login_response = admin_client.post('/api/v1/auth/login', json={'emp_id': 'New001', 'password': password})

  # then
  assert response.status_code == 201
  result = response.json()
  stored_user = db_session.get(User, result['id'])
  assert stored_user is not None
  assert result == {
    'id': stored_user.id,
    'emp_id': 'New001',
    'name': '신규 사용자',
    'department': {'id': user_create_body['department_id'], 'name': '연구개발'},
    'role': 'user',
    'is_active': True,
  }
  assert stored_user.role == UserRole.USER
  assert stored_user.is_active is True
  assert stored_user.password_hash.startswith('$argon2')
  assert verify_password(password, stored_user.password_hash)
  assert not verify_password(password.strip(), stored_user.password_hash)
  assert 'password' not in response.text
  assert password not in response.text
  assert stored_user.password_hash not in response.text
  assert login_response.status_code == 200
  assert decode_access_token(login_response.json()['accessToken']) == stored_user.id


def test_create_user_validation_error_does_not_save_or_expose_password(
  admin_client: TestClient, db_session: Session, user_create_body: dict[str, object]
) -> None:
  # given
  user_create_body['role'] = 'system_admin'
  original_count = db_session.scalars(select(func.count()).select_from(User)).one()

  # when
  response = admin_client.post('/api/v1/admin/users', json=user_create_body)

  # then
  assert response.status_code == 422
  assert response.json()['code'] == 'VALIDATION_ERROR'
  assert db_session.scalars(select(func.count()).select_from(User)).one() == original_count
  assert str(user_create_body['password']) not in response.text


@pytest.mark.parametrize(
  ('role', 'is_active'),
  [
    pytest.param(UserRole.USER, False, id='inactive-user'),
    pytest.param(UserRole.SYSTEM_ADMIN, True, id='system-admin'),
  ],
)
def test_create_user_rejects_duplicate_employee_id(
  admin_client: TestClient,
  db_session: Session,
  user_create_body: dict[str, object],
  role: UserRole,
  is_active: bool,
) -> None:
  # given
  existing = create_user(db_session, emp_id='DUPLICATE001', name='기존 사용자', role=role, is_active=is_active)
  user_create_body['emp_id'] = '  DUPLICATE001  '
  original_count = db_session.scalars(select(func.count()).select_from(User)).one()

  # when
  response = admin_client.post('/api/v1/admin/users', json=user_create_body)

  # then
  assert response.status_code == 409
  assert response.json()['code'] == 'EMP_ID_ALREADY_EXISTS'
  assert db_session.scalars(select(func.count()).select_from(User)).one() == original_count
  db_session.refresh(existing)
  assert (existing.name, existing.role, existing.is_active) == ('기존 사용자', role, is_active)


@pytest.mark.parametrize('state', ['missing', 'inactive'])
def test_create_user_requires_active_department(
  admin_client: TestClient, db_session: Session, user_create_body: dict[str, object], state: str
) -> None:
  # given
  department = create_department(db_session, code='unavailable', name='배정 불가 부서', is_active=False)
  user_create_body['department_id'] = department.id if state == 'inactive' else department.id + 1
  original_count = db_session.scalars(select(func.count()).select_from(User)).one()

  # when
  response = admin_client.post('/api/v1/admin/users', json=user_create_body)

  # then
  assert response.status_code == 422
  assert response.json()['code'] == 'INVALID_DEPARTMENT'
  assert db_session.scalars(select(func.count()).select_from(User)).one() == original_count


def test_commit_conflict_returns_error_before_success_response(
  admin_client: TestClient, db_session: Session, session_factory: sessionmaker[Session]
) -> None:
  # given
  department = create_department(db_session, code='research', name='연구개발')
  body = {'emp_id': 'COMMIT001', 'name': '사용자', 'department_id': department.id, 'password': 'InitialPass123!'}
  conflict_injected = False

  def conflict_on_commit(session: Session) -> None:
    nonlocal conflict_injected
    if conflict_injected:
      return
    conflict_injected = True
    session.add(User(emp_id='COMMIT001', name='동시 생성', password_hash='test-hash'))
    session.flush()

  event.listen(session_factory, 'before_commit', conflict_on_commit)
  try:
    # when
    response = admin_client.post('/api/v1/admin/users', json=body)
    body['emp_id'] = 'NEXT001'
    next_response = admin_client.post('/api/v1/admin/users', json=body)

    # then
    assert response.status_code == 409
    assert response.json()['code'] == 'EMP_ID_ALREADY_EXISTS'
    assert db_session.scalar(select(User).where(User.emp_id == 'COMMIT001')) is None
    assert next_response.status_code == 201
  finally:
    event.remove(session_factory, 'before_commit', conflict_on_commit)
