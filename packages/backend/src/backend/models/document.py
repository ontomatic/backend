from sqlalchemy import ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
  __tablename__ = 'documents'

  id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
  uploader_id: Mapped[int] = mapped_column(ForeignKey('users.id'))

  filename: Mapped[str] = mapped_column(String(255), unique=True)
  original_filename: Mapped[str] = mapped_column(String(255))

  file_size: Mapped[int] = mapped_column(Integer)
  page_count: Mapped[int] = mapped_column(Integer)
