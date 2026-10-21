from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Identity, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin


class FileStatus(StrEnum):
  PENDING = 'pending'
  UPLOADED = 'uploaded'


class File(Base, TimestampMixin):
  __tablename__ = 'files'
  __table_args__ = (UniqueConstraint('bucket', 'key', name='uq_files_bucket_key'),)

  id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
  uploader_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
  bucket: Mapped[str] = mapped_column(String, nullable=False)
  key: Mapped[str] = mapped_column(String, nullable=False)
  original_filename: Mapped[str] = mapped_column(String, nullable=False)
  content_type: Mapped[str] = mapped_column(String, nullable=False)
  file_size: Mapped[int | None] = mapped_column(BigInteger, default=None)
  status: Mapped[FileStatus] = mapped_column(default=FileStatus.PENDING)
