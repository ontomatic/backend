from sqlalchemy.orm import Session

from backend.core.jwt import create_access_token
from backend.core.password import verify_password
from backend.db.session import get_session
from backend.exceptions.auth import InsufficientPermissionsException, InvalidCredentialsException
from backend.models.user import User, UserRole
from backend.repositories.users import get_user_by_emp_id, get_user_by_id
from backend.schemas.user import DepartmentOut, UserOut


def login(emp_id: str, password: str) -> str:
  with get_session() as session:
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


def get_current_user(user_id: int) -> UserOut:
  with get_session() as session:
    user = require_active_user(session, user_id)
    return UserOut(
      id=user.id,
      emp_id=user.emp_id,
      name=user.name,
      department=(
        DepartmentOut(id=user.department.id, name=user.department.name) if user.department is not None else None
      ),
      role=user.role,
      is_active=user.is_active,
    )
