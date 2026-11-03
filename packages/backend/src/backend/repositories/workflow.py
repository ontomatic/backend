from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.exceptions.workflow import WorkflowNotFound
from backend.models.workflow import ProductionJob, ProductionPlan, Specification, WorkDocument, WorkflowEvent


def get_specification(session: Session, specification_id: str, *, lock: bool = False) -> Specification:
  query = select(Specification).where(Specification.id == specification_id)
  if lock:
    query = query.with_for_update()
  result = session.scalar(query)
  if result is None:
    raise WorkflowNotFound('사양 버전을 찾을 수 없습니다.')
  return result


def get_job(session: Session, job_id: str, *, lock: bool = False) -> ProductionJob:
  query = select(ProductionJob).where(ProductionJob.id == job_id)
  if lock:
    query = query.with_for_update()
  result = session.scalar(query)
  if result is None:
    raise WorkflowNotFound('생산 건을 찾을 수 없습니다.')
  return result


def list_specifications(session: Session) -> list[Specification]:
  return list(session.scalars(select(Specification).order_by(Specification.created_at.desc())))


def list_jobs(session: Session) -> list[ProductionJob]:
  return list(session.scalars(select(ProductionJob).order_by(ProductionJob.created_at.desc())))


def list_documents(
  session: Session, *, specification_id: str | None = None, job_id: str | None = None
) -> list[WorkDocument]:
  query = select(WorkDocument)
  if specification_id:
    query = query.where(WorkDocument.specification_id == specification_id)
  if job_id:
    query = query.where(WorkDocument.job_id == job_id)
  return list(session.scalars(query.order_by(WorkDocument.created_at.desc())))


def list_plans(session: Session, job_id: str) -> list[ProductionPlan]:
  return list(
    session.scalars(select(ProductionPlan).where(ProductionPlan.job_id == job_id).order_by(ProductionPlan.version))
  )


def list_events(
  session: Session, *, specification_id: str | None = None, job_id: str | None = None
) -> list[WorkflowEvent]:
  query = select(WorkflowEvent)
  if specification_id:
    query = query.where(WorkflowEvent.specification_id == specification_id)
  if job_id:
    query = query.where(WorkflowEvent.job_id == job_id)
  return list(session.scalars(query.order_by(WorkflowEvent.created_at.desc(), WorkflowEvent.id)))
