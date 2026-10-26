from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .factories import create_department


def test_only_active_departments_are_listed(admin_client: TestClient, db_session: Session) -> None:
  # given
  first = create_department(db_session, code='research', name='연구개발')
  create_department(db_session, code='inactive', name='비활성 부서', is_active=False)
  last = create_department(db_session, code='production', name='생산관리')

  # when
  response = admin_client.get('/api/v1/admin/departments')

  # then
  assert response.status_code == 200
  assert response.json() == [{'id': first.id, 'name': first.name}, {'id': last.id, 'name': last.name}]
