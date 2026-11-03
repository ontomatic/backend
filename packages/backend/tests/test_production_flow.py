from copy import deepcopy
from pathlib import Path

import pytest
from backend.core.jwt import create_access_token
from backend.exceptions.workflow import WorkflowError
from backend.models.workflow import WorkflowEvent
from backend.services.production_flow import configure_processes, rebuild_allocations, remaining_outputs, reserve_inputs
from sqlalchemy import select

from .test_daily_plan import daily_plan
from .test_demo_workflow import fixture_document
from .test_workflow_api import new_job, request, submitted_specification


@pytest.mark.parametrize('with_instruction', [False, True])
def test_document_processes_accept_actual_lots_and_reject_stock_overuse(
  workspace: dict, monkeypatch, tmp_path: Path, with_instruction: bool
) -> None:
  # Given real work-order/count tables, only source-backed good quantities may move to the next process.
  job = new_job(workspace, submitted_specification(workspace), 120)

  class Storage:
    def download(self, key: str, stream: object) -> None:
      stream.write(Path(key).read_bytes() if Path(key).exists() else b'field,value,unit\nlength,8,mm\n')

  monkeypatch.setattr('backend.services.work_documents.get_storage', lambda bucket: Storage())
  instruction = tmp_path / 'instruction.csv'
  instruction.write_text('공정번호,공정,투입 → 산출\nP-01,가공,원자재 → 부품\nP-02,조립,부품 → 모듈\n')
  doc = fixture_document(
    workspace, 'pm', 'work_instruction_module1', instruction, job_id=job['id'], target_ids=[], plan_version=1
  )
  job = (
    workspace['client']
    .get(
      f'/api/v1/workspace/jobs/{job["id"]}',
      headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["pm"].id)}'},
    )
    .json()
  )
  assert doc['scope']['target_ids'] == ['process:P-01', 'process:P-02']
  assert job['revision'] == 2
  # Retrying an auto-bound instruction must preserve its authoritative process scope.
  retried = request(
    workspace,
    'pm',
    '/documents',
    {
      'file_id': doc['file_id'],
      'kind': doc['kind'],
      'job_id': job['id'],
      'plan_version': 1,
    },
    201,
  )
  assert retried['id'] == doc['id'] and retried['scope'] == doc['scope']
  body = daily_plan(workspace, job)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 201)
  counts = tmp_path / 'counts.csv'
  counts.write_text('공정번호,투입,양품,불량\nP-01,120,119,1\nP-02,119,118,1\nP-02,120,119,1\nP-01,120,120,1\n')
  qa = fixture_document(
    workspace,
    'qa',
    'inspection_module1',
    counts,
    job_id=job['id'],
    target_ids=['process:P-01', 'process:P-02'],
    plan_version=1,
  )

  def source(row: int) -> list[dict]:
    return [{'document_id': qa['id'], 'page': 1, 'row': str(row)}]

  for code, amount, row in [('P-01', 120, 2), ('P-02', 119, 3)]:
    key = f'process:{code}'
    job = request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'target_id': key, 'revision': job['revision']})
    completion = {
      'target_id': key,
      'revision': job['revision'],
      'quantity': amount,
      'unit': '개',
      'sources': source(row),
      'confirmed': True,
    }
    invalid = completion | {'sources': source(5) if code == 'P-01' else source(4), 'quantity': 120}
    request(workspace, 'pm', f'/jobs/{job["id"]}/complete', invalid, 422)
    job = request(workspace, 'pm', f'/jobs/{job["id"]}/complete', completion)
    inspection = {
      'target_id': key,
      'revision': job['revision'],
      'sources': source(row),
      'confirmed': True,
      'result': 'pass',
      'criterion': '원문 실적',
      'standard': '시험 원문',
      'measured_value': str(amount - 1),
      'unit': '개',
      'good_quantity': amount - 1,
      'defect_quantity': 1,
    }
    if with_instruction:
      inspection['sources'].append({'document_id': doc['id'], 'page': 1, 'row': str(row)})
      request(
        workspace,
        'qa',
        f'/jobs/{job["id"]}/inspect',
        inspection | {'sources': [*inspection['sources'], {'document_id': 'unrelated', 'page': 1, 'row': '2'}]},
        422,
      )
    request(workspace, 'qa', f'/jobs/{job["id"]}/inspect', inspection | {'good_quantity': amount}, 422)
    request(workspace, 'pm', f'/jobs/{job["id"]}/inspect', inspection, 403)
    job = request(workspace, 'qa', f'/jobs/{job["id"]}/inspect', inspection)
    assert job['targets'][key]['status'] == 'partial'
  assert job['targets']['process:P-01']['remaining_quantity'] == 0
  assert job['targets']['process:P-02']['remaining_quantity'] == 118
  with workspace['factory']() as session:
    events = list(session.scalars(select(WorkflowEvent).where(WorkflowEvent.action == 'inspection')))
    assert [event.data['quantity'] for event in events] == [120, 119]
    assert all(event.data['quantity_unit'] == '개' and event.data['planned_quantity'] == 120 for event in events)
  request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'target_id': 'process:P-02', 'revision': 1}, 409)
  # Physical rework releases the previous reservation, while retaining immutable event history.
  job = request(
    workspace,
    'pm',
    f'/jobs/{job["id"]}/rework',
    {'revision': job['revision'], 'target_id': 'process:P-02', 'cause': 'physical', 'reason': '재작업'},
  )
  assert job['targets']['process:P-01']['remaining_quantity'] == 119
  assert job['targets']['process:P-02']['round'] == 2


def test_shared_instruction_reserves_each_output_once_and_rejects_double_spending() -> None:
  parent = {
    'id': 'source',
    'process_code': 'P-01',
    'name': '사출',
    'good_quantity': 10,
    'output_names': ['화면', '전원', '캡'],
    'allocations': {},
  }
  child = {
    'id': 'screen',
    'process_code': 'P-02',
    'instruction_group': 'shared',
    'round': 1,
    'name': '조립',
    'input_names': ['화면', '전원'],
    'predecessor_ids': ['source'],
    'output_names': ['모듈'],
  }
  targets = {'source': parent, 'screen': child, 'power': deepcopy(child) | {'id': 'power'}}
  for key in ('screen', 'power'):
    targets[key]['input_quantity'] = 10
    reserve_inputs(targets, targets[key], 10)
  assert remaining_outputs(parent) == {'화면': 0, '전원': 0, '캡': 10}
  rebuild_allocations(targets)
  assert len(parent['allocations']) == 1
  with pytest.raises(WorkflowError, match='양품 재고'):
    reserve_inputs(targets, child | {'instruction_group': 'separate'}, 1)


def test_inventory_links_cannot_introduce_a_cycle_with_the_final_process() -> None:
  targets = {
    'root': {'id': 'root', 'kind': 'product', 'process_code': 'P-02', 'children': ['part'], 'condition': ''},
    'part': {
      'id': 'part',
      'kind': 'component',
      'name': '부품',
      'quantity': 10,
      'condition': '자체 가공 (P-01)',
      'children': [],
    },
    'process': {
      'id': 'process',
      'kind': 'component',
      'process_code': 'P-01',
      'children': [],
      'condition': '',
      'output_names': ['부품'],
    },
  }
  schedule = [
    {'kind': 'operation', 'code': 'P-01', 'predecessors': ['P-02'], 'quantity': '10대분'},
    {'kind': 'operation', 'code': 'P-02', 'predecessors': [], 'quantity': '10대'},
  ]
  with pytest.raises(WorkflowError, match='순환 참조'):
    configure_processes(targets, schedule, 10)


def test_growing_a_shared_reservation_checks_its_previous_outputs_too() -> None:
  parent = {
    'id': 'source',
    'process_code': 'P-01',
    'name': '사출',
    'good_quantity': 10,
    'output_names': ['화면', '전원'],
    'allocations': {},
  }
  child = {
    'instruction_group': 'shared',
    'round': 1,
    'name': '조립',
    'input_names': ['화면'],
    'predecessor_ids': ['source'],
  }
  targets = {'source': parent}
  reserve_inputs(targets, child, 8)
  reserve_inputs(targets, child | {'instruction_group': 'other'}, 1)
  with pytest.raises(WorkflowError, match='양품 재고'):
    reserve_inputs(targets, child | {'input_names': ['전원']}, 10)
