from sqlalchemy.orm import Session

from backend.core.jwt import create_access_token
from backend.core.password import verify_password
from backend.db.session import get_session
from backend.exceptions.auth import InsufficientPermissionsException, InvalidCredentialsException
from backend.models.user import User, UserRole
from backend.repositories.users import get_user_by_emp_id, get_user_by_id


def login(session: Session, emp_id: str, password: str) -> str:
  user = get_user_by_emp_id(session, emp_id)
  if user is None or not user.is_active or not verify_password(password, user.password_hash):
    raise InvalidCredentialsException()
  return create_access_token(user.id)


def require_active_user(session: Session, user_id: int) -> User:
  user = get_user_by_id(session, user_id)
  if user is None or not user.is_active:
    raise InvalidCredentialsException()
  return user


def validate_active_user(user_id: int) -> None:
  with get_session() as session:
    require_active_user(session, user_id)


def require_system_admin(session: Session, user_id: int) -> User:
  user = require_active_user(session, user_id)
  if user.role != UserRole.SYSTEM_ADMIN:
    raise InsufficientPermissionsException()
  return user


def get_current_user(session: Session, user_id: int) -> User:
  return require_active_user(session, user_id)
