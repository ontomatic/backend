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


@pytest.fixture
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


def test_login_returns_access_token(user: User, issue_token: Mock, session: Session) -> None:
  # given
  password = 'password'

  # when
  token = auth.login(session, user.emp_id, password)

  # then
  assert token == 'test-token'
  issue_token.assert_called_once_with(user.id)


def test_missing_user_cannot_login(find_by_emp_id: Mock, issue_token: Mock, session: Session) -> None:
  # given
  find_by_emp_id.return_value = None

  # when
  with pytest.raises(InvalidCredentialsException):
    auth.login(session, 'UNKNOWN', 'password')

  # then
  issue_token.assert_not_called()


def test_inactive_user_cannot_login(user: User, issue_token: Mock, session: Session) -> None:
  # given
  user.is_active = False

  # when
  with pytest.raises(InvalidCredentialsException):
    auth.login(session, user.emp_id, 'password')

  # then
  issue_token.assert_not_called()


def test_wrong_password_cannot_login(user: User, check_password: Mock, issue_token: Mock, session: Session) -> None:
  # given
  check_password.return_value = False

  # when
  with pytest.raises(InvalidCredentialsException):
    auth.login(session, user.emp_id, 'wrong-password')

  # then
  issue_token.assert_not_called()


@pytest.mark.parametrize(
  'department',
  [
    pytest.param(Department(id=1, name='연구개발'), id='with-department'),
    pytest.param(None, id='without-department'),
  ],
)
def test_profile_department(user: User, department: Department | None, session: Session) -> None:
  # given
  user.department = department

  # when
  profile = auth.get_current_user(session, user.id)

  # then
  assert profile is user
  assert profile.department is department


def test_deactivated_user_is_blocked_on_next_check(user: User, session: Session) -> None:
  # given
  auth.validate_active_user(user.id)

  # when
  user.is_active = False

  # then
  with pytest.raises(InvalidCredentialsException):
    auth.validate_active_user(user.id)


def test_missing_user_is_blocked(find_by_id: Mock, session: Session) -> None:
  # given
  find_by_id.return_value = None

  # when
  user_id = 1

  # then
  with pytest.raises(InvalidCredentialsException):
    auth.validate_active_user(user_id)


def test_system_admin_is_allowed(user: User, session: Session) -> None:
  # given
  user.role = UserRole.SYSTEM_ADMIN

  # when
  admin = auth.require_system_admin(session, user.id)

  # then
  assert admin is user


@pytest.mark.parametrize('role', [UserRole.USER, UserRole.DEPARTMENT_ADMIN])
def test_non_system_admin_is_forbidden(user: User, session: Session, role: UserRole) -> None:
  # given
  user.role = role

  # when
  user_id = user.id

  # then
  with pytest.raises(InsufficientPermissionsException):
    auth.require_system_admin(session, user_id)


def test_inactive_system_admin_is_blocked(user: User, session: Session) -> None:
  # given
  user.role = UserRole.SYSTEM_ADMIN
  user.is_active = False

  # when
  user_id = user.id

  # then
  with pytest.raises(InvalidCredentialsException):
    auth.require_system_admin(session, user_id)
