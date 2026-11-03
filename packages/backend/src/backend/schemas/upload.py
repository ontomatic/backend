from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.workflow import DocumentKind


class UploadFileDetail(BaseModel):
  filename: str = Field(min_length=1, max_length=255)
  content_type: str = Field(min_length=1)


class UploadFilesIn(BaseModel):
  kind: DocumentKind | Literal['auto']
  files: list[UploadFileDetail] = Field(min_length=1, max_length=10)


class UploadFileOut(BaseModel):
  file_id: int
  upload_url: str
