from collections.abc import Generator
from typing import Annotated

from backend.db.session import get_session
from backend.exceptions.user import DuplicateEmployeeIdException
from backend.repositories.users import is_employee_id_conflict
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def get_request_session() -> Generator[Session, None, None]:
  try:
    with get_session() as session:
      yield session
  except IntegrityError as exc:
    if is_employee_id_conflict(exc):
      raise DuplicateEmployeeIdException() from exc
    raise


RequestSession = Annotated[Session, Depends(get_request_session, scope='function')]
