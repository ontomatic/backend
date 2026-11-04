from copy import deepcopy

import pytest
from backend.core.jwt import create_access_token
from backend.models.workflow import ProductionJob, Specification, WorkDocument
from sqlalchemy import select

from .test_workflow_api import new_job, submitted_specification


@pytest.fixture
def flat_job(workspace: dict) -> dict:
  spec = submitted_specification(workspace)
  with workspace['factory']() as session:
    stored = session.get(Specification, spec['id'])
    graph = deepcopy(stored.graph)
    graph['relations'] = [
      {**graph['relations'][0], 'child': item['key'], 'quantity': quantity}
      for item, quantity in zip(graph['items'][1:], [2, 1, 12], strict=True)
    ]
    doc = session.scalar(select(WorkDocument).where(WorkDocument.specification_id == spec['id']))
    doc.blocks = [
      {
        'kind': 'table',
        'rows': [['품목명', '속성', '속성값'], [name, '길이', '8 mm']],
        'location': {'block_index': index, 'section_title': title},
      }
      for index, name, title in [
        (9, '렌즈', '01. 광학 사양 (렌즈 모듈)'),
        (11, '본체', '02. 센서 사양 (본체 모듈)'),
        (13, '나사', '03. 부속품 사양'),
      ]
    ]
    for item, block in zip(graph['items'][1:], [9, 11, 13], strict=True):
      if item['kind'] == 'assembly':
        item['kind'] = 'component'
      item['attributes'][0]['source'] = {'document_id': doc.id, 'page': None, 'block_index': block, 'row': '2'}
    stored.graph = graph
    session.commit()
  return new_job(workspace, spec)


def reload_job(workspace: dict, job: dict) -> dict:
  response = workspace['client'].get(
    f'/api/v1/workspace/jobs/{job["id"]}',
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["pm"].id)}'},
  )
  assert response.status_code == 200, response.text
  return response.json()


def test_specification_module_groups_are_available_without_work_instructions(workspace: dict, flat_job: dict) -> None:
  # Given source module headings, when creating/reloading a flat BOM job, then only display groups are added.
  targets = {target['code']: target for target in flat_job['targets'].values()}
  assert flat_job['composition_groups'] == [
    {'name': '렌즈 모듈', 'target_ids': [targets['LENS']['id']]},
    {'name': '본체 모듈', 'target_ids': [targets['BODY']['id']]},
  ]
  assert reload_job(workspace, flat_job)['composition_groups'] == flat_job['composition_groups']
  assert len(flat_job['targets']) == 4
  assert [targets[code]['quantity'] for code in ('LENS', 'BODY', 'SCREW')] == [20, 10, 120]
  assert all(set(group) == {'name', 'target_ids'} for group in flat_job['composition_groups'])


def test_display_grouping_preserves_existing_production_state(workspace: dict, flat_job: dict) -> None:
  # Given an approved round, when reading groups, then quantities, dependencies, and evidence stay fixed.
  with workspace['factory']() as session:
    stored = session.get(ProductionJob, flat_job['id'])
    targets = deepcopy(stored.targets)
    part = next(target for target in targets.values() if target['code'] == 'LENS')
    part.update(status='passed', round=2, completion_id='completion', inspection_id='inspection')
    stored.targets = targets
    session.commit()
    original = deepcopy(stored.targets)
    revision = stored.revision
  result = reload_job(workspace, flat_job)
  assert result['composition_groups'] == flat_job['composition_groups']
  with workspace['factory']() as session:
    stored = session.get(ProductionJob, flat_job['id'])
    assert stored.targets == original
    assert stored.revision == revision


@pytest.mark.parametrize('case', ['unreadable_document', 'unreferenced_block', 'existing_bom_parent'])
def test_module_grouping_requires_readable_source_and_preserves_explicit_bom_parents(
  workspace: dict, flat_job: dict, case: str
) -> None:
  # Given missing source context or a real BOM parent, when grouping, then no replacement module is invented.
  with workspace['factory']() as session:
    doc = session.scalar(select(WorkDocument).where(WorkDocument.specification_id == flat_job['specification_id']))
    if case == 'unreadable_document':
      doc.status = 'error'
    else:
      spec = session.get(Specification, flat_job['specification_id'])
      graph = deepcopy(spec.graph)
      if case == 'unreferenced_block':
        for item in graph['items']:
          for attr in item['attributes']:
            attr['source']['block_index'] = 99
      else:
        stored = session.get(ProductionJob, flat_job['id'])
        targets = deepcopy(stored.targets)
        by_code = {target['code']: target for target in targets.values()}
        by_code['LENS']['children'] = [by_code['SCREW']['id']]
        by_code['BODY']['children'] = [by_code['SCREW']['id']]
        by_code['CAM']['children'].remove(by_code['SCREW']['id'])
        stored.targets = targets
      spec.graph = graph
    session.commit()
  assert reload_job(workspace, flat_job)['composition_groups'] == []
