from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.department import Department


def get_department_by_id(session: Session, department_id: int) -> Department | None:
  return session.get(Department, department_id)


def get_active_department_list(session: Session) -> list[Department]:
  statement = select(Department).where(Department.is_active.is_(True)).order_by(Department.id)
  return list(session.scalars(statement))
