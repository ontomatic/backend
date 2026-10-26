from backend.models import UserRole
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .factories import create_department, create_user


def test_list_search_filters_and_pagination(admin_client: TestClient, db_session: Session) -> None:
  # given
  department = create_department(db_session, code='research', name='연구개발')
  matching = create_user(db_session, emp_id='EMP001', name='홍길동', department=department)
  other = create_user(db_session, emp_id='OTHER001', name='김영희', is_active=False)
  create_user(db_session, emp_id='DEPT001', role=UserRole.DEPARTMENT_ADMIN)
  query = {'q': ' emp ', 'department_id': department.id, 'is_active': True, 'page_size': 1}

  # when
  default = admin_client.get('/api/v1/admin/users')
  filtered = admin_client.get('/api/v1/admin/users', params=query)
  past_last_page = admin_client.get('/api/v1/admin/users', params={**query, 'page': 2})

  # then
  assert default.status_code == filtered.status_code == past_last_page.status_code == 200
  assert [item['id'] for item in default.json()['items']] == [other.id, matching.id]
  assert default.json()['total'] == 2
  assert default.json()['page'] == 1
  assert default.json()['page_size'] == 20
  assert all(item['role'] == 'user' for item in default.json()['items'])
  assert filtered.json() == {
    'items': [
      {
        'id': matching.id,
        'emp_id': 'EMP001',
        'name': '홍길동',
        'department': {'id': department.id, 'name': department.name},
        'role': 'user',
        'is_active': True,
      }
    ],
    'total': 1,
    'page': 1,
    'page_size': 1,
  }
  assert past_last_page.json() == {'items': [], 'total': 1, 'page': 2, 'page_size': 1}


def test_invalid_page_size_is_rejected(admin_client: TestClient) -> None:
  # given
  query = {'page_size': 0}

  # when
  response = admin_client.get('/api/v1/admin/users', params=query)

  # then
  assert response.status_code == 422
  assert response.json()['code'] == 'VALIDATION_ERROR'
