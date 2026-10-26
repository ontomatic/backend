import pytest
from backend.models import Department
from sqlalchemy.orm import Session

from ..factories import create_department


@pytest.fixture
def active_department(db_session: Session) -> Department:
  return create_department(db_session, code='research', name='연구개발')


@pytest.fixture
def user_create_body(active_department: Department) -> dict[str, object]:
  return {
    'emp_id': 'NEW001',
    'name': '신규 사용자',
    'department_id': active_department.id,
    'password': 'InitialPass123!',
  }
