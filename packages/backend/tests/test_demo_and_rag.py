import asyncio
import io
from dataclasses import asdict
from pathlib import Path

import pytest
from backend.demo import PRODUCTS, generate_demo
from backend.parsers.documents.csv import parse_csv
from backend.services import rag
from backend.services.extraction import extract_tabular_graph
from backend.services.workflow import build_targets


@pytest.mark.parametrize('product_type', PRODUCTS)
def test_four_product_documents_match_independent_expected_counts_and_values(tmp_path: Path, product_type: str) -> None:
  # Given generated fictional source documents, when extracted before R&D edits, then the expected data matches.
  manifest = generate_demo(tmp_path)
  expected = next(product for product in manifest['products'] if product['product_type'] == product_type)
  document = parse_csv(io.BytesIO((tmp_path / product_type / 'product_detail.csv').read_bytes()))
  graph = extract_tabular_graph('source-document', [asdict(block) for block in document.blocks])
  assert len(graph['items']) == expected['item_count']
  assert len(graph['relations']) == expected['relation_count']
  assert sum(len(item['attributes']) for item in graph['items']) == expected['attribute_count']
  assert not any(item['confirmed'] for item in graph['items'])
  for item in graph['items']:
    length = next(attribute for attribute in item['attributes'] if attribute['field'] == 'length')
    assert (length['value'], length['unit']) == (8, 'mm')
    assert length['source']['original_value'] == '0.8'
    assert length['source']['original_unit'] == 'cm'
  targets = build_targets(graph, expected['quantity'])
  assert (
    sum(target['quantity'] for target in targets.values() if target['code'] == 'MAT-SCR-001')
    == expected['screw_quantity']
  )
  assert max(len(target['children']) for target in targets.values()) >= 2


def test_chunking_keeps_document_page_and_version_scope() -> None:
  from types import SimpleNamespace

  spec = SimpleNamespace(
    id='spec-v1',
    graph={
      'items': [
        {'key': 'A@1', 'code': 'A', 'name': '재료', 'attributes': []},
      ]
    },
  )
  document = SimpleNamespace(
    id='document',
    status='parsed',
    blocks=[
      {'kind': 'text', 'text': 'A 재료 ' + '긴 원문 ' * 500, 'location': {'page_number': 3}},
    ],
  )
  chunks = rag.document_chunks(spec, [document])
  assert len(chunks) > 1
  assert all(chunk['specification_id'] == 'spec-v1' and chunk['page'] == 3 for chunk in chunks)
  assert all(len(chunk['text']) <= 1400 for chunk in chunks)
  assert len({chunk['id'] for chunk in chunks}) == len(chunks)


def test_retrieval_filters_the_version_and_expands_graph_without_generated_cypher(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  calls = []
  questions = []

  class Embedder:
    def embed_query(self, text: str) -> list[float]:
      questions.append(text)
      return [1.0, 0.0]

  monkeypatch.setattr(rag, 'create_embedder', Embedder)
  monkeypatch.setattr(rag, 'vector_index', lambda: 'ontomatic_vectors_test')

  def query(statement: str, parameters: dict) -> list[dict]:
    calls.append((statement, parameters))
    if 'RETURN DISTINCT' in statement:
      return [{'item_key': 'A@1', 'name': '품목'}]
    return [
      {'id': 'chunk', 'document_id': 'doc', 'page': 1, 'row': '2', 'text': '근거', 'item_keys': ['A@1'], 'score': 0.95}
    ]

  monkeypatch.setattr(rag, 'cypher', query)
  sources, graph = rag.retrieve_context('selected-v2', '품목의 구성은?')
  assert sources[0]['document_id'] == 'doc'
  assert graph[0]['item_key'] == 'A@1'
  assert all(parameters['specification_id'] == 'selected-v2' for _, parameters in calls)
  assert all('$specification_id' in statement for statement, _ in calls)
  assert calls[-1][1]['keys'] == ['A@1']
  assert questions == ['품목의 구성은?']
  assert all('node.embedding_index = $index' in statement for statement, _ in calls[:-1])


def test_neo4j_client_uses_query_api_and_parameters(monkeypatch: pytest.MonkeyPatch, api_settings: object) -> None:
  from backend.core.config import get_settings
  from backend.integrations import graph

  settings = get_settings().model_copy(
    update={'graph_rag_enabled': True, 'neo4j_password': __import__('pydantic').SecretStr('test-only')}
  )
  monkeypatch.setattr(graph, 'get_settings', lambda: settings)
  requests = []

  def post(url: str, body: dict, *, authorization: str) -> dict:
    requests.append((url, body, authorization))
    return {'data': {'fields': ['answer'], 'values': [[42]]}, 'errors': []}

  monkeypatch.setattr(graph, 'post_json', post)
  assert graph.cypher('RETURN $value AS answer', {'value': 42}) == [{'answer': 42}]
  assert requests[0][0].endswith('/db/neo4j/query/v2')
  assert requests[0][1]['parameters'] == {'value': 42}
  assert requests[0][2].startswith('Basic ')
