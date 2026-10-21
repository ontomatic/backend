from uuid import uuid4

from backend.integrations.storage.s3 import get_storage
from backend.schemas.upload import UploadFileDetail


def create_upload_key(user_id: int) -> str:
  return f'uploads/{user_id}/{uuid4().hex}'


def get_upload_urls(user_id: int, files: list[UploadFileDetail]) -> list[str]:
  storage = get_storage()

  urls = []
  for file in files:
    key = create_upload_key(user_id)
    url = storage.get_upload_url(key, content_type=file.content_type)
    urls.append(url)

  return urls
