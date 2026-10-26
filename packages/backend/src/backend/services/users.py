from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.password import hash_password
from backend.exceptions.auth import InsufficientPermissionsException
from backend.exceptions.user import DuplicateEmployeeIdException, UserNotFoundException
from backend.models import User, UserRole
from backend.repositories.users import (
  create_general_user,
  get_active_users,
  get_user_by_emp_id,
  get_user_by_id,
  is_employee_id_conflict,
  update_general_user,
)
from backend.schemas.user import UserCreateIn, UserListQuery, UserUpdateIn
from backend.services.auth import require_system_admin
from backend.services.departments import require_active_department


def require_general_user(session: Session, user_id: int) -> User:
  user = get_user_by_id(session, user_id)
  if user is None:
    raise UserNotFoundException()
  if user.role != UserRole.USER:
    raise InsufficientPermissionsException()
  return user


def create_user(session: Session, actor_id: int, body: UserCreateIn) -> User:
  require_system_admin(session, actor_id)
  if get_user_by_emp_id(session, body.emp_id) is not None:
    raise DuplicateEmployeeIdException()
  department = require_active_department(session, body.department_id)
  try:
    return create_general_user(
      session,
      emp_id=body.emp_id,
      name=body.name,
      department=department,
      password_hash=hash_password(body.password.get_secret_value()),
    )
  except IntegrityError as exc:
    if is_employee_id_conflict(exc):
      raise DuplicateEmployeeIdException() from exc
    raise


def update_user(session: Session, actor_id: int, user_id: int, body: UserUpdateIn) -> User:
  require_system_admin(session, actor_id)
  user = require_general_user(session, user_id)
  department = require_active_department(session, body.department_id) if body.department_id is not None else None
  return update_general_user(session, user, name=body.name, department=department)


def get_users(session: Session, user_id: int, query: UserListQuery) -> tuple[list[User], int]:
  require_system_admin(session, user_id)
  return get_active_users(
    session,
    q=query.q,
    department_id=query.department_id,
    is_active=query.is_active,
    page=query.page,
    page_size=query.page_size,
  )
