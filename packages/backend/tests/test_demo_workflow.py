import csv
from copy import deepcopy
from pathlib import Path

import pytest
from backend.demo import PRODUCTS, generate_demo
from backend.models import File
from backend.models.file import FileStatus
from backend.models.workflow import Specification, WorkflowEvent
from sqlalchemy import select

from .test_workflow_api import extract, new_job, produce, request


def fixture_document(workspace: dict, role: str, kind: str, path: Path, **scope: object) -> dict:
  with workspace['factory']() as session:
    file = File(
      uploader_id=workspace['users'][role].id,
      bucket='demo',
      key=str(path),
      original_filename=path.name,
      content_type='text/csv',
      status=FileStatus.UPLOADED,
    )
    session.add(file)
    session.commit()
    file_id = file.id
  doc = request(workspace, role, '/documents', {'file_id': file_id, 'kind': kind, **scope}, 201)
  return extract(workspace, role, doc['id'], {})


def rows(doc: dict) -> list[dict]:
  assert doc['candidates']['status'] == 'ready', doc.get('error')
  return doc['candidates']['data']['rows']


def evidence(doc: dict, row: dict) -> dict:
  return {'document_id': doc['id'], 'page': int(row['page']), 'row': row['row']}


def confirm_graph(workspace: dict, spec: dict, doc: dict) -> dict:
  graph = deepcopy(doc['candidates']['data'])
  for item in graph['items']:
    item['confirmed'] = True
    for attribute in item['attributes']:
      attribute['confirmed'] = True
  for edge in graph['relations']:
    edge['confirmed'] = True
  spec = request(
    workspace, 'rd', f'/specifications/{spec["id"]}', {'revision': spec['revision'], 'graph': graph}, method='put'
  )
  return request(workspace, 'rd', f'/specifications/{spec["id"]}/submit', {'revision': spec['revision']})


def quality(workspace: dict, job: dict, key: str, documents: list[dict]) -> dict:
  target = job['targets'][key]
  sources = []
  values = {}
  for doc in documents:
    row = next(
      row for row in rows(doc) if row['item_code'] == target['code'] and int(row['version']) == target['version']
    )
    sources.append(evidence(doc, row))
    values = {field: row[field] for field in ('criterion', 'standard', 'measured_value', 'unit', 'grade', 'result')}
  return request(
    workspace,
    'qa',
    f'/jobs/{job["id"]}/inspect',
    {
      'revision': job['revision'],
      'target_id': key,
      'confirmed': True,
      'sources': sources,
      **values,
    },
  )


@pytest.fixture
def real_documents(workspace: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
  generate_demo(tmp_path)

  class Storage:
    def download(self, key: str, stream: object) -> None:
      stream.write(Path(key).read_bytes())

  monkeypatch.setattr('backend.services.work_documents.get_storage', lambda bucket: Storage())
  return tmp_path


def test_four_real_document_bundles_complete_via_api_with_independent_states(
  workspace: dict, real_documents: Path
) -> None:
  # Given four fictional bundles, when source documents are confirmed, then all jobs finish independently.
  completed = []
  for product_type, (code, name) in PRODUCTS.items():
    directory = real_documents / product_type
    spec = request(
      workspace,
      'rd',
      '/specifications',
      {
        'code': code,
        'name': name,
        'product_type': product_type,
        'graph': {'root': f'{code}@1', 'items': [{'key': f'{code}@1', 'code': code, 'name': name, 'kind': 'product'}]},
      },
      201,
    )
    doc = fixture_document(
      workspace, 'rd', 'product_detail', directory / 'product_detail.csv', specification_id=spec['id']
    )
    fixture_document(workspace, 'rd', 'bom_transfer', directory / 'bom_transfer.csv', specification_id=spec['id'])
    spec = confirm_graph(workspace, spec, doc)
    job = new_job(workspace, spec)
    production_targets = [key for key, target in job['targets'].items() if target['kind'] != 'material']
    plan_docs = [
      fixture_document(
        workspace,
        'pm',
        kind,
        directory / f'{kind}.csv',
        job_id=job['id'],
        target_ids=production_targets,
        plan_version=1,
      )
      for kind in ('production_plan',)
    ]
    lines = []
    for row in rows(plan_docs[0]):
      line = {
        field: row[field]
        for field in (
          'target_id',
          'process',
          'track',
          'unit',
          'duration_unit',
          'time_basis',
          'resource',
          'start',
          'end',
        )
      }
      line.update(
        quantity=float(row['quantity']),
        duration=float(row['duration']),
        predecessors=[],
        sources=[
          evidence(doc, next(candidate for candidate in rows(doc) if candidate['target_id'] == row['target_id']))
          for doc in plan_docs
        ],
      )
      lines.append(line)
    job = request(
      workspace,
      'pm',
      f'/jobs/{job["id"]}/plans',
      {
        'revision': job['revision'],
        'quantity': 10,
        'reason': '가상 시연 계획 확인',
        'confirmed': True,
        'lines': lines,
      },
      201,
    )
    material_targets = [key for key, target in job['targets'].items() if target['kind'] == 'material']
    material_docs = [
      fixture_document(workspace, 'qa', kind, directory / f'{kind}.csv', job_id=job['id'], target_ids=material_targets)
      for kind in ('incoming_inspection',)
    ]
    for key in material_targets:
      job = quality(workspace, job, key, material_docs)
    reports = {}
    for target_kind, kind in {
      'component': 'inspection_module1',
      'assembly': 'inspection_module2',
      'product': 'inspection_final',
    }.items():
      reports[target_kind] = fixture_document(
        workspace,
        'qa',
        kind,
        directory / f'{kind}.csv',
        job_id=job['id'],
        target_ids=[key for key, target in job['targets'].items() if target['kind'] == target_kind],
        plan_version=1,
      )
    for line in lines:
      key = line['target_id']
      job = quality(workspace, produce(workspace, job, key), key, [reports[job['targets'][key]['kind']]])
    assert job['status'] == 'completed'
    completed.append(job['id'])
  assert len(set(completed)) == 4


def test_selective_version_change_preserves_other_branch_and_all_original_snapshots(workspace: dict) -> None:
  from .test_workflow_api import document, inspection, plan, source, submitted_specification, target_key

  spec = submitted_specification(workspace)
  original_graph = deepcopy(spec['graph'])
  job = new_job(workspace, spec)
  job = request(workspace, 'pm', f'/jobs/{job["id"]}/plans', plan(workspace, job), 201)
  job = inspection(workspace, job, 'SCREW@1|J8')
  for key in ('LENS@1|common', 'BODY@1|common', 'CAM@1|root'):
    job = inspection(workspace, produce(workspace, job, key), key)
  body_id = target_key(job, 'BODY@1|common')
  body_pass = job['targets'][body_id]['inspection_id']
  draft = request(
    workspace,
    'rd',
    '/specifications',
    {
      'code': spec['code'],
      'name': spec['name'],
      'product_type': 'digital',
      'previous_id': spec['id'],
      'reason': '촬영 모듈만 다른 나사 버전으로 변경',
      'graph': spec['graph'],
    },
    201,
  )
  graph = draft['graph']
  screw = deepcopy(next(item for item in graph['items'] if item['code'] == 'SCREW'))
  screw.update(key='SCREW@2', version=2)
  graph['items'].append(screw)
  for item in graph['items']:
    if item['code'] in ('CAM', 'LENS'):
      item['key'] = item['key'].replace('@1', '@2')
      item['version'] = 2
  graph['root'] = 'CAM@2'
  for edge in graph['relations']:
    for field in ('parent', 'child'):
      if edge[field] in ('CAM@1', 'LENS@1'):
        edge[field] = edge[field].replace('@1', '@2')
    if edge['parent'] == 'LENS@2' and edge['child'] == 'SCREW@1':
      edge.update(child='SCREW@2', condition='J10')
  draft = request(
    workspace, 'rd', f'/specifications/{draft["id"]}', {'revision': draft['revision'], 'graph': graph}, method='put'
  )
  revised = request(workspace, 'rd', f'/specifications/{draft["id"]}/submit', {'revision': draft['revision']})
  job = request(
    workspace,
    'rd',
    f'/jobs/{job["id"]}/rework',
    {
      'revision': job['revision'],
      'target_id': target_key(job, 'LENS@1|common'),
      'cause': 'specification',
      'reason': '촬영 모듈의 사용 조건만 선택 변경',
      'specification_id': revised['id'],
    },
  )
  assert job['targets'][body_id]['inspection_id'] == body_pass
  assert job['targets'][body_id]['status'] == 'passed'
  assert (
    next(target for target in job['targets'].values() if target['code'] == 'SCREW' and target['version'] == 1)[
      'quantity'
    ]
    == 60
  )
  assert (
    next(target for target in job['targets'].values() if target['code'] == 'SCREW' and target['version'] == 2)[
      'quantity'
    ]
    == 40
  )
  with workspace['factory']() as session:
    assert session.get(Specification, spec['id']).graph == original_graph
    assert session.get(WorkflowEvent, body_pass).data['result'] == 'pass'
