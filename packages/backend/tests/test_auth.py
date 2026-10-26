from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from backend.exceptions.auth import InsufficientPermissionsException, InvalidCredentialsException
from backend.models import Department, User, UserRole
from backend.services import auth
from sqlalchemy.orm import Session


@pytest.fixture
def user() -> User:
  return User(id=1, emp_id='EMP001', name='담당자', password_hash='hashed', role=UserRole.USER, is_active=True)


@pytest.fixture(autouse=True)
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
  session = Mock(spec=Session)
  monkeypatch.setattr(auth, 'get_session', lambda: nullcontext(session))
  return session


@pytest.fixture(autouse=True)
def find_by_emp_id(monkeypatch: pytest.MonkeyPatch, user: User) -> Mock:
  find_user = Mock(return_value=user)
  monkeypatch.setattr(auth, 'get_user_by_emp_id', find_user)
  return find_user


@pytest.fixture(autouse=True)
def find_by_id(monkeypatch: pytest.MonkeyPatch, user: User) -> Mock:
  find_user = Mock(return_value=user)
  monkeypatch.setattr(auth, 'get_user_by_id', find_user)
  return find_user


@pytest.fixture(autouse=True)
def check_password(monkeypatch: pytest.MonkeyPatch) -> Mock:
  check = Mock(return_value=True)
  monkeypatch.setattr(auth, 'verify_password', check)
  return check


@pytest.fixture(autouse=True)
def issue_token(monkeypatch: pytest.MonkeyPatch) -> Mock:
  token = Mock(return_value='test-token')
  monkeypatch.setattr(auth, 'create_access_token', token)
  return token


def test_login_returns_access_token(user: User, issue_token: Mock) -> None:
  assert auth.login(user.emp_id, 'password') == 'test-token'
  issue_token.assert_called_once_with(user.id)


def test_missing_user_cannot_login(find_by_emp_id: Mock, issue_token: Mock) -> None:
  find_by_emp_id.return_value = None
  with pytest.raises(InvalidCredentialsException):
    auth.login('UNKNOWN', 'password')
  issue_token.assert_not_called()


def test_inactive_user_cannot_login(user: User, issue_token: Mock) -> None:
  user.is_active = False
  with pytest.raises(InvalidCredentialsException):
    auth.login(user.emp_id, 'password')
  issue_token.assert_not_called()


def test_wrong_password_cannot_login(user: User, check_password: Mock, issue_token: Mock) -> None:
  check_password.return_value = False
  with pytest.raises(InvalidCredentialsException):
    auth.login(user.emp_id, 'wrong-password')
  issue_token.assert_not_called()


@pytest.mark.parametrize(
  ('department', 'expected'),
  [
    pytest.param(Department(id=1, name='연구개발'), {'id': 1, 'name': '연구개발'}, id='with-department'),
    pytest.param(None, None, id='without-department'),
  ],
)
def test_profile_department(user: User, department: Department | None, expected: dict[str, int | str] | None) -> None:
  user.department = department
  profile = auth.get_current_user(user.id).model_dump()

  assert profile == {
    'id': user.id,
    'emp_id': user.emp_id,
    'name': user.name,
    'department': expected,
    'role': user.role,
    'is_active': True,
  }


def test_deactivated_user_is_blocked_on_next_check(user: User) -> None:
  auth.validate_active_user(user.id)

  user.is_active = False
  with pytest.raises(InvalidCredentialsException):
    auth.validate_active_user(user.id)


def test_missing_user_is_blocked(find_by_id: Mock) -> None:
  find_by_id.return_value = None
  with pytest.raises(InvalidCredentialsException):
    auth.validate_active_user(1)


def test_system_admin_is_allowed(user: User, session: Session) -> None:
  user.role = UserRole.SYSTEM_ADMIN
  assert auth.require_system_admin(session, user.id) is user


@pytest.mark.parametrize('role', [UserRole.USER, UserRole.DEPARTMENT_ADMIN])
def test_non_system_admin_is_forbidden(user: User, session: Session, role: UserRole) -> None:
  user.role = role
  with pytest.raises(InsufficientPermissionsException):
    auth.require_system_admin(session, user.id)


def test_inactive_system_admin_is_blocked(user: User, session: Session) -> None:
  user.role = UserRole.SYSTEM_ADMIN
  user.is_active = False
  with pytest.raises(InvalidCredentialsException):
    auth.require_system_admin(session, user.id)
