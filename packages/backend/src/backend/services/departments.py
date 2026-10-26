from sqlalchemy.orm import Session

from backend.exceptions.user import InvalidDepartmentException
from backend.models.department import Department
from backend.repositories.departments import get_active_department_list, get_department_by_id


def require_active_department(session: Session, department_id: int) -> Department:
  department = get_department_by_id(session, department_id)
  if department is None or not department.is_active:
    raise InvalidDepartmentException()
  return department


def get_departments(session: Session) -> list[Department]:
  return get_active_department_list(session)
