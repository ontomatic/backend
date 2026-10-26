from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.exceptions.user import InvalidDepartmentException
from backend.models.department import Department
from backend.repositories.departments import get_active_department_list, get_department_by_id
from backend.schemas.department import DepartmentOut
from backend.services.auth import require_system_admin


def require_active_department(session: Session, department_id: int) -> Department:
  department = get_department_by_id(session, department_id)
  if department is None or not department.is_active:
    raise InvalidDepartmentException()
  return department


def get_departments(user_id: int) -> list[DepartmentOut]:
  with get_session() as session:
    require_system_admin(session, user_id)
    return [DepartmentOut.model_validate(department) for department in get_active_department_list(session)]
