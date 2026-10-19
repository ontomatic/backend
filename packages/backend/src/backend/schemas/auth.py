from pydantic import BaseModel, Field, SecretStr


class LoginIn(BaseModel):
  emp_id: str = Field(min_length=1, max_length=30)
  password: SecretStr = Field(min_length=1, max_length=30)


class TokenOut(BaseModel):
  accessToken: str
