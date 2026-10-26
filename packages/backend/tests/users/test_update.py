import pytest
from backend.models import Department, User, UserRole
from backend.schemas.user import UserOut
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ..factories import create_department, create_user


@pytest.fixture
def target_user(db_session: Session, active_department: Department) -> User:
  return create_user(db_session, emp_id='TARGET001', name='기존 사용자', department=active_department)


@pytest.mark.parametrize('fields', ['name', 'department', 'both'])
def test_update_user_fields(admin_client: TestClient, db_session: Session, target_user: User, fields: str) -> None:
  # given
  assert target_user.department is not None
  body: dict[str, object] = {}
  expected_name = target_user.name
  expected_department_id = target_user.department_id
  expected_department_name = target_user.department.name
  original_hash = target_user.password_hash
  if fields in ('name', 'both'):
    body['name'] = '  수정 사용자  '
    expected_name = '수정 사용자'
  if fields in ('department', 'both'):
    production = create_department(db_session, code='production', name='생산관리')
    body['department_id'] = production.id
    expected_department_id = production.id
    expected_department_name = production.name

  # when
  response = admin_client.patch(f'/api/v1/admin/users/{target_user.id}', json=body)

  # then
  assert response.status_code == 200
  assert response.json() == {
    'id': target_user.id,
    'emp_id': 'TARGET001',
    'name': expected_name,
    'department': {'id': expected_department_id, 'name': expected_department_name},
    'role': 'user',
    'is_active': True,
  }
  db_session.refresh(target_user)
  assert target_user.name == expected_name
  assert target_user.department_id == expected_department_id
  assert target_user.password_hash == original_hash


def test_employee_id_change_rejects_entire_update(
  admin_client: TestClient, db_session: Session, target_user: User
) -> None:
  # given
  body = {'name': '수정 사용자', 'emp_id': 'CHANGED001'}
  original = UserOut.model_validate(target_user).model_dump()
  original_hash = target_user.password_hash

  # when
  response = admin_client.patch(f'/api/v1/admin/users/{target_user.id}', json=body)

  # then
  assert response.status_code == 422
  assert response.json()['code'] == 'VALIDATION_ERROR'
  db_session.refresh(target_user)
  assert UserOut.model_validate(target_user).model_dump() == original
  assert target_user.password_hash == original_hash


@pytest.mark.parametrize('state', ['missing', 'inactive'])
def test_invalid_department_does_not_partially_update_name(
  admin_client: TestClient, db_session: Session, target_user: User, state: str
) -> None:
  # given
  inactive = create_department(db_session, code='inactive', name='비활성 부서', is_active=False)
  body = {'name': '저장되면 안 되는 이름', 'department_id': inactive.id if state == 'inactive' else inactive.id + 1}
  original = UserOut.model_validate(target_user).model_dump()

  # when
  response = admin_client.patch(f'/api/v1/admin/users/{target_user.id}', json=body)

  # then
  assert response.status_code == 422
  assert response.json()['code'] == 'INVALID_DEPARTMENT'
  db_session.refresh(target_user)
  assert UserOut.model_validate(target_user).model_dump() == original


@pytest.mark.parametrize('target_role', ['self', 'system_admin', 'department_admin'])
def test_admin_accounts_cannot_be_updated(
  admin_client: TestClient, admin_user: User, db_session: Session, target_role: str
) -> None:
  # given
  target = (
    admin_user
    if target_role == 'self'
    else create_user(db_session, emp_id='ADMIN002', role=UserRole(target_role), is_active=False)
  )
  original = UserOut.model_validate(target).model_dump()
  original_hash = target.password_hash

  # when
  response = admin_client.patch(f'/api/v1/admin/users/{target.id}', json={'name': '수정 시도'})

  # then
  assert response.status_code == 403
  assert response.json()['code'] == 'FORBIDDEN'
  db_session.refresh(target)
  assert UserOut.model_validate(target).model_dump() == original
  assert target.password_hash == original_hash


def test_update_missing_user(admin_client: TestClient, target_user: User) -> None:
  # given
  missing_user_id = target_user.id + 1

  # when
  response = admin_client.patch(f'/api/v1/admin/users/{missing_user_id}', json={'name': '수정 사용자'})

  # then
  assert response.status_code == 404
  assert response.json()['code'] == 'USER_NOT_FOUND'
