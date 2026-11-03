from copy import deepcopy

import pytest
from backend.core.jwt import create_access_token
from backend.models.workflow import ProductionJob, ProductionPlan, WorkDocument
from sqlalchemy import select

from .test_workflow_api import document, new_job, request, submitted_specification


def daily_plan(workspace: dict, job: dict) -> dict:
  target_ids = [key for key, target in job['targets'].items() if target['kind'] != 'material']
  doc_id = document(
    workspace, 'pm', 'production_plan', job_id=job['id'], target_ids=target_ids, plan_version=job['plan_version'] + 1
  )
  tables = [
    [['품목', '수량', '시작', '종료'], ['카메라', '120대', '2026-11-02', '2026-11-03']],
    [
      ['공정번호', '공정', '시작', '종료', '기간 (근무일)', '선행 작업'],
      ['P-01', '가공', '2026-11-02', '2026-11-02', '1', '—'],
      ['P-02', '조립', '2026-11-03', '2026-11-03', '1', 'P-01'],
    ],
    [['품목', '공정', '담당자'], ['카메라', 'P-01 가공', '작업자1'], ['카메라', 'P-02 조립', '작업자2']],
  ]
  with workspace['factory']() as session:
    doc = session.get(WorkDocument, doc_id)
    doc.blocks = [
      {'kind': 'table', 'rows': rows, 'location': {'page_number': index}} for index, rows in enumerate(tables, start=1)
    ]
    session.commit()

  def source(page: int, row: int) -> dict:
    return {'document_id': doc_id, 'page': page, 'row': str(row)}

  return {
    'revision': job['revision'],
    'quantity': 120,
    'reason': '원문의 날짜·근무일과 작업자 배정 확인',
    'confirmed': True,
    'schedule': [
      {
        'kind': 'summary',
        'process': '카메라',
        'track': '카메라',
        'quantity': '120대',
        'start': '2026-11-02',
        'end': '2026-11-03',
        'sources': [source(1, 2)],
      },
      {
        'kind': 'operation',
        'code': 'P-01',
        'process': '가공',
        'track': '카메라',
        'start': '2026-11-02',
        'end': '2026-11-02',
        'working_days': 1,
        'resource': '작업자1',
        'sources': [source(2, 2), source(3, 2)],
      },
      {
        'kind': 'operation',
        'code': 'P-02',
        'process': '조립',
        'track': '카메라',
        'start': '2026-11-03',
        'end': '2026-11-03',
        'working_days': 1,
        'resource': '작업자2',
        'predecessors': ['P-01'],
        'sources': [source(2, 3), source(3, 3)],
      },
    ],
  }


def test_date_only_plan_is_saved_and_reloaded_without_fabricated_times(workspace: dict) -> None:
  # Given three separate source tables, when confirming a day plan, then dates and BOM quantities survive reload.
  job = new_job(workspace, submitted_specification(workspace))
  body = daily_plan(workspace, job)
  result = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  assert result['quantity'] == 120
  assert result['plan_version'] == 1
  assert all(target['status'] == 'waiting' for target in result['targets'].values())
  assert all(target['plan_version'] == 1 for target in result['targets'].values() if target['kind'] != 'material')
  with workspace['factory']() as session:
    saved = session.scalar(select(ProductionPlan).where(ProductionPlan.job_id == job['id']))
    assert saved.data['lines'] == []
    assert saved.data['schedule'][1]['start'] == saved.data['schedule'][1]['end'] == '2026-11-02'
    assert saved.data['schedule'][1]['working_days'] == 1
    assert saved.data['schedule'][2]['predecessors'] == ['P-01']
    assert len(saved.data['schedule'][1]['sources']) == 2
    assert 'duration' not in saved.data['schedule'][1]
    assert saved.data['warnings'] == []
  response = workspace['client'].get(
    f'/api/v1/workspace/jobs/{job["id"]}/plans',
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["pm"].id)}'},
  )
  assert response.status_code == 200
  assert response.json()[0]['data']['schedule'][1]['start'] == '2026-11-02'


@pytest.mark.parametrize(
  'failure', ['dates', 'quantity', 'cycle', 'missing_predecessor', 'duplicate', 'unconfirmed', 'omitted', 'resource']
)
def test_date_plan_rejects_invalid_or_unconfirmed_changes(workspace: dict, failure: str) -> None:
  job = new_job(workspace, submitted_specification(workspace))
  body = daily_plan(workspace, job)
  if failure == 'dates':
    body['schedule'][1]['start'] = '2026-11-01'
  elif failure == 'quantity':
    body['quantity'] = 1
  elif failure == 'cycle':
    body['schedule'][1]['predecessors'] = ['P-02']
  elif failure == 'missing_predecessor':
    body['schedule'][1]['predecessors'] = ['UNKNOWN']
  elif failure == 'duplicate':
    body['schedule'].append(deepcopy(body['schedule'][1]))
  elif failure == 'omitted':
    body['schedule'].pop()
  elif failure == 'resource':
    body['schedule'][1]['resource'] = '원문에 없는 작업자'
  else:
    body['confirmed'] = False
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 422)
  with workspace['factory']() as session:
    assert session.get(ProductionJob, job['id']).plan_version == 0


def test_daily_plan_requires_acknowledgement_for_source_schedule_conflicts(workspace: dict) -> None:
  # Given overlapping dates in the original, when saving, then acknowledgement is required.
  job = new_job(workspace, submitted_specification(workspace))
  body = daily_plan(workspace, job)
  body['schedule'][1]['end'] = '2026-11-03'
  with workspace['factory']() as session:
    doc = session.get(WorkDocument, body['schedule'][0]['sources'][0]['document_id'])
    blocks = deepcopy(doc.blocks)
    blocks[1]['rows'][1][3] = '2026-11-03'
    doc.blocks = blocks
    session.commit()
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 422)
  body['acknowledged_warnings'] = True
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)


def test_replanning_a_daily_schedule_rechecks_covered_production_targets(workspace: dict) -> None:
  job = new_job(workspace, submitted_specification(workspace))
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', daily_plan(workspace, job), 201)
  body = daily_plan(workspace, job)
  body['schedule'][1]['resource'] = '교대 작업자'
  with workspace['factory']() as session:
    doc = session.get(WorkDocument, body['schedule'][0]['sources'][0]['document_id'])
    blocks = deepcopy(doc.blocks)
    blocks[2]['rows'][1][2] = '교대 작업자'
    doc.blocks = blocks
    session.commit()
  updated = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  assert updated['plan_version'] == 2
  assert all(target['plan_version'] == 2 for target in updated['targets'].values() if target['kind'] != 'material')


def test_date_plan_keeps_department_and_document_scope_checks(workspace: dict) -> None:
  job = new_job(workspace, submitted_specification(workspace))
  body = daily_plan(workspace, job)
  request(workspace, 'qa', f'/jobs/{job["id"]}/plans', body, 403)
  with workspace['factory']() as session:
    doc = session.get(WorkDocument, body['schedule'][0]['sources'][0]['document_id'])
    doc.scope = {**doc.scope, 'target_ids': [next(iter(job['targets']))]}
    session.commit()
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 422)
