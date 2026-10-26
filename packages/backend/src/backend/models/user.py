from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Identity, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.models.department import Department


class UserRole(StrEnum):
  USER = 'user'
  DEPARTMENT_ADMIN = 'department_admin'
  SYSTEM_ADMIN = 'system_admin'


class User(Base, TimestampMixin):
  __tablename__ = 'users'

  id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
  emp_id: Mapped[str] = mapped_column(String(30), unique=True)
  name: Mapped[str] = mapped_column(String(100))
  password_hash: Mapped[str] = mapped_column(String(255))

  department_id: Mapped[int | None] = mapped_column(
    ForeignKey('departments.id', name='fk_users_department_id'), index=True
  )
  department: Mapped[Department | None] = relationship(lazy='joined')
  role: Mapped[str] = mapped_column(String(50), default=UserRole.USER)
  is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
