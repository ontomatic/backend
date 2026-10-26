from core.api.client import call


def get_departments() -> list[dict]:
  return call('get', '/api/v1/admin/departments')


def get_users(
  *,
  q: str | None = None,
  department_id: int | None = None,
  is_active: bool | None = None,
  page: int | None = None,
  page_size: int | None = None,
) -> dict:
  params = {
    key: value
    for key, value in {
      'q': q,
      'department_id': department_id,
      'is_active': is_active,
      'page': page,
      'page_size': page_size,
    }.items()
    if value is not None
  }
  return call('get', '/api/v1/admin/users', params=params)


def create_user(emp_id: str, name: str, department_id: int, password: str) -> dict:
  return call(
    'post',
    '/api/v1/admin/users',
    body={
      'emp_id': emp_id,
      'name': name,
      'department_id': department_id,
      'password': password,
    },
  )


def update_user(user_id: int, name: str, department_id: int) -> dict:
  return call(
    'patch',
    f'/api/v1/admin/users/{user_id}',
    body={'name': name, 'department_id': department_id},
  )
