from pydantic import BaseModel, Field


class ChatIn(BaseModel):
  prompt: str = Field(min_length=1)


class ChatOut(BaseModel):
  text: str
