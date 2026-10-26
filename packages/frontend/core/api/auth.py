from core.api.client import call


def login(emp_id: str, password: str) -> str:
  response = call('post', '/api/v1/auth/login', body={'emp_id': emp_id, 'password': password})
  return response['accessToken']


def get_current_user() -> dict:
  return call('get', '/api/v1/auth/me')
