from sqlalchemy import Boolean, Identity, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Department(Base):
  __tablename__ = 'departments'

  id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
  code: Mapped[str] = mapped_column(String(50), unique=True)
  name: Mapped[str] = mapped_column(String(100), unique=True)
  is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
