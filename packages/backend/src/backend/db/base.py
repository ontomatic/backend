import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.core.utils import utc_now


class Base(DeclarativeBase):
  type_annotation_map = {
    enum.Enum: Enum(
      enum.Enum,
      native_enum=False,
      create_constraint=True,
      values_callable=lambda cls: [member.value for member in cls],
    )
  }


class TimestampMixin:
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
