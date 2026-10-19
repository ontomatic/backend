from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  emp_id: str
  name: str
  department: str | None
  role: str
