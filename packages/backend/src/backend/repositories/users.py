from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.user import User


def get_user_by_emp_id(session: Session, emp_id: str) -> User | None:
  statement = select(User).where(User.emp_id == emp_id.strip())
  return session.scalar(statement)


def get_user_by_id(session: Session, user_id: int) -> User | None:
  return session.get(User, user_id)
