import sqlite3

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.department import Department
from backend.models.user import User, UserRole


def get_user_by_emp_id(session: Session, emp_id: str) -> User | None:
  statement = select(User).where(User.emp_id == emp_id.strip())
  return session.scalar(statement)


def get_user_by_id(session: Session, user_id: int) -> User | None:
  return session.get(User, user_id)


def create_general_user(
  session: Session, *, emp_id: str, name: str, department: Department, password_hash: str
) -> User:
  user = User(
    emp_id=emp_id,
    name=name,
    department=department,
    password_hash=password_hash,
    role=UserRole.USER,
    is_active=True,
  )
  session.add(user)
  session.flush()
  return user


def update_general_user(session: Session, user: User, *, name: str | None, department: Department | None) -> User:
  if name is not None:
    user.name = name
  if department is not None:
    user.department = department
  session.flush()
  return user


def is_employee_id_conflict(error: IntegrityError) -> bool:
  original = error.orig
  if isinstance(original, sqlite3.IntegrityError):
    return (
      getattr(original, 'sqlite_errorcode', None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
      and str(original) == 'UNIQUE constraint failed: users.emp_id'
    )
  return (
    getattr(original, 'sqlstate', None) == '23505'
    and getattr(getattr(original, 'diag', None), 'constraint_name', None) == 'users_emp_id_key'
  )


def get_active_users(
  session: Session,
  *,
  q: str | None,
  department_id: int | None,
  is_active: bool | None,
  page: int,
  page_size: int,
) -> tuple[list[User], int]:
  conditions = [User.role == UserRole.USER]
  if q:
    conditions.append(or_(User.emp_id.icontains(q, autoescape=True), User.name.icontains(q, autoescape=True)))
  if department_id is not None:
    conditions.append(User.department_id == department_id)
  if is_active is not None:
    conditions.append(User.is_active == is_active)

  total = session.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
  offset = (page - 1) * page_size
  if offset >= total:
    return [], total
  statement = select(User).where(*conditions).order_by(User.id.desc()).offset(offset).limit(page_size)
  return list(session.scalars(statement)), total
