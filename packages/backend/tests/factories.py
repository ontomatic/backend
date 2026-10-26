from backend.models import Department, User, UserRole
from sqlalchemy.orm import Session


def create_department(session: Session, *, code: str, name: str, is_active: bool = True) -> Department:
  department = Department(code=code, name=name, is_active=is_active)
  session.add(department)
  session.commit()
  return department


def create_user(
  session: Session,
  *,
  emp_id: str,
  name: str = '담당자',
  department: Department | None = None,
  role: UserRole = UserRole.USER,
  is_active: bool = True,
) -> User:
  user = User(
    emp_id=emp_id,
    name=name,
    department=department,
    role=role,
    is_active=is_active,
    password_hash='not-a-real-password-hash',
  )
  session.add(user)
  session.commit()
  return user
