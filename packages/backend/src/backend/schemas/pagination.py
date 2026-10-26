from pydantic import BaseModel, ConfigDict, Field


class PaginationQuery(BaseModel):
  model_config = ConfigDict(extra='forbid')

  page: int = Field(default=1, ge=1)
  page_size: int = Field(default=20, ge=1, le=100)


class PaginatedOut[T](BaseModel):
  items: list[T]
  total: int
  page: int
  page_size: int
