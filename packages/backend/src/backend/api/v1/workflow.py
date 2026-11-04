from backend.api.dependencies import RequestSession
from backend.api.guard import CurrentUser
from backend.models.workflow import Specification
from backend.repositories import workflow as repository
from backend.schemas.workflow import (
  CompletionIn,
  DocumentIn,
  DraftIn,
  ExtractionIn,
  InspectionIn,
  ItemImportIn,
  JobIn,
  PlanIn,
  RagIn,
  RevisionIn,
  ReworkIn,
  SchedulePlanIn,
  SpecificationIn,
  TargetIn,
)
from backend.services import work_documents, workflow
from fastapi import APIRouter, BackgroundTasks
from sqlalchemy.orm import Session

router = APIRouter(prefix='/workspace', tags=['workspace'])


@router.get('/items')
def item_catalog(session: RequestSession, user: CurrentUser) -> list[dict]:
  return workflow.get_item_catalog(session)


def specification_out(spec: Specification) -> dict:
  return {column.name: getattr(spec, column.name) for column in Specification.__table__.columns}


@router.get('/specifications')
def specifications(session: RequestSession, user: CurrentUser) -> list[dict]:
  return [specification_out(spec) for spec in repository.list_specifications(session)]


@router.post('/specifications', status_code=201)
def create_specification(session: RequestSession, user: CurrentUser, body: SpecificationIn) -> dict:
  return specification_out(workflow.create_specification(session, user, body))


@router.get('/specifications/{specification_id}')
def specification_detail(session: RequestSession, user: CurrentUser, specification_id: str) -> dict:
  return specification_out(repository.get_specification(session, specification_id))


@router.post('/specifications/{specification_id}/items')
def import_item(session: RequestSession, user: CurrentUser, specification_id: str, body: ItemImportIn) -> dict:
  return specification_out(workflow.import_item_definition(session, user, specification_id, body))


@router.put('/specifications/{specification_id}')
def save_specification(session: RequestSession, user: CurrentUser, specification_id: str, body: DraftIn) -> dict:
  return specification_out(workflow.save_draft(session, user, specification_id, body))


@router.post('/specifications/{specification_id}/submit')
def submit_specification(
  session: RequestSession,
  user: CurrentUser,
  specification_id: str,
  body: RevisionIn,
  background: BackgroundTasks,
) -> dict:
  spec = workflow.submit_specification(session, user, specification_id, body.revision)
  from backend.services.rag import index_specification

  background.add_task(index_specification, spec.id)
  return specification_out(spec)


@router.get('/jobs')
def jobs(session: RequestSession, user: CurrentUser) -> list[dict]:
  return [workflow.serialize_job(session, job) for job in repository.list_jobs(session)]


@router.post('/jobs', status_code=201)
def create_job(session: RequestSession, user: CurrentUser, body: JobIn) -> dict:
  return workflow.serialize_job(session, workflow.create_job(session, user, body))


@router.get('/jobs/{job_id}')
def job_detail(session: RequestSession, user: CurrentUser, job_id: str) -> dict:
  return workflow.serialize_job(session, repository.get_job(session, job_id))


@router.post('/jobs/{job_id}/plans', status_code=201)
def confirm_plan(session: RequestSession, user: CurrentUser, job_id: str, body: PlanIn | SchedulePlanIn) -> dict:
  return workflow.serialize_job(session, workflow.confirm_plan(session, user, job_id, body))


@router.get('/jobs/{job_id}/plans')
def plans(session: RequestSession, user: CurrentUser, job_id: str) -> list[dict]:
  repository.get_job(session, job_id)
  return [
    {
      'id': plan.id,
      'version': plan.version,
      'data': plan.data,
      'created_at': plan.created_at,
      'created_by': plan.created_by,
    }
    for plan in repository.list_plans(session, job_id)
  ]


@router.post('/jobs/{job_id}/start')
def start_production(session: RequestSession, user: CurrentUser, job_id: str, body: TargetIn) -> dict:
  return workflow.serialize_job(
    session, workflow.start_production(session, user, job_id, body.target_id, body.revision)
  )


@router.post('/jobs/{job_id}/complete')
def complete_production(session: RequestSession, user: CurrentUser, job_id: str, body: CompletionIn) -> dict:
  return workflow.serialize_job(session, workflow.complete_production(session, user, job_id, body))


@router.post('/jobs/{job_id}/inspect')
def inspect_target(session: RequestSession, user: CurrentUser, job_id: str, body: InspectionIn) -> dict:
  return workflow.serialize_job(session, workflow.inspect_target(session, user, job_id, body))


@router.post('/jobs/{job_id}/rework')
def rework_target(session: RequestSession, user: CurrentUser, job_id: str, body: ReworkIn) -> dict:
  return workflow.serialize_job(session, workflow.rework_target(session, user, job_id, body))


@router.get('/documents')
def documents(
  session: RequestSession,
  user: CurrentUser,
  specification_id: str | None = None,
  job_id: str | None = None,
) -> list[dict]:
  return [
    work_documents.serialize_document(session, doc)
    for doc in repository.list_documents(session, specification_id=specification_id, job_id=job_id)
  ]


@router.post('/documents', status_code=201)
def attach_document(session: RequestSession, user: CurrentUser, body: DocumentIn) -> dict:
  return work_documents.serialize_document(session, work_documents.attach_document(session, user, body))


@router.get('/documents/{document_id}')
def document_detail(session: RequestSession, user: CurrentUser, document_id: str) -> dict:
  return work_documents.serialize_document(session, work_documents.get_document(session, document_id))


@router.post('/documents/{document_id}/extract', status_code=202)
def extract_document(
  session: RequestSession,
  user: CurrentUser,
  document_id: str,
  background: BackgroundTasks,
  body: ExtractionIn | None = None,
) -> dict:
  doc = work_documents.queue_extraction(session, user, document_id)
  background.add_task(
    work_documents.run_extraction,
    user.id,
    document_id,
    graph_candidate=body.graph_candidate if body else False,
  )
  return work_documents.serialize_document(session, doc)


@router.get('/documents/{document_id}/download')
def download_document(session: RequestSession, user: CurrentUser, document_id: str) -> dict:
  from backend.integrations.storage.s3 import get_storage
  from backend.models.file import File

  doc = work_documents.get_document(session, document_id)
  file = session.get(File, doc.file_id)
  return {'url': get_storage(file.bucket).get_download_url(file.key, filename=file.original_filename)}


@router.get('/events')
def events(
  session: RequestSession,
  user: CurrentUser,
  specification_id: str | None = None,
  job_id: str | None = None,
) -> list[dict]:
  return [
    {column.name: getattr(event, column.name) for column in event.__table__.columns}
    for event in repository.list_events(session, specification_id=specification_id, job_id=job_id)
  ]


@router.get('/rag/status')
def rag_status(user: CurrentUser) -> dict:
  from backend.core.config import get_settings

  settings = get_settings()
  return {'enabled': settings.graph_rag_enabled, 'embedding_model': settings.embedding_model, 'graph_database': 'Neo4j'}


@router.post('/specifications/{specification_id}/index', status_code=202)
def reindex_specification(
  session: RequestSession,
  user: CurrentUser,
  specification_id: str,
  background: BackgroundTasks,
) -> dict:
  from backend.services.rag import index_specification

  workflow.require_department(user, workflow.RD)
  spec = repository.get_specification(session, specification_id, lock=True)
  if spec.status != 'submitted':
    from backend.exceptions.workflow import WorkflowError

    raise WorkflowError('R&D 확인·제출 이후 색인할 수 있습니다.')
  spec.index_status = 'pending'
  background.add_task(index_specification, spec.id)
  return {'status': 'pending'}


@router.post('/rag/ask')
async def rag_answer(session: RequestSession, user: CurrentUser, body: RagIn) -> dict:
  from backend.services.rag import answer_question

  return await answer_question(session, body.specification_id, body.question, body.job_id)
