from pydantic import BaseModel


class DepartmentOut(BaseModel):
  id: int
  name: str


class UserOut(BaseModel):
  id: int
  emp_id: str
  name: str
  department: DepartmentOut | None
  role: str
  is_active: bool
