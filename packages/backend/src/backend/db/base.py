from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.utils import utc_now


class Base(DeclarativeBase):
  pass


class TimestampMixin:
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
