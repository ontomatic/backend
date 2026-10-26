import pytest
from backend.schemas.user import UserCreateIn, UserUpdateIn
from pydantic import ValidationError


@pytest.fixture
def create_payload() -> dict[str, object]:
  return {'emp_id': 'EMP001', 'name': '사용자', 'department_id': 1, 'password': 'InitialPass123!'}


@pytest.mark.parametrize('length', [12, 30])
def test_create_password_length_boundaries(create_payload: dict[str, object], length: int) -> None:
  # given
  create_payload['password'] = 'p' * length

  # when
  body = UserCreateIn.model_validate(create_payload)

  # then
  assert body.password.get_secret_value() == create_payload['password']


@pytest.mark.parametrize(
  ('field', 'value'),
  [
    ('emp_id', '   '),
    ('name', '   '),
    ('password', 'p' * 11),
    ('password', 'p' * 31),
    ('department_id', None),
    ('department_id', 0),
    ('role', 'system_admin'),
  ],
  ids=['blank-id', 'blank-name', 'short-password', 'long-password', 'null-department', 'zero-department', 'role'],
)
def test_create_schema_rejects_invalid_values(create_payload: dict[str, object], field: str, value: object) -> None:
  # given
  create_payload[field] = value

  # when
  with pytest.raises(ValidationError) as caught:
    UserCreateIn.model_validate(create_payload)

  # then
  assert caught.value.errors()[0]['loc'] == (field,)


@pytest.mark.parametrize('payload', [{}, {'name': None}, {'name': '사용자', 'department_id': None}])
def test_update_requires_non_null_changes(payload: dict[str, object]) -> None:
  # given
  body = payload

  # when
  with pytest.raises(ValidationError) as caught:
    UserUpdateIn.model_validate(body)

  # then
  assert caught.value.errors()[0]['type'] == 'value_error'
