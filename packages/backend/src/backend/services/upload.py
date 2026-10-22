from uuid import uuid4

from backend.core.config import get_settings
from backend.core.logger import get_logger
from backend.db.session import get_session
from backend.exceptions.file import FileNotFoundException
from backend.integrations.storage.s3 import get_storage
from backend.models.file import FileStatus
from backend.repositories.files import FileCreate, create_files, get_file_by_file_id, make_file_uploaded
from backend.schemas.upload import UploadFileDetail, UploadFileOut
from backend.services.document import parse_document

logger = get_logger(__file__)


def create_upload_key(user_id: int) -> str:
  return f'uploads/{user_id}/{uuid4().hex}'


def get_upload_urls(user_id: int, files: list[UploadFileDetail]) -> list[UploadFileOut]:
  bucket = get_settings().s3_bucket
  storage = get_storage(bucket)

  items = [
    FileCreate(key=create_upload_key(user_id), original_filename=file.filename, content_type=file.content_type)
    for file in files
  ]

  with get_session() as session:
    created_files = create_files(session, uploader_id=user_id, bucket=bucket, items=items)
    return [
      UploadFileOut(file_id=file.id, upload_url=storage.get_upload_url(file.key, content_type=file.content_type))
      for file in created_files
    ]


def complete_file_upload(user_id: int, file_id: int):
  with get_session() as session:
    file = get_file_by_file_id(session, file_id=file_id)
    if file is None or file.uploader_id != user_id:
      raise FileNotFoundException()

    if file.status == FileStatus.UPLOADED:
      return

    storage = get_storage(file.bucket)
    object_info = storage.get_object_info(file.key)
    make_file_uploaded(session, file, file_size=object_info.size)

  doc = parse_document(user_id, file_id)

  logs = []
  logs.append(f'Parsed format: {doc.format}')
  for block in doc.blocks:
    if block.kind == 'text':
      logs.append(f'\t {block.text}')
      continue

    if block.kind == 'table':
      for row in block.rows:
        logs.append(f'\t {"\t".join(cell or "" for cell in row)}')
      continue

  logger.info('\n'.join(logs))
