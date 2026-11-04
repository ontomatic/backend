from pathlib import Path

from backend.core.jwt import create_access_token
from backend.models.workflow import WorkDocument

from .test_demo_workflow import fixture_document
from .test_workflow_api import document, inspection, new_job, request, source


def test_department_sequence_accepts_instructions_after_plan_and_requires_each_inspection(
  workspace: dict, monkeypatch, tmp_path: Path
) -> None:
  # Given a confirmed product with fourteen purchased parts and six first-module work groups.
  items = [
    {'key': 'CAM@1', 'code': 'CAM', 'name': '카메라', 'kind': 'product'},
    *[
      {'key': f'MAT-{index}@1', 'code': f'MAT-{index}', 'name': f'구매 부품 {index}', 'kind': 'material'}
      for index in range(14)
    ],
  ]
  graph = {
    'root': 'CAM@1',
    'items': items,
    'relations': [
      {'parent': 'CAM@1', 'child': item['key'], 'quantity': 1, 'condition': '구매', 'confirmed': True}
      for item in items[1:]
    ],
  }
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph},
    201,
  )
  detail = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  for item in items:
    item.update(
      confirmed=True,
      attributes=[{'field': 'length', 'value': 8, 'unit': 'mm', 'confirmed': True, 'source': source(detail)}],
    )
  for edge in graph['relations']:
    edge['source'] = source(detail)
  spec = request(workspace, 'rd', f'/specifications/{spec["id"]}', {'revision': 1, 'graph': graph}, method='put')
  request(workspace, 'rd', f'/specifications/{spec["id"]}/submit', {'revision': spec['revision']}, 422)
  document(workspace, 'rd', 'bom_transfer', specification_id=spec['id'])
  spec = request(workspace, 'rd', f'/specifications/{spec["id"]}/submit', {'revision': spec['revision']})
  job = new_job(workspace, spec)
  plan_id = document(workspace, 'pm', 'production_plan', job_id=job['id'], target_ids=['CAM@1|root'], plan_version=1)
  codes = [*[f'P-{index:02}' for index in range(1, 9)], 'P-16']
  dependencies = {**{code: [] for code in codes[:6]}, 'P-07': codes[:3], 'P-08': codes[3:6], 'P-16': codes[6:8]}
  dates = {
    **{code: '2026-11-04' for code in codes[:6]},
    'P-07': '2026-11-09',
    'P-08': '2026-11-09',
    'P-16': '2026-11-12',
  }
  with workspace['factory']() as session:
    session.get(WorkDocument, plan_id).blocks = [
      {
        'kind': 'table',
        'location': {'page_number': 1},
        'rows': [
          ['품목', '수량', '시작', '종료'],
          ['카메라', '10대', '2026-11-04', '2026-11-12'],
        ],
      },
      {
        'kind': 'table',
        'location': {'page_number': 2},
        'rows': [
          ['공정번호', '공정', '시작', '종료', '선행 작업', '담당자'],
          *[[code, code, dates[code], dates[code], ', '.join(dependencies[code]), f'작업자-{code}'] for code in codes],
        ],
      },
    ]
    session.commit()
  body = {
    'revision': job['revision'],
    'quantity': 10,
    'reason': '부서별 순차 생산',
    'confirmed': True,
    'schedule': [
      {
        'kind': 'summary',
        'process': '카메라',
        'quantity': '10대',
        'start': '2026-11-04',
        'end': '2026-11-12',
        'sources': [{'document_id': plan_id, 'page': 1, 'row': '2'}],
      },
      *[
        {
          'kind': 'operation',
          'code': code,
          'process': code,
          'start': dates[code],
          'end': dates[code],
          'predecessors': dependencies[code],
          'resource': f'작업자-{code}',
          'sources': [{'document_id': plan_id, 'page': 2, 'row': str(index + 2)}],
        }
        for index, code in enumerate(codes)
      ],
    ],
  }
  # When attempting to plan before incoming approval, the plan stays unconfirmed.
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body, 409)
  materials = [key for key, target in job['targets'].items() if target['kind'] == 'material']
  for key in materials[:-1]:
    job = inspection(workspace, job, key)
  request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body | {'revision': job['revision']}, 409)
  job = inspection(workspace, job, materials[-1])
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', body | {'revision': job['revision']}, 201)

  class Storage:
    def download(self, key: str, stream: object) -> None:
      stream.write(Path(key).read_bytes())

  monkeypatch.setattr('backend.services.work_documents.get_storage', lambda bucket: Storage())

  def reload() -> dict:
    response = workspace['client'].get(
      f'/api/v1/workspace/jobs/{job["id"]}',
      headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["pm"].id)}'},
    )
    assert response.status_code == 200
    return response.json()

  def instruction(kind: str, rows: list[str]) -> None:
    path = tmp_path / f'{kind}.csv'
    path.write_text('공정번호,공정,투입 → 산출\n' + '\n'.join(rows) + '\n')
    fixture_document(workspace, 'pm', kind, path, job_id=job['id'], target_ids=[], plan_version=1)

  def approve(current: dict, keys: list[str], kind: str) -> dict:
    path = tmp_path / f'{kind}-{current["targets"][keys[0]]["code"]}.csv'
    path.write_text(
      '공정번호,투입,양품,불량\n'
      + '\n'.join(f'{current["targets"][key]["process_code"]},10,10,0' for key in keys)
      + '\n'
    )
    report = fixture_document(workspace, 'qa', kind, path, job_id=job['id'], target_ids=keys, plan_version=1)
    for index, key in enumerate(keys, start=2):
      sources = [{'document_id': report['id'], 'page': 1, 'row': str(index)}]
      current = request(
        workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': current['revision'], 'target_id': key}
      )
      current = request(
        workspace,
        'pm',
        f'/jobs/{job["id"]}/complete',
        {
          'revision': current['revision'],
          'target_id': key,
          'quantity': 10,
          'unit': current['targets'][key]['unit'],
          'confirmed': True,
          'sources': sources,
        },
      )
      current = request(
        workspace,
        'qa',
        f'/jobs/{job["id"]}/inspect',
        {
          'revision': current['revision'],
          'target_id': key,
          'result': 'pass',
          'criterion': '수량 확인',
          'standard': '실적 원문',
          'measured_value': '10',
          'unit': current['targets'][key]['unit'],
          'good_quantity': 10,
          'defect_quantity': 0,
          'confirmed': True,
          'sources': sources,
        },
      )
    return current

  # Then work orders can be added to the confirmed plan without creating a new plan version.
  instruction('work_instruction_lens', ['P-07,렌즈 조립,모듈1 + 모듈2 + 모듈3 → 렌즈'])
  job = reload()
  assert job['targets']['process:P-07']['pending_predecessors'] == codes[:3]
  request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': job['revision'], 'target_id': 'process:P-07'}, 409)
  instruction(
    'work_instruction_module1',
    [f'{code},모듈 조립 {index},원자재 → 모듈{index}' for index, code in enumerate(codes[:6], start=1)],
  )
  job = reload()
  assert job['targets']['process:P-07']['pending_predecessors'] == []
  request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': job['revision'], 'target_id': 'process:P-07'}, 409)
  job = approve(job, [f'process:{code}' for code in codes[:5]], 'inspection_module1')
  # The lens inputs have passed, but the sixth first-module process still blocks the whole second stage.
  request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': job['revision'], 'target_id': 'process:P-07'}, 409)
  job = approve(job, ['process:P-06'], 'inspection_module1')
  instruction('work_instruction_body', ['P-08,본체 조립,모듈4 + 모듈5 + 모듈6 → 본체'])
  instruction('work_instruction_final', ['P-16,최종 결합·검사,렌즈 + 본체 → 카메라'])
  job = reload()
  job = approve(job, ['process:P-07'], 'inspection_module2')
  request(workspace, 'pm', f'/jobs/{job["id"]}/start', {'revision': job['revision'], 'target_id': 'CAM@1|root'}, 409)
  job = approve(job, ['process:P-08'], 'inspection_module2')
  assert job['status'] == 'active'
  job = approve(job, ['CAM@1|root'], 'inspection_final')
  assert job['status'] == 'completed'
  assert job['plan_version'] == 1
  assert job['production_result']['good_quantity'] == 10
