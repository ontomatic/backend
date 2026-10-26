from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, model_validator

from backend.schemas.department import DepartmentOut
from backend.schemas.pagination import PaginatedOut, PaginationQuery

EmployeeId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
UserName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
DepartmentId = Annotated[int, Field(strict=True, gt=0)]


class UserCreateIn(BaseModel):
  model_config = ConfigDict(extra='forbid')

  emp_id: EmployeeId
  name: UserName
  department_id: DepartmentId
  password: SecretStr = Field(min_length=12, max_length=30)


class UserUpdateIn(BaseModel):
  model_config = ConfigDict(extra='forbid')

  name: UserName | None = None
  department_id: DepartmentId | None = None

  @model_validator(mode='before')
  @classmethod
  def require_changes(cls, data: Any) -> Any:
    if isinstance(data, dict) and (not data or None in data.values()):
      raise ValueError('이름 또는 부서를 null이 아닌 값으로 지정해야 합니다.')
    return data


class UserOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  emp_id: str
  name: str
  department: DepartmentOut | None
  role: str
  is_active: bool


class UserListQuery(PaginationQuery):
  model_config = ConfigDict(str_strip_whitespace=True)

  q: str | None = Field(default=None, max_length=100)
  department_id: int | None = Field(default=None, gt=0)
  is_active: bool | None = None


class UserListOut(PaginatedOut[UserOut]):
  pass
