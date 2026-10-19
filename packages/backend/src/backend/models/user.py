from sqlalchemy import Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
  __tablename__ = 'users'

  id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
  emp_id: Mapped[str] = mapped_column(String(30), unique=True)
  name: Mapped[str] = mapped_column(String(100))
  password_hash: Mapped[str] = mapped_column(String(255))

  department: Mapped[str | None] = mapped_column(String(100))
  role: Mapped[str] = mapped_column(String(50))
