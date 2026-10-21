from pydantic import BaseModel, Field


class UploadFileDetail(BaseModel):
  filename: str = Field(min_length=1, max_length=255)
  content_type: str = Field(min_length=1)


class UploadFilesIn(BaseModel):
  files: list[UploadFileDetail] = Field(min_length=1, max_length=10)


class UploadFilesOut(BaseModel):
  urls: list[str]
