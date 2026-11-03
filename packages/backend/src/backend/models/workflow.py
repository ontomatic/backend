from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.utils import utc_now
from backend.db.base import Base


def new_id() -> str:
  return str(uuid4())


class Specification(Base):
  __tablename__ = 'specifications'
  __table_args__ = (UniqueConstraint('code', 'version', name='uq_specification_version'),)

  id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
  code: Mapped[str] = mapped_column(String(80), index=True)
  name: Mapped[str] = mapped_column(String(150))
  product_type: Mapped[str] = mapped_column(String(30))
  version: Mapped[int] = mapped_column(Integer, default=1)
  revision: Mapped[int] = mapped_column(Integer, default=1)
  status: Mapped[str] = mapped_column(String(20), default='draft')
  previous_id: Mapped[str | None] = mapped_column(ForeignKey('specifications.id'))
  graph: Mapped[dict] = mapped_column(JSON)
  reason: Mapped[str] = mapped_column(String(2000), default='')
  created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
  submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  index_status: Mapped[str] = mapped_column(String(20), default='pending')
  index_error: Mapped[str | None] = mapped_column(String(500))


class ProductionJob(Base):
  __tablename__ = 'production_jobs'

  id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
  name: Mapped[str] = mapped_column(String(150))
  specification_id: Mapped[str] = mapped_column(ForeignKey('specifications.id'), index=True)
  quantity: Mapped[float]
  revision: Mapped[int] = mapped_column(Integer, default=1)
  plan_version: Mapped[int] = mapped_column(Integer, default=0)
  status: Mapped[str] = mapped_column(String(32), default='active')
  targets: Mapped[dict] = mapped_column(JSON)
  created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkDocument(Base):
  __tablename__ = 'work_documents'

  id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
  file_id: Mapped[int] = mapped_column(ForeignKey('files.id'), index=True)
  kind: Mapped[str] = mapped_column(String(40))
  department: Mapped[str] = mapped_column(String(50))
  specification_id: Mapped[str | None] = mapped_column(ForeignKey('specifications.id'), index=True)
  job_id: Mapped[str | None] = mapped_column(ForeignKey('production_jobs.id'), index=True)
  scope: Mapped[dict] = mapped_column(JSON)
  blocks: Mapped[list] = mapped_column(JSON, default=list)
  candidates: Mapped[dict] = mapped_column(JSON, default=dict)
  status: Mapped[str] = mapped_column(String(20), default='pending')
  error: Mapped[str | None] = mapped_column(String(500))
  created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductionPlan(Base):
  __tablename__ = 'production_plans'
  __table_args__ = (UniqueConstraint('job_id', 'version', name='uq_job_plan_version'),)

  id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
  job_id: Mapped[str] = mapped_column(ForeignKey('production_jobs.id'), index=True)
  version: Mapped[int]
  data: Mapped[dict] = mapped_column(JSON)
  created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowEvent(Base):
  __tablename__ = 'workflow_events'

  id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
  specification_id: Mapped[str | None] = mapped_column(ForeignKey('specifications.id'), index=True)
  job_id: Mapped[str | None] = mapped_column(ForeignKey('production_jobs.id'), index=True)
  target_id: Mapped[str | None] = mapped_column(String(200))
  action: Mapped[str] = mapped_column(String(50))
  actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
  actor_name: Mapped[str] = mapped_column(String(100))
  department: Mapped[str] = mapped_column(String(50))
  data: Mapped[dict] = mapped_column(JSON)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
