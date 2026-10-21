from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.models.file import File, FileStatus


@dataclass
class FileCreate:
  key: str
  original_filename: str
  content_type: str


def create_files(session: Session, *, uploader_id: int, bucket: str, items: list[FileCreate]) -> list[File]:
  files = [
    File(
      uploader_id=uploader_id,
      bucket=bucket,
      key=item.key,
      original_filename=item.original_filename,
      content_type=item.content_type,
    )
    for item in items
  ]
  session.add_all(files)
  session.flush()

  return files


def get_file_by_file_id(session: Session, *, file_id: int) -> File | None:
  statement = select(File).where(File.id == file_id)
  return session.scalar(statement)


def make_file_uploaded(session: Session, file: File, *, file_size: int) -> None:
  file.file_size = file_size
  file.status = FileStatus.UPLOADED
  session.flush()
