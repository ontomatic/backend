import json
from copy import deepcopy
from decimal import Decimal
from math import isfinite

from backend.exceptions.workflow import WorkflowError
from backend.schemas.workflow import Graph
from backend.services.document_formats import HEADER_FIELDS
from backend.services.workflow import FIELD_ALIASES, normalize_value, validate_graph


def extraction_chunks(blocks: list[dict]) -> list[list[dict]]:
  units = []
  for block in blocks:
    if block['kind'] == 'table' and len(block.get('rows', [])) > 1:
      table = {**block, 'row_numbers': list(range(1, len(block['rows']) + 1))}
      if len(json.dumps([table], ensure_ascii=False)) <= 2000:
        units.append(table)
        continue
      header = block['rows'][0]
      units.extend(
        {**block, 'rows': [header, row], 'row_numbers': [1, index]}
        for index, row in enumerate(block['rows'][1:], start=2)
      )
    elif block['kind'] == 'text':
      text = block.get('text') or ''
      units.extend({**block, 'text': text[offset : offset + 1000]} for offset in range(0, len(text), 1000))
    else:
      units.append(block)
  chunks: list[list[dict]] = []
  current: list[dict] = []
  for unit in units:
    if len(json.dumps([unit], ensure_ascii=False)) > 2000:
      raise WorkflowError('표의 한 행이 추출 입력 한도를 초과합니다. 긴 셀을 나눠 다시 업로드해 주세요.')
    if current and len(json.dumps([*current, unit], ensure_ascii=False)) > 2000:
      chunks.append(current)
      current = []
    current.append(unit)
  if current:
    chunks.append(current)
  return chunks


def merge_graph_candidates(parts: list[dict], root: dict) -> dict:
  items = {root['key']: deepcopy(root)}
  relations: list[dict] = []
  for part in parts:
    if part['root'] != root['key']:
      raise WorkflowError('분할 추출 결과의 완제품 식별자가 서로 다릅니다.')
    for item in part['items']:
      known = items.get(item['key'])
      if known is None:
        items[item['key']] = deepcopy(item)
        continue
      if item['key'] != root['key'] and (
        any(known[field] != item[field] for field in ('kind', 'version', 'unit'))
        or (known['code'] and item['code'] and known['code'] != item['code'])
      ):
        raise WorkflowError('분할 추출 결과의 같은 품목 정보가 충돌합니다. 원문을 확인해 주세요.')
      known['code'] = known['code'] or item['code']
      for attribute in item['attributes']:
        if attribute not in known['attributes']:
          known['attributes'].append(deepcopy(attribute))
      aliases = [*known['aliases'], *item['aliases']]
      if item['name'] != known['name']:
        aliases.append(item['name'])
      known['aliases'] = list(dict.fromkeys(aliases))
    for relation in part['relations']:
      if relation not in relations:
        relations.append(deepcopy(relation))
  return Graph.model_validate({'root': root['key'], 'items': list(items.values()), 'relations': relations}).model_dump(
    mode='json'
  )


def product_specification_items(document_id: str, rows: list[dict], root: dict) -> list[dict] | None:
  # shortcut: flat unversioned specification tables use this path; other layouts keep the full extractor.
  headers = {'항목', '값', '부품', '품목명', '구성 상세', '속성', '속성값', 'unit'}
  if not rows or any(
    not row.get('field')
    or not row.get('value')
    or row.get('version')
    or '버전' in row['field']
    or row['field'].casefold() == 'version'
    or set(row.get('original', {})) - headers
    for row in rows
  ):
    return None
  items = {root['key']: deepcopy(root)}
  for row in rows:
    key = f'{row["name"]}@1' if row.get('name') else root['key']
    item = items.setdefault(key, {'key': key, 'name': row.get('name'), 'attributes': []})
    field = f'{row["description"]} · {row["field"]}' if row.get('description') else row['field']
    item['attributes'].append(
      {
        'field': field,
        'value': row['value'],
        'unit': row.get('unit') or '',
        'source': {
          'document_id': document_id,
          'page': row.get('page'),
          'block_index': row.get('block_index'),
          'row': row['row'],
          'original_field': row['field'],
          'original_value': row['value'],
          'original_unit': row.get('unit') or '',
        },
      }
    )
  return list(items.values())


def bom_transfer_graph(document_id: str, rows: list[dict], root: dict) -> dict | None:
  # shortcut: unversioned flat or explicit-parent BOM tables use this path; other layouts keep the full extractor.
  rows = [
    row for row in rows if any(field in row for field in ('quantity_per_product', 'quantity_per_parent', 'parent_code'))
  ]
  fields = {
    'sequence',
    'item_code',
    'name',
    'quantity_per_product',
    'quantity_per_parent',
    'procurement',
    'parent_code',
    'unit',
  }
  if not rows or any(
    not str(row.get('item_code') or '').strip()
    or not str(row.get('name') or '').strip()
    or not ('quantity_per_product' in row or 'quantity_per_parent' in row)
    or any(HEADER_FIELDS.get(header, header) not in fields for header in row.get('original', {}))
    for row in rows
  ):
    return None
  items = {root['key']: deepcopy(root)}
  relations = []
  hierarchical = any('parent_code' in row for row in rows)
  product_quantities = {root['key']: [1.0]}
  base_names = [str(row['name']).strip().partition(' (')[0] for row in rows]
  for row in rows:
    code, name = str(row['item_code']).strip(), str(row['name']).strip()
    key = f'{code}@1'
    if key in items and (not hierarchical or key == root['key']):
      raise WorkflowError('BOM에 중복된 품목코드가 있습니다. 원문과 사용 조건을 확인해 주세요.')
    if 'quantity_per_parent' in row and 'quantity_per_product' in row:
      raise WorkflowError('BOM의 상위 1개당 소요 수량과 완제품 대당 수량 중 기준을 하나만 지정해 주세요.')
    quantity_field = 'quantity_per_parent' if 'quantity_per_parent' in row else 'quantity_per_product'
    try:
      quantity = float(row[quantity_field])
    except (TypeError, ValueError) as exc:
      raise WorkflowError('BOM의 구성 수량에는 숫자를 입력해 주세요.') from exc
    if not isfinite(quantity) or not 0 < quantity <= 1_000_000_000:
      raise WorkflowError('BOM의 구성 수량은 0보다 크고 허용 범위 이내여야 합니다.')
    if quantity_field == 'quantity_per_product':
      product_quantities.setdefault(key, []).append(quantity)
    base_name = name.partition(' (')[0] if name.endswith(')') else name
    item = {
      'key': key,
      'code': code,
      'name': name,
      'version': 1,
      'unit': str(row.get('unit') or '개').strip(),
      'aliases': [base_name] if base_name != name and base_names.count(base_name) == 1 else [],
      'attributes': [],
    }
    procurement = str(row.get('procurement') or '').strip()
    if procurement.startswith('구매'):
      item['kind'] = 'material'
    elif procurement.startswith('자체 가공'):
      item['kind'] = 'component'
    if key in items and items[key] != item:
      raise WorkflowError(f'BOM의 같은 품목 정보가 서로 다릅니다: {code}')
    items[key] = item
    parent = root['key']
    if hierarchical:
      parent_code = str(row.get('parent_code') or '').strip()
      if not parent_code:
        raise WorkflowError(f'BOM의 상위 품목코드를 확인해 주세요: {code}')
      parent = parent_code
    relations.append(
      {
        'parent': parent,
        'child': key,
        'quantity': quantity,
        'condition': row.get('procurement') or 'common',
        'source': {
          'document_id': document_id,
          'page': row.get('page'),
          'block_index': row.get('block_index'),
          'row': row['row'],
          'original_field': '소요 수량' if quantity_field == 'quantity_per_parent' else '대당 수량',
          'original_value': str(row[quantity_field]),
          'original_unit': str(row.get('unit') or ''),
        },
      }
    )
  for row, relation in zip(rows, relations, strict=True):
    parents = [key for key, item in items.items() if relation['parent'] in (key, item['code'], item['name'])]
    if len(parents) != 1:
      raise WorkflowError(f'BOM의 상위 품목을 유일하게 확인할 수 없습니다: {relation["parent"]}')
    parent = relation['parent'] = parents[0]
    if hierarchical and 'quantity_per_product' in row:
      amounts = product_quantities.get(parent, [])
      if len(amounts) != 1:
        raise WorkflowError('BOM의 상위 대당 수량이 불명확합니다. 상위 1개당 소요 수량으로 지정해 주세요.')
      relation['quantity'] = float(Decimal(str(relation['quantity'])) / Decimal(str(amounts[0])))
  result = {'root': root['key'], 'items': list(items.values()), 'relations': relations}
  validate_graph({**result, 'items': [{'kind': 'component', **item} for item in result['items']]})
  return result


def table_rows(blocks: list[dict]) -> list[dict]:
  result = []
  for block in blocks:
    if block['kind'] != 'table' or not block.get('rows'):
      continue
    headers = [str(cell or '').strip() for cell in block['rows'][0]]
    for index, values in enumerate(block['rows'][1:], start=2):
      row = dict(zip(headers, values, strict=False))
      location = block.get('location') or {}
      row['page'] = location.get('page_number') if location.get('block_index') else location.get('page_number') or 1
      row['block_index'] = location.get('block_index')
      row['row'] = str(index)
      result.append(row)
  return result


def extract_tabular_graph(document_id: str, blocks: list[dict]) -> dict | None:
  rows = table_rows(blocks)
  if not rows or not any('record_type' in row for row in rows):
    return None
  items: dict = {}
  relations = []
  root = None
  for row in rows:
    if row.get('record_type') != 'item':
      continue
    code, version = row.get('item_code') or '', int(row.get('version') or 1)
    key = f'{code or "unresolved-row-" + row["row"]}@{version}'
    if key in items:
      raise WorkflowError('상세서에 중복된 품목코드·버전이 있습니다. R&D가 원문을 확인해 주세요.')
    item = {
      'key': key,
      'code': code,
      'name': row.get('name') or '명칭 미확인',
      'kind': row.get('kind'),
      'version': version,
      'unit': row.get('unit') or '개',
      'aliases': [],
      'attributes': [],
      'confirmed': False,
    }
    items[key] = item
    if item['kind'] == 'product':
      if root is not None:
        raise WorkflowError('상세서의 완제품 루트를 R&D가 선택해 주세요.')
      root = key
  for row in rows:
    source = {
      'document_id': document_id,
      'page': row['page'],
      'block_index': row.get('block_index'),
      'row': row['row'],
      'original_field': row.get('field') or row.get('record_type') or '',
      'original_value': row.get('value') or row.get('quantity') or '',
      'original_unit': row.get('unit') or '',
    }
    if row.get('record_type') == 'attribute':
      key = f'{row.get("item_code")}@{row.get("version") or 1}'
      if key not in items:
        raise WorkflowError('사양이 참조하는 품목코드·버전이 없습니다.')
      value, unit = normalize_value(row.get('value') or '', row.get('unit') or '')
      items[key]['attributes'].append(
        {
          'field': FIELD_ALIASES.get(row.get('field'), row.get('field')),
          'value': value,
          'unit': unit,
          'source': source,
          'required': True,
          'confirmed': False,
        }
      )
    elif row.get('record_type') == 'relation':
      relations.append(
        {
          'parent': row['parent'],
          'child': row['child'],
          'quantity': float(row['quantity']),
          'condition': row.get('condition') or '',
          'source': source,
          'confirmed': False,
        }
      )
  return Graph.model_validate({'root': root, 'items': list(items.values()), 'relations': relations}).model_dump(
    mode='json'
  )
