from pathlib import Path
from typing import Literal
from uuid import uuid4

from backend.core.config import get_settings
from backend.core.logger import get_logger
from backend.db.session import get_session
from backend.exceptions.file import FileNotFoundException
from backend.exceptions.workflow import WorkflowError
from backend.integrations.storage.s3 import get_storage
from backend.models.file import FileStatus
from backend.repositories.files import FileCreate, create_files, get_file_by_file_id, make_file_uploaded
from backend.schemas.upload import UploadFileDetail, UploadFileOut
from backend.schemas.workflow import DocumentKind
from backend.services.auth import require_active_user
from backend.services.workflow import DOCUMENT_DEPARTMENTS, QA, require_department

logger = get_logger(__file__)


def create_upload_key(user_id: int) -> str:
  return f'uploads/{user_id}/{uuid4().hex}'


def get_upload_urls(
  user_id: int, files: list[UploadFileDetail], kind: DocumentKind | Literal['auto']
) -> list[UploadFileOut]:
  items = [
    FileCreate(key=create_upload_key(user_id), original_filename=file.filename, content_type=file.content_type)
    for file in files
  ]

  with get_session() as session:
    user = require_active_user(session, user_id)
    require_department(user, QA if kind == 'auto' else DOCUMENT_DEPARTMENTS[kind])
    if any(Path(file.filename).suffix.lower() not in ('.pdf', '.docx', '.xlsx', '.csv') for file in files):
      raise WorkflowError('문서 형식은 PDF·DOCX·XLSX·CSV만 지원합니다.')
    bucket = get_settings().s3_bucket
    storage = get_storage(bucket)
    created_files = create_files(session, uploader_id=user_id, bucket=bucket, items=items)
    return [
      UploadFileOut(file_id=file.id, upload_url=storage.get_upload_url(file.key, content_type=file.content_type))
      for file in created_files
    ]


def complete_file_upload(user_id: int, file_id: int):
  with get_session() as session:
    require_active_user(session, user_id)
    file = get_file_by_file_id(session, file_id=file_id, lock=True)
    if file is None or file.uploader_id != user_id:
      raise FileNotFoundException()

    if file.status == FileStatus.UPLOADED:
      return

    storage = get_storage(file.bucket)
    object_info = storage.get_object_info(file.key)
    staging_key = file.key
    original_key = f'originals/{user_id}/{file.key.rsplit("/", 1)[-1]}'
    storage.copy(file.key, original_key, source_etag=object_info.etag)
    file.key = original_key
    make_file_uploaded(session, file, file_size=object_info.size)

  try:
    storage.delete(staging_key)
  except Exception:
    logger.warning('Failed to clean staging upload for file %s', file_id)
  # Parse after binding the document so failures can be retried without losing the uploaded original.
  logger.info('File upload completed: %s', file_id)
