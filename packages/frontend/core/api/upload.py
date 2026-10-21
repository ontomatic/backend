from typing import TypedDict

import httpx2
from core.api.client import call
from streamlit.typing import UploadedFile


class UploadTicket(TypedDict):
  file_id: int
  upload_url: str


def get_presigned_urls(files: list[UploadedFile]) -> list[UploadTicket]:
  body = {'files': [{'filename': file.name, 'content_type': file.type} for file in files]}
  response = call('post', '/api/v1/uploads', body=body)
  return response


def upload_file(url: str, file: UploadedFile):
  response = httpx2.put(url, content=file.getvalue(), headers={'Content-Type': file.type})
  response.raise_for_status()


def complete_upload(file_id: int) -> None:
  call('post', f'/api/v1/uploads/{file_id}/complete')
