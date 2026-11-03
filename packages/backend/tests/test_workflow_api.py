from copy import deepcopy

import pytest
from backend.core.jwt import create_access_token
from backend.db.base import Base
from backend.models import File, User
from backend.models.file import FileStatus
from backend.models.workflow import ProductionJob, Specification, WorkflowEvent
from backend.services.workflow import finish_job_change
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .factories import create_department, create_user
from .test_workflow import graph


def request(workspace: dict, role: str, path: str, body: dict, status: int = 200, method: str = 'post') -> dict:
  client = workspace['client']
  response = getattr(client, method)(
    '/api/v1/workspace' + path,
    json=body,
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"][role].id)}'},
  )
  assert response.status_code == status, response.text
  return response.json()


def document(workspace: dict, role: str, kind: str, **scope: object) -> str:
  with workspace['factory']() as session:
    file = File(
      uploader_id=workspace['users'][role].id,
      bucket='test',
      key=f'{kind}-{scope}-{len(session.new)}',
      original_filename=f'{kind}.csv',
      content_type='text/csv',
      status=FileStatus.UPLOADED,
    )
    # The key only identifies a test original; every attachment remains a separate immutable record.
    file.key = f'{file.key}-{__import__("uuid").uuid4()}'
    session.add(file)
    session.commit()
    file_id = file.id
  return request(workspace, role, '/documents', {'file_id': file_id, 'kind': kind, **scope}, 201)['id']


def extract(workspace: dict, role: str, document_id: str, body: dict) -> dict:
  request(workspace, role, f'/documents/{document_id}/extract', body, 202)
  response = workspace['client'].get(
    f'/api/v1/workspace/documents/{document_id}',
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"][role].id)}'},
  )
  assert response.status_code == 200, response.text
  return response.json()


def source(document_id: str) -> dict:
  return {'document_id': document_id, 'page': 1, 'row': '2', 'original_field': 'length', 'original_value': '8 mm'}


def submitted_specification(workspace: dict, product_type: str = 'digital', code: str = 'CAM') -> dict:
  data = graph()
  for item in data['items']:
    item.update(confirmed=True, attributes=[{'field': 'length', 'value': 8, 'unit': 'mm', 'confirmed': True}])
  for edge in data['relations']:
    edge['confirmed'] = True
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {
      'code': code,
      'name': '시연용 카메라',
      'product_type': product_type,
      'graph': data,
    },
    201,
  )
  doc = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  document(workspace, 'rd', 'bom_transfer', specification_id=spec['id'])
  for item in data['items']:
    item['attributes'][0]['source'] = source(doc)
  for edge in data['relations']:
    edge['source'] = source(doc)
  spec = request(workspace, 'rd', f'/specifications/{spec["id"]}', {'revision': 1, 'graph': data}, method='put')
  return request(workspace, 'rd', f'/specifications/{spec["id"]}/submit', {'revision': spec['revision']})


def new_job(workspace: dict, spec: dict, quantity: int = 10) -> dict:
  return request(
    workspace,
    'pm',
    '/jobs',
    {
      'name': '카메라 생산 건',
      'specification_id': spec['id'],
      'quantity': quantity,
    },
    201,
  )


def plan(workspace: dict, job: dict, quantity: int = 10) -> dict:
  target_ids = [key for key, target in job['targets'].items() if target['kind'] != 'material']
  sources = [
    source(
      document(workspace, 'pm', kind, job_id=job['id'], target_ids=target_ids, plan_version=job['plan_version'] + 1)
    )
    for kind in ('production_plan',)
  ]
  return {
    'revision': job['revision'],
    'quantity': quantity,
    'reason': '계획 확인 또는 목표 변경',
    'confirmed': True,
    'lines': [
      {
        'target_id': key,
        'process': '조립',
        'track': f'T-{index}',
        'quantity': quantity,
        'unit': '개',
        'duration': 1,
        'duration_unit': 'hour',
        'time_basis': 'batch',
        'resource': f'담당자-{index}',
        'start': '2026-11-02T09:00:00+09:00',
        'end': '2026-11-02T10:00:00+09:00',
        'sources': sources,
      }
      for index, key in enumerate(target_ids)
    ],
  }


def target_key(job: dict, prefix: str) -> str:
  return next(key for key in job['targets'] if key == prefix or key.startswith(prefix + '|'))


def inspection(workspace: dict, job: dict, key: str, *, result: str = 'pass', **extra: object) -> dict:
  matching = [target_id for target_id in job['targets'] if target_id == key or target_id.startswith(key + '|')]
  if len(matching) > 1:
    for target_id in matching:
      job = inspection(workspace, job, target_id, result=result, **extra)
    return job
  key = matching[0]
  target = job['targets'][key]
  kinds = (
    {
      'material': 'incoming_inspection',
      'component': 'inspection_module1',
      'assembly': 'inspection_module2',
      'product': 'inspection_final',
    }[target['kind']],
  )
  sources = [
    source(
      document(
        workspace,
        'qa',
        kind,
        job_id=job['id'],
        target_ids=[key],
        round=target['round'],
        plan_version=target['plan_version'],
      )
    )
    for kind in kinds
  ]
  return request(
    workspace,
    'qa',
    f'/jobs/{job["id"]}/inspect',
    {
      'revision': job['revision'],
      'target_id': key,
      'result': result,
      'criterion': '시연용 가상 기준 8 mm',
      'standard': 'DEMO-8',
      'measured_value': '8',
      'unit': 'mm',
      'grade': 'A',
      'sources': sources,
      'confirmed': True,
      **extra,
    },
  )


def produce(workspace: dict, job: dict, key: str) -> dict:
  key = target_key(job, key)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': job['revision'], 'target_id': key})
  return request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/complete',
    {
      'revision': job['revision'],
      'target_id': key,
      'quantity': job['targets'][key]['quantity'],
      'unit': '개',
      'confirmed': True,
    },
  )


@pytest.mark.parametrize(
  'target_status,defect_quantity,expected',
  [('waiting', 0, 'active'), ('passed', 0, 'completed'), ('partial', 1, 'completed_with_defects')],
)
def test_job_completion_status_fits_persisted_column(
  workspace: dict, target_status: str, defect_quantity: int, expected: str
) -> None:
  # Given a final process, when its outcome changes, then the job status fits the database column.
  job = new_job(workspace, submitted_specification(workspace))
  with workspace['factory']() as session:
    persisted = session.get(ProductionJob, job['id'])
    targets = deepcopy(persisted.targets)
    for target in targets.values():
      target['status'] = target_status
    targets[target_key(job, 'CAM@1')].update(process_code='P-FINAL', defect_quantity=defect_quantity)
    finish_job_change(session, persisted, targets)
    session.commit()
    assert persisted.status == expected
    assert len(persisted.status) <= ProductionJob.__table__.c.status.type.length


@pytest.mark.parametrize('product_type', ['digital', 'telephoto', 'film', 'polaroid'])
def test_four_product_types_complete_only_after_manual_production_and_quality(
  workspace: dict, product_type: str
) -> None:
  # Given an independently confirmed product, when all stages are manually completed, then only this job completes.
  spec = submitted_specification(workspace, product_type)
  job = new_job(workspace, spec)
  another = new_job(workspace, spec, 2)
  body = plan(workspace, job)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/start',
    {
      'revision': job['revision'],
      'target_id': 'CAM@1|root',
    },
    409,
  )
  job = inspection(workspace, job, 'SCREW@1|J8')
  for key in ('LENS@1|common', 'BODY@1|common', 'CAM@1|root'):
    job = produce(workspace, job, key)
    assert job['status'] == 'active'
    job = inspection(workspace, job, key)
  assert job['status'] == 'completed'
  with workspace['factory']() as session:
    independent = session.get(ProductionJob, another['id'])
    assert independent.status == 'active'
    assert all(target['status'] == 'waiting' for target in independent.targets.values())
    assert len(list(session.scalars(select(WorkflowEvent).where(WorkflowEvent.action == 'production_completed')))) == 3


def test_quantity_shortage_excess_stale_update_and_department_permissions(workspace: dict) -> None:
  spec = submitted_specification(workspace)
  job = new_job(workspace, spec)
  body = plan(workspace, job)
  request(workspace, 'qa', f'/jobs/{job["id"]}/plans', body, 403)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  job = inspection(workspace, job, 'SCREW@1|J8')
  job = request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/start',
    {
      'revision': job['revision'],
      'target_id': target_key(job, 'LENS@1|common'),
    },
  )
  for amount in (8, 12):
    request(
      workspace,
      'pm',
      f'/jobs/{job["id"]}/complete',
      {
        'revision': job['revision'],
        'target_id': target_key(job, 'LENS@1|common'),
        'quantity': amount,
        'unit': '개',
        'confirmed': True,
      },
      422,
    )
  request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/complete',
    {
      'revision': 1,
      'target_id': target_key(job, 'LENS@1|common'),
      'quantity': 10,
      'unit': '개',
      'confirmed': True,
    },
    409,
  )
  changed = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', plan(workspace, job, 12), 201)
  assert changed['quantity'] == 12
  assert changed['targets'][target_key(changed, 'SCREW@1|J8')]['status'] == 'waiting'
  assert changed['targets'][target_key(changed, 'LENS@1|common')]['round'] == 2


def test_failure_rework_preserves_unaffected_passes_and_previous_rounds(workspace: dict) -> None:
  spec = submitted_specification(workspace)
  job = new_job(workspace, spec)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', plan(workspace, job), 201)
  job = inspection(workspace, job, 'SCREW@1|J8')
  job = inspection(workspace, produce(workspace, job, 'BODY@1|common'), 'BODY@1|common')
  original_pass = job['targets'][target_key(job, 'BODY@1|common')]['inspection_id']
  job = inspection(
    workspace,
    produce(workspace, job, 'LENS@1|common'),
    'LENS@1|common',
    result='fail',
    cause='physical',
    reason='가상 검사에서 일부 불량',
  )
  assert job['targets'][target_key(job, 'LENS@1|common')]['status'] == 'held'
  failure = job['targets'][target_key(job, 'LENS@1|common')]['inspection_id']
  job = request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/rework',
    {
      'revision': job['revision'],
      'target_id': target_key(job, 'LENS@1|common'),
      'cause': 'physical',
      'reason': '렌즈 모듈 재작업',
    },
  )
  assert job['targets'][target_key(job, 'LENS@1|common')]['round'] == 2
  assert job['targets'][target_key(job, 'BODY@1|common')]['inspection_id'] == original_pass
  assert job['targets'][target_key(job, 'BODY@1|common')]['status'] == 'passed'
  job = inspection(workspace, produce(workspace, job, 'LENS@1|common'), 'LENS@1|common')
  with workspace['factory']() as session:
    assert session.get(WorkflowEvent, failure).data['result'] == 'fail'
  assert job['targets'][target_key(job, 'LENS@1|common')]['status'] == 'passed'


def test_submission_and_evidence_scope_cannot_be_bypassed(workspace: dict) -> None:
  spec = submitted_specification(workspace)
  request(workspace, 'pm', '/jobs', {'name': '잘못된 수량', 'specification_id': spec['id'], 'quantity': 0.5}, 422)
  request(
    workspace,
    'rd',
    f'/specifications/{spec["id"]}',
    {
      'revision': spec['revision'],
      'graph': spec['graph'],
    },
    409,
    'put',
  )
  job = new_job(workspace, spec)
  other = new_job(workspace, spec)
  bad_doc = document(
    workspace, 'qa', 'incoming_inspection', job_id=other['id'], target_ids=[target_key(other, 'SCREW@1|J8')]
  )
  request(
    workspace,
    'qa',
    f'/jobs/{job["id"]}/inspect',
    {
      'revision': job['revision'],
      'target_id': target_key(job, 'SCREW@1|J8'),
      'result': 'pass',
      'criterion': '시연용',
      'standard': 'DEMO',
      'measured_value': '8',
      'grade': 'A',
      'sources': [source(bad_doc)],
      'confirmed': True,
    },
    422,
  )


def test_plan_keeps_multiple_processes_for_the_same_target(workspace: dict) -> None:
  spec = submitted_specification(workspace)
  job = new_job(workspace, spec)
  body = plan(workspace, job)
  extra = deepcopy(body['lines'][0])
  extra.update(process='추가 공정', start='2026-11-02T10:00:00+09:00', end='2026-11-02T11:00:00+09:00')
  body['lines'].append(extra)
  confirmed = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  assert confirmed['plan_version'] == 1
  with workspace['factory']() as session:
    from backend.models.workflow import ProductionPlan

    saved = session.scalar(select(ProductionPlan).where(ProductionPlan.job_id == job['id']))
    assert len(saved.data['lines']) == 4
    assert saved.data['quantity'] == 10


def test_common_definitions_merge_shared_parts_without_copying_other_product_approval(workspace: dict) -> None:
  source_spec = submitted_specification(workspace)
  draft = request(
    workspace,
    'rd',
    '/specifications',
    {
      'code': 'NEW',
      'name': '새 카메라',
      'product_type': 'film',
      'graph': {'root': 'NEW@1', 'items': [{'key': 'NEW@1', 'code': 'NEW', 'name': '새 카메라', 'kind': 'product'}]},
    },
    201,
  )
  for key in ('LENS@1', 'BODY@1'):
    draft = request(
      workspace,
      'rd',
      f'/specifications/{draft["id"]}/items',
      {
        'revision': draft['revision'],
        'source_specification_id': source_spec['id'],
        'item_key': key,
      },
    )
  assert sum(item['code'] == 'SCREW' for item in draft['graph']['items']) == 1
  graph = draft['graph']
  root = graph['items'][0]
  root['confirmed'] = True
  root['attributes'] = deepcopy(graph['items'][1]['attributes'])
  imported_source = root['attributes'][0]['source']
  graph['relations'].extend(
    [
      {
        'parent': 'NEW@1',
        'child': key,
        'quantity': 1,
        'condition': 'common',
        'confirmed': True,
        'source': imported_source,
      }
      for key in ('LENS@1', 'BODY@1')
    ]
  )
  draft = request(
    workspace,
    'rd',
    f'/specifications/{draft["id"]}',
    {
      'revision': draft['revision'],
      'graph': graph,
    },
    method='put',
  )
  request(workspace, 'rd', f'/specifications/{draft["id"]}/submit', {'revision': draft['revision']}, 422)
  own_detail = document(workspace, 'rd', 'product_detail', specification_id=draft['id'])
  graph['items'][0]['attributes'][0]['source'] = source(own_detail)
  draft = request(
    workspace,
    'rd',
    f'/specifications/{draft["id"]}',
    {
      'revision': draft['revision'],
      'graph': graph,
    },
    method='put',
  )
  confirmed = request(workspace, 'rd', f'/specifications/{draft["id"]}/submit', {'revision': draft['revision']})
  job = new_job(workspace, confirmed)
  assert all(target['status'] == 'waiting' and not target['inspection_id'] for target in job['targets'].values())
