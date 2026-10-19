from pydantic import BaseModel


class ErrorOut(BaseModel):
  code: str
  message: str
