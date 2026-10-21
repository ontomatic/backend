from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.file import File


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
