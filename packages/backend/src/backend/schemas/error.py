from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
  loc: list[str | int]
  msg: str


class ErrorOut(BaseModel):
  code: str
  message: str
  errors: list[ErrorDetail] = Field(default_factory=list)
