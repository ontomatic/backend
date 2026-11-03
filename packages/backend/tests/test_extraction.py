import asyncio
import json
from copy import deepcopy

import pytest
from backend.core.config import Settings
from backend.core.jwt import create_access_token
from backend.exceptions.workflow import WorkflowError
from backend.integrations.llm import factory
from backend.models.workflow import Specification, WorkDocument
from backend.schemas.workflow import Graph
from backend.services.extraction import (
  bom_transfer_graph,
  extraction_chunks,
  merge_graph_candidates,
  product_specification_items,
)
from backend.services.workflow import build_targets, validate_graph
from pydantic import SecretStr

from .test_workflow import graph
from .test_workflow_api import document, extract, new_job, request, source


def test_extraction_chunks_keep_table_headers_and_original_source_rows() -> None:
  # given
  rows = [['품목명', '값']] + [[f'부품-{index}', '가' * 600] for index in range(5)]
  blocks = [{'kind': 'table', 'rows': rows, 'location': {'block_index': 4, 'page_number': None}}]
  original = deepcopy(blocks)

  # when
  chunks = extraction_chunks(blocks)

  # then
  assert len(chunks) > 1
  assert all(len(json.dumps(chunk, ensure_ascii=False)) <= 2000 for chunk in chunks)
  pieces = [block for chunk in chunks for block in chunk]
  assert [piece['rows'][1] for piece in pieces] == rows[1:]
  assert [piece['row_numbers'] for piece in pieces] == [[1, row] for row in range(2, 7)]
  assert all(piece['rows'][0] == rows[0] and piece['location'] == blocks[0]['location'] for piece in pieces)
  assert blocks == original


def test_extraction_chunks_split_long_text_without_losing_original_block() -> None:
  # given
  text = '한글과 숫자 123 ' * 400
  location = {'block_index': 7, 'page_number': None}

  # when
  chunks = extraction_chunks([{'kind': 'text', 'text': text, 'location': location}])

  # then
  pieces = [block for chunk in chunks for block in chunk]
  assert ''.join(piece['text'] for piece in pieces) == text
  assert all(piece['location'] == location for piece in pieces)
  assert all(len(json.dumps(chunk, ensure_ascii=False)) <= 2000 for chunk in chunks)


def test_extraction_rejects_a_table_row_that_cannot_fit_without_truncation() -> None:
  with pytest.raises(WorkflowError):
    extraction_chunks([{'kind': 'table', 'rows': [['값'], ['가' * 3000]], 'location': {}}])


def test_extraction_sends_202_before_background_work_finishes(workspace: dict, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given an extractor that waits until after the response has been sent.
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])

  async def scenario() -> None:
    sent, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    messages = []

    async def extract(session, user, document_id, *, graph_candidate=False, on_progress=None):
      doc = session.get(WorkDocument, document_id)
      assert doc.candidates['status'] == 'extracting'
      assert graph_candidate is True
      started.set()
      await release.wait()
      doc.candidates = {'status': 'ready', 'data': graph()}
      return doc

    monkeypatch.setattr('backend.services.work_documents.extract_candidates', extract)

    async def receive() -> dict:
      return {'type': 'http.request', 'body': b'{"graph_candidate":true}', 'more_body': False}

    async def send(message: dict) -> None:
      messages.append(message)
      if message['type'] == 'http.response.body' and not message.get('more_body'):
        sent.set()

    token = create_access_token(workspace['users']['rd'].id)
    path = f'/api/v1/workspace/documents/{doc_id}/extract'
    scope = {
      'type': 'http',
      'asgi': {'version': '3.0'},
      'http_version': '1.1',
      'method': 'POST',
      'scheme': 'http',
      'path': path,
      'raw_path': path.encode(),
      'query_string': b'',
      'root_path': '',
      'headers': [(b'content-type', b'application/json'), (b'authorization', f'Bearer {token}'.encode())],
      'server': ('testserver', 80),
      'client': ('127.0.0.1', 1),
    }
    task = asyncio.create_task(workspace['client'].app(scope, receive, send))
    try:
      # When the response arrives, the background extractor is still waiting.
      await asyncio.wait_for(sent.wait(), 2)
      assert next(message for message in messages if message['type'] == 'http.response.start')['status'] == 202
      body = json.loads(b''.join(message.get('body', b'') for message in messages))
      assert body['candidates']['status'] == 'extracting'
      await asyncio.wait_for(started.wait(), 2)
      assert not task.done()
    finally:
      release.set()
      await asyncio.wait_for(task, 2)

  asyncio.run(scenario())
  # Then completion is available through a separate status request.
  response = workspace['client'].get(
    f'/api/v1/workspace/documents/{doc_id}',
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["rd"].id)}'},
  )
  assert response.status_code == 200
  assert response.json()['candidates']['status'] == 'ready'


def test_extraction_rejects_duplicate_jobs_and_checks_permissions(
  workspace: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given an accepted job whose background work has not finished.
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  calls = []

  async def pending(user_id, document_id, **kwargs):
    calls.append(document_id)

  monkeypatch.setattr('backend.services.work_documents.run_extraction', pending)

  # When the same job is submitted again, or another department tries to submit it.
  accepted = request(workspace, 'rd', f'/documents/{doc_id}/extract', {}, 202)
  request(workspace, 'rd', f'/documents/{doc_id}/extract', {}, 409)
  request(workspace, 'qa', f'/documents/{doc_id}/extract', {}, 403)

  # Then only one job is scheduled and the pending state is durable across requests.
  assert accepted['candidates']['status'] == 'extracting'
  assert accepted['candidates']['progress']['stage'] == 'queued'
  assert accepted['candidates']['progress']['started_at']
  assert calls == [doc_id]
  with workspace['factory']() as session:
    assert session.get(WorkDocument, doc_id).candidates['status'] == 'extracting'


def test_background_failure_is_queryable_and_keeps_previous_candidates(
  workspace: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given useful extracted rows before a background worker fails unexpectedly.
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  previous = {'rows': [{'name': '렌즈', 'value': '광학 유리'}]}
  with workspace['factory']() as session:
    session.get(WorkDocument, doc_id).candidates = {'status': 'ready', 'data': previous}
    session.commit()

  async def unavailable(*args, **kwargs):
    raise ConnectionError('unavailable')

  monkeypatch.setattr('backend.services.work_documents.extract_candidates', unavailable)

  # When background extraction fails, then the status API reports it without losing the previous data.
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})
  assert result['candidates']['status'] == 'error'
  assert result['candidates']['data'] == previous
  assert result['candidates']['progress']['stage'] == 'failed'
  assert result['error']


def test_merging_chunk_candidates_keeps_conflicting_attributes_for_review() -> None:
  # given
  first = Graph.model_validate(graph()).model_dump(mode='json')
  second = deepcopy(first)
  first['items'][1]['attributes'] = [{'field': 'length', 'value': 8, 'unit': 'mm'}]
  second['items'][1]['attributes'] = [{'field': 'length', 'value': 9, 'unit': 'mm'}]
  second['items'][1]['name'] = '렌즈부'

  # when
  result = merge_graph_candidates([first, second], first['items'][0])

  # then
  assert len(result['items']) == len(first['items'])
  assert len(result['relations']) == len(first['relations'])
  assert [attribute['value'] for attribute in result['items'][1]['attributes']] == [8, 9]
  assert '렌즈부' in result['items'][1]['aliases']
  assert len(first['items'][1]['attributes']) == 1


def test_merging_chunk_candidates_rejects_conflicting_item_identities() -> None:
  first = Graph.model_validate(graph()).model_dump(mode='json')
  second = deepcopy(first)
  second['items'][1]['kind'] = 'material'
  with pytest.raises(WorkflowError):
    merge_graph_candidates([first, second], first['items'][0])


@pytest.mark.parametrize(
  'row',
  [
    {'name': '렌즈', 'field': '재질', 'value': '유리', 'version': '2'},
    {'name': '렌즈', 'field': '사양 버전', 'value': '2'},
    {'name': '렌즈', 'field': '재질', 'value': '유리', 'original': {'상위 품목': 'CAM'}},
    {'name': '렌즈', 'field': '재질', 'value': '유리', 'original': {'품목코드': 'LENS'}},
  ],
)
def test_flat_specification_path_does_not_drop_versions_or_bom_columns(row: dict) -> None:
  assert product_specification_items('doc', [row], graph()['items'][0]) is None


@pytest.mark.parametrize('valid', [True, False])
def test_korean_specification_only_generates_kinds_and_preserves_every_fact(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  with workspace['factory']() as session:
    session.get(WorkDocument, doc_id).blocks = [
      {'kind': 'table', 'rows': [['항목', '값'], ['모델명', 'CAM']], 'location': {'block_index': 1}},
      {
        'kind': 'table',
        'rows': [
          ['부품', '구성 상세', '속성', '속성값'],
          ['렌즈', '광축 중심 편차', '허용값', '0.030 mm 이하'],
          ['렌즈', 'MTF 중심부', '허용값', '0.70 이상'],
          ['경통', '렌즈 교환식 경통', '재질', '알루미늄 합금'],
        ],
        'location': {'block_index': 2},
      },
    ]
    session.commit()
  calls = []

  class LLM:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
      calls.append(prompt)
      assert [item['name'] for item in json.loads(prompt)] == ['렌즈', '경통']
      return json.dumps({'0': 'material', '1': 'component'} if valid else {'0': 'product'})

  def create_llm(*, output_schema: dict) -> LLM:
    assert set(output_schema['properties']) == {'0', '1'}
    assert output_schema['additionalProperties'] is False
    return LLM()

  monkeypatch.setattr('backend.services.work_documents.create_llm', create_llm)
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})
  assert len(calls) == 1
  if not valid:
    assert result['error']
    assert len(result['candidates']['data']['rows']) == 4
    return
  assert result['error'] is None
  assert result['candidates']['method'] == 'structured_specification'
  data = result['candidates']['data']
  assert data['root'] == spec['graph']['root']
  assert data['relations'] == []
  assert [item['key'] for item in data['items']] == [data['root'], '렌즈@1', '경통@1']
  attributes = [attribute for item in data['items'] for attribute in item['attributes']]
  assert [attribute['value'] for attribute in attributes] == ['CAM', '0.030 mm 이하', '0.70 이상', '알루미늄 합금']
  assert [attribute['field'] for attribute in data['items'][1]['attributes']] == [
    '광축 중심 편차 · 허용값',
    'MTF 중심부 · 허용값',
  ]
  assert [(a['source']['block_index'], a['source']['row']) for a in attributes] == [
    (1, '2'),
    (2, '2'),
    (2, '3'),
    (2, '4'),
  ]
  assert all(a['source']['document_id'] == doc_id and not a['confirmed'] for a in attributes)
  assert all(not item['confirmed'] for item in data['items'])


def test_korean_bom_only_classifies_real_parts_and_preserves_source_relationships(
  workspace: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given a flat BOM alongside document metadata and transfer references.
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'bom_transfer', specification_id=spec['id'])
  with workspace['factory']() as session:
    session.get(WorkDocument, doc_id).blocks = [
      {
        'kind': 'table',
        'rows': [['문서번호', 'D100-BOM-02', '버전', '1.0'], ['대상 모델', 'CAM', '생산 로트', 'D100-20261102-01']],
        'location': {'block_index': 3},
      },
      {
        'kind': 'table',
        'rows': [
          ['순번', '품목코드', '품목명', '대당 수량', '조달·공급'],
          ['1', 'LENS', '렌즈 (다층 코팅 광학 유리)', '1', '자체 가공 (D100-02)'],
          ['2', 'SCREW', '나사', '4', '구매'],
        ],
        'location': {'block_index': 6},
      },
      {
        'kind': 'table',
        'rows': [['분류', '확인 내용'], ['참조 문서', 'D100-사양-01 v2.0 → D100-BOM-02']],
        'location': {'block_index': 8},
      },
    ]
    session.commit()

  def unexpected_llm(**kwargs: object) -> None:
    pytest.fail('Explicit procurement kinds do not require LLM classification.')

  monkeypatch.setattr('backend.services.work_documents.create_llm', unexpected_llm)

  # When graph candidates are requested through the document API.
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})

  # Then only source BOM parts and edges are returned, with no invented document relationships.
  assert result['error'] is None
  assert result['candidates']['method'] == 'structured_bom'
  data = result['candidates']['data']
  assert [item['key'] for item in data['items']] == ['CAM@1', 'LENS@1', 'SCREW@1']
  assert [item['code'] for item in data['items']] == ['CAM', 'LENS', 'SCREW']
  assert [item['kind'] for item in data['items']] == ['product', 'component', 'material']
  assert data['items'][1]['aliases'] == ['렌즈']
  assert [(edge['parent'], edge['child'], edge['quantity'], edge['condition']) for edge in data['relations']] == [
    ('CAM@1', 'LENS@1', 1, '자체 가공 (D100-02)'),
    ('CAM@1', 'SCREW@1', 4, '구매'),
  ]
  for index, edge in enumerate(data['relations'], start=2):
    assert edge['source'] == {
      'document_id': doc_id,
      'page': None,
      'block_index': 6,
      'row': str(index),
      'original_field': '대당 수량',
      'original_value': '1' if index == 2 else '4',
      'original_unit': '',
    }
    assert not edge['confirmed']
  assert all(not item['confirmed'] for item in data['items'])
  validate_graph(data)


def test_flat_bom_does_not_offer_an_ambiguous_short_name_for_merging() -> None:
  # Given different BOM codes whose descriptions share the same short name.
  rows = [
    {'item_code': 'LENS-A', 'name': '렌즈 (광학 유리)', 'quantity_per_product': '1', 'row': '2'},
    {'item_code': 'LENS-B', 'name': '렌즈 (플라스틱)', 'quantity_per_product': '1', 'row': '3'},
  ]

  # When extracting identities, then neither variant claims the unspecified specification name.
  result = bom_transfer_graph('bom', rows, graph()['items'][0])
  assert [item['aliases'] for item in result['items'][1:]] == [[], []]


@pytest.mark.parametrize('quantity', ['0', '-1', 'nan', 'inf', '1000000001', 'one'])
def test_flat_bom_rejects_invalid_source_quantities(quantity: str) -> None:
  rows = [{'item_code': 'LENS', 'name': '렌즈', 'quantity_per_product': quantity, 'row': '2'}]
  with pytest.raises(WorkflowError):
    bom_transfer_graph('bom', rows, graph()['items'][0])


@pytest.mark.parametrize('column', ['품목 버전', '레벨'])
def test_bom_leaves_unsupported_layouts_to_the_full_extractor(column: str) -> None:
  rows = [
    {
      'item_code': 'LENS',
      'name': '렌즈',
      'quantity_per_product': '1',
      'row': '2',
      'original': {'품목코드': 'LENS', '품목명': '렌즈', '대당 수량': '1', column: '2'},
    }
  ]
  assert bom_transfer_graph('bom', rows, graph()['items'][0]) is None


@pytest.mark.parametrize(
  'quantity_header,quantities', [('소요 수량', ['2', '3', '4']), ('대당 수량', ['2', '6', '24'])]
)
def test_korean_bom_hierarchy_survives_extraction_submission_and_job_reload(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, quantity_header: str, quantities: list[str]
) -> None:
  # Given explicit BOM parents across tables, including a child listed before its parent.
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'bom_transfer', specification_id=spec['id'])
  header = ['상위 품목코드', '품목코드', '품목명', quantity_header, '단위', '조달·공급']
  with workspace['factory']() as session:
    session.get(WorkDocument, doc_id).blocks = [
      {
        'kind': 'table',
        'rows': [header, ['OPTIC', 'GLASS', '광학 유리', quantities[2], '매', '구매']],
        'location': {'block_index': 6},
      },
      {
        'kind': 'table',
        'rows': [
          header,
          ['CAM', 'LENS', '렌즈 모듈', quantities[0], '개', '조립'],
          ['LENS', 'OPTIC', '광학 모듈', quantities[1], '개', '조립'],
        ],
        'location': {'block_index': 8},
      },
    ]
    session.commit()
  calls = []

  class LLM:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
      calls.append(json.loads(prompt))
      assert [item['children'] for item in calls[-1]] == [['광학 모듈'], ['광학 유리']]
      return json.dumps({'0': 'assembly', '1': 'component'})

  monkeypatch.setattr('backend.services.work_documents.create_llm', lambda **kwargs: LLM())

  # When extracting, then each edge follows its source parent and quantities use the parent as their basis.
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})
  assert result['error'] is None
  assert result['candidates']['method'] == 'structured_bom'
  assert len(calls) == 1
  data = result['candidates']['data']
  assert [(edge['parent'], edge['child'], edge['quantity']) for edge in data['relations']] == [
    ('OPTIC@1', 'GLASS@1', 4),
    ('CAM@1', 'LENS@1', 2),
    ('LENS@1', 'OPTIC@1', 3),
  ]
  assert data['relations'][0]['source'] == {
    'document_id': doc_id,
    'page': None,
    'block_index': 6,
    'row': '2',
    'original_field': quantity_header,
    'original_value': quantities[2],
    'original_unit': '매',
  }
  assert all(not edge['confirmed'] for edge in data['relations'])
  assert next(item for item in data['items'] if item['code'] == 'GLASS')['unit'] == '매'

  # Given manual R&D confirmation, when creating and reloading a job, then the three-level chain remains intact.
  detail_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  for item in data['items']:
    item.update(
      confirmed=True,
      attributes=[
        {
          'field': 'length',
          'value': 8,
          'unit': 'mm',
          'confirmed': True,
          'source': source(detail_id),
        }
      ],
    )
  for edge in data['relations']:
    edge['confirmed'] = True
  saved = request(
    workspace, 'rd', f'/specifications/{spec["id"]}', {'revision': spec['revision'], 'graph': data}, method='put'
  )
  submitted = request(workspace, 'rd', f'/specifications/{spec["id"]}/submit', {'revision': saved['revision']})
  job = new_job(workspace, submitted, quantity=5)
  reloaded = (
    workspace['client']
    .get(
      f'/api/v1/workspace/jobs/{job["id"]}',
      headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["pm"].id)}'},
    )
    .json()
  )
  assert reloaded['targets'] == job['targets']
  targets = {target['code']: target for target in reloaded['targets'].values()}
  assert [targets[code]['quantity'] for code in ('CAM', 'LENS', 'OPTIC', 'GLASS')] == [5, 10, 30, 120]
  assert [targets[code]['parents'] for code in ('LENS', 'OPTIC', 'GLASS')] == [
    [targets[code]['id']] for code in ('CAM', 'LENS', 'OPTIC')
  ]


def test_hierarchical_bom_keeps_shared_parts_in_each_parent_scope() -> None:
  # Given one screw used by two modules, when reading explicit parents, then the item is shared but edges are distinct.
  rows = [
    {'parent_code': 'CAM', 'item_code': 'LENS', 'name': '렌즈 모듈', 'quantity_per_parent': '2', 'row': '2'},
    {'parent_code': 'CAM', 'item_code': 'BODY', 'name': '본체 모듈', 'quantity_per_parent': '1', 'row': '3'},
    {
      'parent_code': 'LENS',
      'item_code': 'SCREW',
      'name': '나사',
      'quantity_per_parent': '4',
      'procurement': '구매',
      'row': '4',
    },
    {
      'parent_code': 'BODY',
      'item_code': 'SCREW',
      'name': '나사',
      'quantity_per_parent': '6',
      'procurement': '구매',
      'row': '5',
    },
  ]
  result = bom_transfer_graph('bom', rows, graph()['items'][0])
  assert len(result['items']) == 4
  assert [(edge['parent'], edge['child'], edge['quantity']) for edge in result['relations']] == [
    ('CAM@1', 'LENS@1', 2),
    ('CAM@1', 'BODY@1', 1),
    ('LENS@1', 'SCREW@1', 4),
    ('BODY@1', 'SCREW@1', 6),
  ]
  for item in result['items']:
    item.setdefault('kind', 'component')
  targets = build_targets(result, 10)
  assert sum(target['quantity'] for target in targets.values() if target['code'] == 'SCREW') == 140


@pytest.mark.parametrize('parent', ['LENS', 'LENS@1', '렌즈 모듈'])
def test_hierarchical_bom_resolves_explicit_parent_identity(parent: str) -> None:
  rows = [
    {'parent_code': 'CAM', 'item_code': 'LENS', 'name': '렌즈 모듈', 'quantity_per_parent': '1', 'row': '2'},
    {'parent_code': parent, 'item_code': 'GLASS', 'name': '유리', 'quantity_per_parent': '14', 'row': '3'},
  ]
  assert bom_transfer_graph('bom', rows, graph()['items'][0])['relations'][1]['parent'] == 'LENS@1'


def test_bom_does_not_ignore_a_separate_parent_table_without_quantities() -> None:
  rows = [
    {'item_code': 'GLASS', 'name': '유리', 'quantity_per_product': '14', 'row': '2'},
    {'parent_code': 'LENS', 'item_code': 'GLASS', 'name': '유리', 'row': '2'},
  ]
  assert bom_transfer_graph('bom', rows, graph()['items'][0]) is None


@pytest.mark.parametrize('parent', ['', 'UNKNOWN', 'LENS'])
def test_hierarchical_bom_does_not_replace_invalid_parents_with_the_root(parent: str) -> None:
  rows = [{'parent_code': parent, 'item_code': 'LENS', 'name': '렌즈 모듈', 'quantity_per_parent': '1', 'row': '2'}]
  with pytest.raises(WorkflowError):
    bom_transfer_graph('bom', rows, graph()['items'][0])


@pytest.mark.parametrize('failure', ['missing_parent_total', 'repeated_parent_total', 'mixed_basis'])
def test_hierarchical_bom_rejects_ambiguous_quantity_bases(failure: str) -> None:
  # Given ambiguous source quantities, when resolving a hierarchy, then no quantity basis is guessed.
  rows = [
    {'parent_code': 'CAM', 'item_code': 'LENS', 'name': '렌즈 모듈', 'quantity_per_product': '2', 'row': '2'},
    {'parent_code': 'LENS', 'item_code': 'GLASS', 'name': '유리', 'quantity_per_product': '28', 'row': '3'},
  ]
  if failure == 'missing_parent_total':
    rows[0]['quantity_per_parent'] = rows[0].pop('quantity_per_product')
  elif failure == 'repeated_parent_total':
    rows.append({**rows[0], 'row': '4'})
  else:
    rows[1]['quantity_per_parent'] = '14'
  with pytest.raises(WorkflowError, match='수량'):
    bom_transfer_graph('bom', rows, graph()['items'][0])


@pytest.mark.parametrize('fail_second', [False, True])
def test_chunked_extraction_only_publishes_after_every_chunk_succeeds(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, fail_second: bool
) -> None:
  # given
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  with workspace['factory']() as session:
    doc = session.get(WorkDocument, doc_id)
    doc.blocks = [{'kind': 'text', 'text': '사양 원문 ' * 500, 'location': {'block_index': 1}}]
    session.commit()
  calls = []
  progress_updates = []

  class LLM:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
      calls.append(prompt)
      with workspace['factory']() as session:
        current = session.get(WorkDocument, doc_id)
        assert current.candidates['status'] == 'extracting'
        assert 'data' not in current.candidates
        progress_updates.append(deepcopy(current.candidates['progress']))
      if fail_second and len(calls) == 2:
        raise ValueError('Invalid model response')
      part = graph()
      part['items'][1]['attributes'] = [{'field': 'length', 'value': len(calls), 'unit': 'mm'}]
      return json.dumps(part)

  monkeypatch.setattr('backend.services.work_documents.create_llm', lambda **kwargs: LLM())

  # when
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})

  # then
  assert len(calls) > 1
  assert [update['completed_chunks'] for update in progress_updates] == list(range(len(calls)))
  assert all(update['stage'] == 'extracting' and update['total_chunks'] > 1 for update in progress_updates)
  progress = result['candidates']['progress']
  assert progress['stage'] == ('failed' if fail_second else 'completed')
  assert progress['completed_chunks'] == (len(calls) - 1 if fail_second else len(calls))
  assert all(len(prompt) <= 2000 for prompt in calls)
  assert result['candidates']['status'] == ('error' if fail_second else 'ready')
  if fail_second:
    assert 'data' not in result['candidates']
  else:
    assert len(result['candidates']['data']['items'][1]['attributes']) == len(calls)
  with workspace['factory']() as session:
    assert session.get(Specification, spec['id']).graph == spec['graph']


@pytest.mark.parametrize('structured', [False, True])
def test_ollama_extraction_constrains_output_without_changing_normal_chat(
  monkeypatch: pytest.MonkeyPatch, api_settings: Settings, structured: bool
) -> None:
  # given
  parameters = {}
  monkeypatch.setattr(factory, 'get_settings', lambda: api_settings.model_copy(update={'llm_provider': 'ollama'}))
  monkeypatch.setattr(factory, 'ChatOllama', lambda **kwargs: parameters.update(kwargs))
  schema = Graph.model_json_schema()

  # when
  if structured:
    factory.create_llm(output_schema=schema)
  else:
    factory.create_llm()

  # then
  assert parameters.get('num_ctx') == (16_384 if structured else None)
  if structured:
    output = parameters['format']
    assert output['properties']['items']['items'] == {'$ref': '#/$defs/Item'}
    assert output['$defs']['Item']['properties']['kind'] == schema['$defs']['Item']['properties']['kind']
    assert 'maxItems' not in output['properties']['items']
    assert 'maxLength' not in output['$defs']['Evidence']['properties']['original_value']
    assert output['$defs']['Item']['properties']['unit']['minLength'] == 1
    assert schema['properties']['items']['maxItems'] == 500
  else:
    assert parameters.get('format') is None


@pytest.mark.parametrize('structured', [False, True])
def test_anthropic_omits_temperature(monkeypatch: pytest.MonkeyPatch, api_settings: Settings, structured: bool) -> None:
  # given
  parameters = {}
  settings = api_settings.model_copy(update={'llm_provider': 'anthropic', 'anthropic_api_key': SecretStr('test-key')})
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  monkeypatch.setattr(factory, 'ChatAnthropic', lambda **kwargs: parameters.update(kwargs))

  # when
  factory.create_llm(output_schema=Graph.model_json_schema() if structured else None)

  # then
  assert 'temperature' not in parameters


@pytest.mark.parametrize('graph_candidate', [False, True])
def test_failed_graph_generation_keeps_successfully_extracted_source_rows(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, graph_candidate: bool
) -> None:
  # given
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  with workspace['factory']() as session:
    session.get(WorkDocument, doc_id).blocks = [
      {
        'kind': 'table',
        'rows': [['품목명', '값'], ['렌즈', '광학 유리']],
        'location': {'block_index': 4},
      }
    ]
    session.commit()

  def unavailable(**kwargs: object) -> None:
    raise ConnectionError('Ollama unavailable')

  monkeypatch.setattr('backend.services.work_documents.create_llm', unavailable)

  # when
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': graph_candidate})

  # then
  assert bool(result['error']) == graph_candidate
  assert result['candidates']['progress']['stage'] == ('failed' if graph_candidate else 'completed')
  assert result['candidates']['status'] == 'ready'
  assert 'items' not in result['candidates']['data']
  row = result['candidates']['data']['rows'][0]
  assert (row['name'], row['value'], row['block_index'], row['row']) == ('렌즈', '광학 유리', 4, '2')


@pytest.mark.parametrize('valid', [True, False])
def test_llm_candidates_use_graph_schema_and_stay_unconfirmed(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
  # given
  spec = request(
    workspace,
    'rd',
    '/specifications',
    {'code': 'CAM', 'name': '카메라', 'product_type': 'digital', 'graph': graph()},
    201,
  )
  doc_id = document(workspace, 'rd', 'product_detail', specification_id=spec['id'])
  candidate = graph()
  for item in candidate['items']:
    item['confirmed'] = True
    item['attributes'] = [{'field': 'length', 'value': 8, 'unit': 'mm', 'confirmed': True}]
  for relation in candidate['relations']:
    relation['confirmed'] = True

  class LLM:
    async def generate(self, prompt: str, *, system: str | None = None) -> str:
      return json.dumps(candidate if valid else {'rows': []})

  def create_llm(*, output_schema: dict) -> LLM:
    assert output_schema['properties']['root']['enum'] == [spec['graph']['root']]
    assert output_schema['$defs'] == Graph.model_json_schema()['$defs']
    return LLM()

  monkeypatch.setattr('backend.services.work_documents.create_llm', create_llm)

  # when
  result = extract(workspace, 'rd', doc_id, {'graph_candidate': True})

  # then
  assert result['status'] == 'parsed'
  assert result['blocks']
  assert result['candidates']['status'] == ('ready' if valid else 'error')
  if valid:
    data = result['candidates']['data']
    assert len(data['items']) == len(candidate['items'])
    assert all(not item['confirmed'] for item in data['items'])
    assert all(not attribute['confirmed'] for item in data['items'] for attribute in item['attributes'])
    assert all(not relation['confirmed'] for relation in data['relations'])
  else:
    assert 'data' not in result['candidates']
