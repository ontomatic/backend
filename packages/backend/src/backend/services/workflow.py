import json
import re
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from math import isfinite
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.utils import utc_now
from backend.exceptions.workflow import WorkflowConflict, WorkflowError, WorkflowPermission
from backend.models.file import File
from backend.models.user import User
from backend.models.workflow import ProductionJob, ProductionPlan, Specification, WorkDocument, WorkflowEvent
from backend.repositories.workflow import get_job, get_specification, list_documents, list_plans
from backend.schemas.workflow import (
  CompletionIn,
  DraftIn,
  InspectionIn,
  ItemImportIn,
  JobIn,
  PlanIn,
  ReworkIn,
  SchedulePlanIn,
  SpecificationIn,
)
from backend.services.document_formats import HEADER_FIELDS
from backend.services.production_flow import (
  ACCEPTED,
  configure_processes,
  count_source,
  rebuild_allocations,
  remaining_outputs,
  reserve_inputs,
  update_inventory,
)

RD = 'research_and_development'
QA = 'quality_assurance'
PM = 'production_management'
DOCUMENT_DEPARTMENTS = {
  'product_detail': RD,
  'bom_transfer': RD,
  'incoming_inspection': QA,
  'production_plan': PM,
  'work_instruction_module1': PM,
  'inspection_module1': QA,
  'work_instruction_lens': PM,
  'work_instruction_body': PM,
  'inspection_module2': QA,
  'work_instruction_final': PM,
  'inspection_final': QA,
}
PLAN_KINDS = {'production_plan'}
DOCUMENT_TARGET_KINDS = {
  'incoming_inspection': {'material'},
  'production_plan': {'component', 'assembly', 'product'},
  'work_instruction_module1': {'component'},
  'inspection_module1': {'component'},
  'work_instruction_lens': {'assembly'},
  'work_instruction_body': {'assembly'},
  'inspection_module2': {'assembly'},
  'work_instruction_final': {'product'},
  'inspection_final': {'product'},
}
INSPECTION_KINDS = {
  'material': 'incoming_inspection',
  'component': 'inspection_module1',
  'assembly': 'inspection_module2',
  'product': 'inspection_final',
}
UNIT_FACTORS = {
  'mm': ('mm', 1),
  'cm': ('mm', 10),
  'm': ('mm', 1000),
  'g': ('g', 1),
  'kg': ('g', 1000),
  'V': ('V', 1),
  'mV': ('V', 0.001),
  'W': ('W', 1),
  'mW': ('W', 0.001),
}
FIELD_ALIASES = {
  '길이': 'length',
  '전장': 'length',
  'length': 'length',
  '지름': 'diameter',
  '직경': 'diameter',
  'diameter': 'diameter',
  '무게': 'mass',
  '질량': 'mass',
  'mass': 'mass',
  '정격전압': 'voltage',
  '전압': 'voltage',
  'voltage': 'voltage',
  '소비전력': 'power',
  '전력': 'power',
  'power': 'power',
  '재질': 'material',
  '소재': 'material',
  'material': 'material',
}


def require_department(user: User, department: str) -> None:
  if not user.is_active or not user.department or not user.department.is_active or user.department.code != department:
    raise WorkflowPermission('이 작업은 해당 담당 부서만 수행할 수 있습니다.')


def normalize_value(value: str | float, unit: str) -> tuple[str | float, str]:
  if unit not in UNIT_FACTORS:
    return value, unit
  try:
    number = Decimal(str(value))
    if not number.is_finite():
      raise WorkflowError('사양 수치는 유한한 값이어야 합니다.')
    canonical, factor = UNIT_FACTORS[unit]
    return float(number * Decimal(str(factor))), canonical
  except (ValueError, ArithmeticError) as exc:
    raise WorkflowError('단위가 있는 사양에는 숫자를 입력해 주세요.') from exc


def validate_graph(graph: dict) -> list[str]:
  items = {item['key']: item for item in graph['items']}
  if len(items) != len(graph['items']):
    raise WorkflowError('중복된 품목 버전 식별자가 있습니다.')
  root = graph['root']
  if root not in items or items[root]['kind'] != 'product':
    raise WorkflowError('완제품을 BOM 루트로 선택해 주세요.')
  children: dict[str, list[str]] = {key: [] for key in items}
  seen: set[tuple] = set()
  for edge in graph['relations']:
    parent, child = edge['parent'], edge['child']
    if parent not in items or child not in items or parent == child:
      raise WorkflowError(f'없는 버전 참조 또는 자기 참조: {parent} → {child}')
    if not isfinite(edge['quantity']) or edge['quantity'] <= 0:
      raise WorkflowError(f'구성 수량은 0보다 커야 합니다: {parent} → {child}')
    identity = (parent, child, edge.get('condition', 'common'))
    if identity in seen:
      raise WorkflowError(f'중복 구성 관계: {parent} → {child}')
    seen.add(identity)
    children[parent].append(child)
  order: list[str] = []
  visited: set[str] = set()
  active: set[str] = set()

  def visit(key: str) -> None:
    if key in active:
      raise WorkflowError(f'순환 참조: {key}')
    if key in visited:
      return
    active.add(key)
    for child in children[key]:
      visit(child)
    active.remove(key)
    visited.add(key)
    order.append(key)

  visit(root)
  if visited != set(items):
    raise WorkflowError('루트에서 연결되지 않은 품목이 있습니다.')
  if any('|' in key for key in items) or any('|' in edge.get('condition', '') for edge in graph['relations']):
    raise WorkflowError('품목 식별자와 사용 조건에 | 문자를 사용할 수 없습니다.')
  for key, item in items.items():
    if item['kind'] == 'material' and children[key]:
      raise WorkflowError(f'재료에는 하위 구성을 지정할 수 없습니다: {key}')
    if item['kind'] in ('product', 'assembly') and not children[key]:
      raise WorkflowError(f'생산 대상의 하위 구성 근거가 필요합니다: {key}')
  return list(reversed(order))


def build_targets(graph: dict, quantity: float) -> dict:
  order = validate_graph(graph)
  items = {item['key']: item for item in graph['items']}
  targets: dict = {}

  def add(key: str, condition: str, amount: float, scope: str, *, root: bool = False) -> str:
    item = items[key]
    target_id = f'{item["code"]}@{item["version"]}|{condition}' + (
      '' if root else '|' + sha256(scope.encode()).hexdigest()[:16]
    )
    if target_id not in targets:
      if len(targets) >= 500:
        raise WorkflowError('한 생산 건에서 추적할 수 있는 구성별 사용 범위는 최대 500개입니다.')
      item = items[key]
      targets[target_id] = {
        'id': target_id,
        'item_key': key,
        'code': item['code'],
        'name': item['name'],
        'kind': item['kind'],
        'version': item['version'],
        'condition': condition,
        'scope': scope,
        'quantity': 0,
        'unit': item['unit'],
        'children': [],
        'status': 'waiting',
        'round': 1,
        'completion_id': None,
        'inspection_id': None,
        'plan_version': 0,
        'issue': None,
      }
    total = Decimal(str(targets[target_id]['quantity'])) + Decimal(str(amount))
    if total > Decimal('1000000000'):
      raise WorkflowError('총 소요 수량이 허용 범위를 초과합니다.')
    targets[target_id]['quantity'] = float(total)
    return target_id

  root_scope = json.dumps([[items[graph['root']]['code'], 'root']], ensure_ascii=False, separators=(',', ':'))
  add(graph['root'], 'root', quantity, root_scope, root=True)
  for key in order:
    for target in [t for t in targets.values() if t['item_key'] == key]:
      for edge in graph['relations']:
        if edge['parent'] != key:
          continue
        amount = float(Decimal(str(target['quantity'])) * Decimal(str(edge['quantity'])))
        condition = edge.get('condition', 'common')
        scope = json.dumps(
          json.loads(target['scope']) + [[items[edge['child']]['code'], condition]],
          ensure_ascii=False,
          separators=(',', ':'),
        )
        child_id = add(edge['child'], condition, amount, scope)
        if child_id not in target['children']:
          target['children'].append(child_id)
  return targets


def record_event(
  session: Session,
  user: User,
  action: str,
  data: dict,
  *,
  specification_id: str | None = None,
  job_id: str | None = None,
  target_id: str | None = None,
) -> WorkflowEvent:
  event = WorkflowEvent(
    specification_id=specification_id,
    job_id=job_id,
    target_id=target_id,
    action=action,
    actor_id=user.id,
    actor_name=user.name,
    department=user.department.code if user.department else user.role,
    data=data,
  )
  session.add(event)
  session.flush()
  return event


def check_revision(actual: int, expected: int) -> None:
  if actual != expected:
    raise WorkflowConflict('다른 담당자가 변경했습니다. 최신 상태를 불러온 뒤 다시 확인해 주세요.')


def copy_definition_documents(
  session: Session,
  user: User,
  source: Specification,
  destination: Specification,
  graph: dict,
) -> dict:
  source_ids = {}
  existing = {
    doc.scope.get('origin_document_id'): doc
    for doc in list_documents(session, specification_id=destination.id)
    if doc.scope.get('origin_document_id')
  }
  for original in list_documents(session, specification_id=source.id):
    origin = original.scope.get('origin_document_id', original.id)
    copied = existing.get(origin)
    if not copied:
      copied = WorkDocument(
        file_id=original.file_id,
        kind=original.kind,
        department=original.department,
        specification_id=destination.id,
        scope=original.scope
        | {
          'specification_id': destination.id,
          'origin_document_id': origin,
          'root_code': original.scope.get('root_code', source.code),
        },
        blocks=deepcopy(original.blocks),
        candidates=deepcopy(original.candidates),
        status=original.status,
        error=original.error,
        created_by=user.id,
      )
      session.add(copied)
      session.flush()
    source_ids[original.id] = copied.id
  graph = deepcopy(graph)
  for item in graph['items']:
    for attribute in item['attributes']:
      if attribute['source'] and attribute['source']['document_id'] in source_ids:
        attribute['source']['document_id'] = source_ids[attribute['source']['document_id']]
  for relation in graph['relations']:
    if relation['source'] and relation['source']['document_id'] in source_ids:
      relation['source']['document_id'] = source_ids[relation['source']['document_id']]
  return graph


def create_specification(session: Session, user: User, body: SpecificationIn) -> Specification:
  require_department(user, RD)
  previous = get_specification(session, body.previous_id, lock=True) if body.previous_id else None
  if previous and (previous.status != 'submitted' or previous.code != body.code or not body.reason.strip()):
    raise WorkflowError('확정된 같은 제품에서 변경 사유를 남겨 새 버전을 만들어 주세요.')
  existing = session.scalar(select(func.max(Specification.version)).where(Specification.code == body.code))
  if existing and not previous:
    raise WorkflowConflict('이미 등록된 제품 코드입니다. 기존 버전에서 새 작업본을 만들어 주세요.')
  graph = body.graph.model_dump(mode='json')
  spec = Specification(
    code=body.code,
    name=body.name,
    product_type=body.product_type,
    version=(existing or 0) + 1,
    previous_id=body.previous_id,
    graph=graph,
    reason=body.reason,
    created_by=user.id,
  )
  session.add(spec)
  try:
    session.flush()
  except IntegrityError as exc:
    constraint = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
    if constraint == 'uq_specification_version' or str(exc.orig) == (
      'UNIQUE constraint failed: specifications.code, specifications.version'
    ):
      raise WorkflowConflict('다른 담당자가 같은 제품 버전을 생성했습니다. 목록을 새로 불러와 주세요.') from exc
    raise
  if previous:
    graph = copy_definition_documents(session, user, previous, spec, graph)
    spec.graph = graph
  record_event(session, user, 'draft_created', {'graph': graph, 'reason': body.reason}, specification_id=spec.id)
  return spec


def save_draft(session: Session, user: User, specification_id: str, body: DraftIn) -> Specification:
  require_department(user, RD)
  spec = get_specification(session, specification_id, lock=True)
  check_revision(spec.revision, body.revision)
  if spec.status != 'draft':
    raise WorkflowConflict('제출된 사양은 수정할 수 없습니다. 새 버전을 만들어 주세요.')
  graph = body.graph.model_dump(mode='json')
  for item in graph['items']:
    for attr in item['attributes']:
      if attr['confirmed']:
        attr['value'], attr['unit'] = normalize_value(attr['value'], attr['unit'])
        attr['field'] = FIELD_ALIASES.get(attr['field'], attr['field'])
  spec.graph = graph
  spec.revision += 1
  record_event(session, user, 'draft_saved', {'graph': graph, 'revision': spec.revision}, specification_id=spec.id)
  return spec


def get_item_catalog(session: Session) -> list[dict]:
  catalog = {}
  for spec in session.scalars(
    select(Specification).where(Specification.status == 'submitted').order_by(Specification.created_at)
  ):
    for item in spec.graph['items']:
      if item['kind'] != 'product':
        catalog.setdefault((item['code'], item['version']), {'specification_id': spec.id, 'item': item})
  return sorted(catalog.values(), key=lambda entry: (entry['item']['code'], entry['item']['version']))


def import_item_definition(session: Session, user: User, specification_id: str, body: ItemImportIn) -> Specification:
  require_department(user, RD)
  draft = get_specification(session, specification_id, lock=True)
  check_revision(draft.revision, body.revision)
  if draft.status != 'draft':
    raise WorkflowConflict('제품 작업본에만 공통 사양을 연결할 수 있습니다.')
  source = get_specification(session, body.source_specification_id)
  items = {item['key']: item for item in source.graph['items']}
  if source.status != 'submitted' or body.item_key not in items or items[body.item_key]['kind'] == 'product':
    raise WorkflowError('확인된 공통 부품·재료 사양을 선택해 주세요.')
  selected = {body.item_key}
  while True:
    children = {edge['child'] for edge in source.graph['relations'] if edge['parent'] in selected}
    if children <= selected:
      break
    selected |= children
  imported = {
    'root': source.graph['root'],
    'items': [items[key] for key in items if key in selected],
    'relations': [edge for edge in source.graph['relations'] if edge['parent'] in selected],
  }
  graph = deepcopy(draft.graph)
  existing = {(item['code'], item['version']): item for item in graph['items']}
  replacements = {}
  for item in imported['items']:
    current = existing.get((item['code'], item['version']))
    if current:
      if semantic_item(current, graph) != semantic_item(item, source.graph):
        raise WorkflowConflict('기존 품목 버전의 사양이 다릅니다. 수정 중인 값을 먼저 확인해 주세요.')
      replacements[item['key']] = current['key']
  imported['items'] = [item for item in imported['items'] if item['key'] not in replacements]
  if not imported['items']:
    raise WorkflowConflict('이미 연결된 품목 버전입니다. 기존 품목을 선택해 주세요.')
  if {item['key'] for item in graph['items']} & {item['key'] for item in imported['items']}:
    raise WorkflowConflict('작업본의 식별자와 충돌합니다. 기존 품목 식별자를 먼저 정리해 주세요.')
  imported['relations'] = [
    edge | {'child': replacements.get(edge['child'], edge['child'])}
    for edge in imported['relations']
    if edge['parent'] not in replacements
  ]
  imported = copy_definition_documents(session, user, source, draft, imported)
  graph['items'].extend(imported['items'])
  graph['relations'].extend(imported['relations'])
  draft.graph = graph
  draft.revision += 1
  record_event(
    session,
    user,
    'item_imported',
    {
      'source_specification_id': source.id,
      'item_key': body.item_key,
      'graph': graph,
      'revision': draft.revision,
    },
    specification_id=draft.id,
  )
  return draft


def source_row(document: WorkDocument, source: dict) -> dict:
  if not source['row'].isdigit():
    return {}
  index = int(source['row']) - 1
  tables = [
    block
    for block in document.blocks
    if block['kind'] == 'table'
    and (
      (block.get('location', {}).get('block_index') == source.get('block_index'))
      if source.get('block_index')
      else (block.get('location', {}).get('page_number') or 1) == source['page']
    )
  ]
  if len(tables) != 1 or index < 1 or index >= len(tables[0]['rows']):
    return {}
  rows = tables[0]['rows']
  return dict(zip(rows[0], rows[index], strict=False))


def validate_sources(
  session: Session,
  sources: list[dict],
  documents: list[WorkDocument],
  expected: dict | None = None,
) -> set[str]:
  allowed = {doc.id: doc for doc in documents if doc.status == 'parsed'}
  extensions = {
    doc.id: Path(session.get(File, doc.file_id).original_filename).suffix.lower() for doc in allowed.values()
  }
  kinds = set()
  for source in sources:
    doc = allowed.get(source['document_id'])
    if not doc:
      raise WorkflowError('다른 대상/버전/회차의 문서 또는 추출하지 못한 문서가 근거에 포함되어 있습니다.')
    pages = {block.get('location', {}).get('page_number') or 1 for block in doc.blocks}
    is_docx = any(block.get('location', {}).get('block_index') for block in doc.blocks)
    block_indices = {block.get('location', {}).get('block_index') for block in doc.blocks}
    located = source.get('block_index') in block_indices if is_docx else source['page'] in pages
    if not located or not source['row'].strip():
      raise WorkflowError('근거의 페이지 또는 DOCX 문단/표 블록과 행을 확인해 주세요.')
    selected_tables = [
      block
      for block in doc.blocks
      if block['kind'] == 'table'
      and (
        block.get('location', {}).get('block_index') == source.get('block_index')
        if is_docx
        else (block.get('location', {}).get('page_number') or 1) == source['page']
      )
    ]
    if (extensions[doc.id] == '.csv' or (is_docx and selected_tables)) and not source['row'].isdigit():
      raise WorkflowError('CSV 또는 DOCX 표의 실제 행 번호를 입력해 주세요.')
    if (
      len(selected_tables) == 1
      and source['row'].isdigit()
      and not 2 <= int(source['row']) <= len(selected_tables[0]['rows'])
    ):
      raise WorkflowError('근거 행이 원문 표에 없습니다. 헤더가 아닌 실제 값의 행을 선택해 주세요.')
    row = source_row(doc, source)
    identity_columns = {'target_id', 'item_code', 'version'}
    if not identity_columns.intersection(row):
      row = {}
    for field, value in (expected or {}).items():
      raw = row.get(field)
      if raw is None or raw == '':
        continue
      if field in ('quantity', 'version', 'duration', 'measured_value'):
        try:
          matches = Decimal(str(raw)) == Decimal(str(value))
        except ArithmeticError:
          matches = str(raw).strip() == str(value).strip()
      elif field in ('start', 'end'):
        try:
          matches = datetime.fromisoformat(raw) == datetime.fromisoformat(value)
        except ValueError:
          matches = False
      else:
        matches = str(raw).strip() == str(value).strip()
      if not matches:
        raise WorkflowError(f'{field}: 문서 간 값 또는 확인값이 원문 행과 다릅니다.')
    kinds.add(doc.kind)
  return kinds


def submit_specification(session: Session, user: User, specification_id: str, revision: int) -> Specification:
  require_department(user, RD)
  spec = get_specification(session, specification_id, lock=True)
  check_revision(spec.revision, revision)
  if spec.status != 'draft':
    raise WorkflowConflict('이미 제출된 사양입니다.')
  graph = spec.graph
  validate_graph(graph)
  if next(item for item in graph['items'] if item['key'] == graph['root'])['code'] != spec.code:
    raise WorkflowError('완제품 루트의 품목코드가 등록한 제품 코드와 다릅니다.')
  docs = list_documents(session, specification_id=spec.id)
  if not any(
    doc.kind == 'product_detail' and doc.status == 'parsed' and doc.scope.get('root_code', spec.code) == spec.code
    for doc in docs
  ):
    raise WorkflowError('제품사양서를 연결하고 추출 결과를 확인해 주세요.')
  if not any(doc.kind == 'bom_transfer' and doc.status == 'parsed' for doc in docs):
    raise WorkflowError('BOM 및 양산 이관을 연결하고 확인한 뒤 제출해 주세요.')
  sources = []
  identities: set[tuple] = set()
  for item in graph['items']:
    if not item['code'] or not item['confirmed'] or not item['attributes']:
      raise WorkflowError(f'{item["name"]}: 품목 식별·필수 사양·버전 확인이 필요합니다.')
    identity = (item['code'], item['version'])
    if identity in identities:
      raise WorkflowError('같은 코드·버전은 하나의 공통 품목으로 연결해 주세요.')
    identities.add(identity)
    if len({attribute['field'] for attribute in item['attributes']}) != len(item['attributes']):
      raise WorkflowError(f'{item["name"]}: 중복되거나 충돌하는 사양 항목을 정리해 주세요.')
    for attr in item['attributes']:
      if not attr['confirmed'] or not attr['source'] or str(attr['value']).strip() == '':
        raise WorkflowError(f'{item["name"]} / {attr["field"]}: 값·단위·원문 근거를 확인해 주세요.')
      sources.append(attr['source'])
      doc = next((document for document in docs if document.id == attr['source']['document_id']), None)
      row = source_row(doc, attr['source']) if doc else {}
      if 'field' in row and 'value' in row and 'unit' in row:
        value, unit = normalize_value(row['value'], row['unit'])
        if FIELD_ALIASES.get(row['field'], row['field']) != attr['field'] or (str(value), unit) != (
          str(attr['value']),
          attr['unit'],
        ):
          try:
            equivalent = Decimal(str(value)) == Decimal(str(attr['value'])) and unit == attr['unit']
          except ArithmeticError:
            equivalent = False
          if not equivalent or FIELD_ALIASES.get(row['field'], row['field']) != attr['field']:
            raise WorkflowError(f'{item["name"]} / {attr["field"]}: 표준값이 원문 행과 다릅니다.')
  for edge in graph['relations']:
    if not edge['confirmed'] or not edge['source']:
      raise WorkflowError(f'{edge["parent"]} → {edge["child"]}: 수량·사용 조건·근거를 확인해 주세요.')
    sources.append(edge['source'])
  validate_sources(session, sources, docs)
  definitions = {
    (item['code'], item['version']): semantic_item(item, confirmed.graph)
    for confirmed in session.scalars(select(Specification).where(Specification.status == 'submitted'))
    for item in confirmed.graph['items']
  }
  for item in graph['items']:
    identity = (item['code'], item['version'])
    if identity in definitions and definitions[identity] != semantic_item(item, graph):
      raise WorkflowError(
        f'{item["code"]} v{item["version"]}: 확정된 사양/구성이 달라졌습니다. 새 품목 버전을 사용해 주세요.'
      )
  spec.status = 'submitted'
  spec.submitted_at = utc_now()
  spec.revision += 1
  record_event(
    session,
    user,
    'specification_submitted',
    {'graph': graph, 'version': spec.version, 'revision': spec.revision},
    specification_id=spec.id,
  )
  return spec


def create_job(session: Session, user: User, body: JobIn) -> ProductionJob:
  require_department(user, PM)
  spec = get_specification(session, body.specification_id)
  if spec.status != 'submitted':
    raise WorkflowError('R&D가 확인·제출한 사양/BOM 버전만 생산할 수 있습니다.')
  job = ProductionJob(
    name=body.name,
    specification_id=spec.id,
    quantity=body.quantity,
    targets=build_targets(spec.graph, body.quantity),
    created_by=user.id,
  )
  session.add(job)
  session.flush()
  record_event(session, user, 'job_created', {'specification_id': spec.id, 'quantity': body.quantity}, job_id=job.id)
  return job


def affected_targets(targets: dict, changed: set[str]) -> set[str]:
  affected = set(changed)
  while True:
    parents = {key for key, target in targets.items() if set(target['children']) & affected}
    if parents <= affected:
      return affected
    affected |= parents


def semantic_item(item: dict, graph: dict) -> dict:
  items = {node['key']: node for node in graph['items']}
  return {
    'code': item['code'],
    'version': item['version'],
    'kind': item['kind'],
    'unit': item['unit'],
    'attributes': sorted(
      ({key: attribute[key] for key in ('field', 'value', 'unit', 'required')} for attribute in item['attributes']),
      key=lambda attribute: attribute['field'],
    ),
    'children': sorted(
      [
        (items[edge['child']]['code'], items[edge['child']]['version'], edge['quantity'], edge['condition'])
        for edge in graph['relations']
        if edge['parent'] == item['key']
      ],
    ),
  }


def invalidate(targets: dict, changed: set[str], reason: str) -> set[str]:
  affected = affected_targets(targets, changed)
  for key in affected:
    target = targets[key]
    target.update(status='waiting', round=target['round'] + 1, completion_id=None, inspection_id=None, issue=None)
    target['recheck_reason'] = reason
    if target.get('process_code') or target.get('inventory_of'):
      for field in ('input_quantity', 'good_quantity', 'defect_quantity'):
        target.pop(field, None)
      target['allocations'] = {}
  return affected


def finish_job_change(session: Session, job: ProductionJob, targets: dict) -> None:
  previous = job.revision
  rebuild_allocations(targets)
  update_inventory(targets)
  complete = all(target['status'] in ACCEPTED for target in targets.values())
  partial = complete and any(
    target.get('defect_quantity', 0) for target in targets.values() if target.get('process_code')
  )
  result = session.execute(
    update(ProductionJob)
    .where(ProductionJob.id == job.id, ProductionJob.revision == previous)
    .values(
      targets=targets,
      revision=previous + 1,
      status='completed_with_defects' if partial else 'completed' if complete else 'active',
      quantity=job.quantity,
      specification_id=job.specification_id,
      plan_version=job.plan_version,
    ),
    execution_options={'synchronize_session': False},
  )
  if result.rowcount != 1:
    raise WorkflowConflict('다른 담당자가 변경했습니다. 최신 상태를 불러와 주세요.')
  session.expire(job)


def target_documents(session: Session, job: ProductionJob, target: dict) -> list[WorkDocument]:
  return [
    doc
    for doc in list_documents(session, job_id=job.id)
    if target['id'] in doc.scope['target_ids']
    and (doc.scope['round'] == target['round'] or doc.kind.startswith('work_instruction_'))
    and doc.scope['specification_id'] == job.specification_id
    and doc.scope['plan_version'] == target['plan_version']
  ]


def plan_warnings(lines: list[dict]) -> list[str]:
  warnings = []
  by_target: dict[str, list[dict]] = {}
  for line in lines:
    by_target.setdefault(line['target_id'], []).append(line)
  for index, line in enumerate(lines):
    start, end = datetime.fromisoformat(line['start']), datetime.fromisoformat(line['end'])
    minutes = line['duration'] * (60 if line['duration_unit'] == 'hour' else 1)
    if line['time_basis'] == 'per_item':
      minutes *= line['quantity']
    if (end - start).total_seconds() / 60 < minutes:
      warnings.append(
        f'시간 기준 확인: {line["target_id"]} / {line["process"]}의 배정 구간이 예상·표준시간보다 짧습니다.'
      )
    for earlier in lines[:index]:
      if (
        earlier['resource'] == line['resource']
        and start < datetime.fromisoformat(earlier['end'])
        and datetime.fromisoformat(earlier['start']) < end
      ):
        warnings.append(f'자원 중복: {line["resource"]} / {earlier["target_id"]} · {line["target_id"]}')
    for predecessor in line['predecessors']:
      if predecessor not in by_target:
        raise WorkflowError(f'없는 선행 작업: {predecessor}')
      if max(datetime.fromisoformat(operation['end']) for operation in by_target[predecessor]) > start:
        warnings.append(f'명시된 선행 작업 역전: {predecessor} → {line["target_id"]}')
  return warnings


def validate_schedule(
  session: Session, schedule: list[dict], documents: list[WorkDocument], target_ids: set[str], quantity: int
) -> list[str]:
  docs = {doc.id: doc for doc in documents if doc.kind == 'production_plan'}
  covered: set[str] = set()
  operations: dict[str, dict] = {}
  warnings: list[str] = []
  identities: set[tuple[str, str]] = set()
  cited_rows: set[tuple[str, int | None, int | None, str]] = set()
  for entry in schedule:
    identity = (entry['kind'], entry['code'] or entry['process'])
    if identity in identities or entry['end'] < entry['start']:
      raise WorkflowError('중복된 일정 또는 시작보다 빠른 종료일이 있습니다.')
    identities.add(identity)
    kinds = validate_sources(session, entry['sources'], list(docs.values()))
    if not kinds >= PLAN_KINDS:
      raise WorkflowError('날짜 계획의 생산계획서 근거를 연결해 주세요.')
    rows = []
    for source in entry['sources']:
      doc = docs[source['document_id']]
      covered.update(doc.scope['target_ids'])
      cited_rows.add((doc.id, source.get('block_index'), source['page'], source['row']))
      rows.append({HEADER_FIELDS.get(key, key): value for key, value in source_row(doc, source).items()})
    if not any(
      row.get('start_date') == entry['start']
      and row.get('end_date') == entry['end']
      and (
        row.get('품목', row.get('name')) == entry['process']
        if entry['kind'] == 'summary'
        else row.get('process') == entry['process'] and (not entry['code'] or row.get('process_codes') == entry['code'])
      )
      for row in rows
    ):
      raise WorkflowError(f'{entry["process"]}: 공정과 날짜가 원문 행과 다릅니다.')
    for field, original_fields in {
      'track': ('track', '품목'),
      'quantity': ('quantity', '수량'),
      'resource': ('resource', 'assignee'),
      'owner': ('process_owner',),
      'assistants': ('assistants',),
      'working_days': ('working_days',),
      'headcount': ('headcount',),
      'note': ('note',),
    }.items():
      value = entry[field]
      if value is None or value == '':
        continue
      originals = list(dict.fromkeys(str(row[key]).strip() for row in rows for key in original_fields if row.get(key)))
      if str(value) not in originals and str(value) != ', '.join(originals):
        raise WorkflowError(f'{entry["process"]}: {field} 값이 원문 행과 다릅니다.')
    raw_predecessors = next((row['선행 작업'] for row in rows if '선행 작업' in row), '')
    predecessors = [
      value.strip() for value in re.split(r'[,;\n]', raw_predecessors) if value.strip() not in ('', '—', '-', '없음')
    ]
    if entry['predecessors'] != predecessors:
      raise WorkflowError(f'{entry["process"]}: 선행 공정이 원문 행과 다릅니다.')
    if entry['kind'] == 'summary':
      if not any(str(row.get('수량', row.get('quantity', ''))) == entry['quantity'] for row in rows):
        raise WorkflowError('계획 수량이 원문 행과 다릅니다.')
      product_quantity = re.fullmatch(r'(\d+)\s*(?:대|개)', entry['quantity'])
      if product_quantity and int(product_quantity[1]) != quantity:
        raise WorkflowError('완제품 목표 수량이 생산계획서의 수량과 다릅니다.')
    else:
      operations[entry['code'] or entry['process']] = entry
  if not operations or not target_ids <= covered:
    raise WorkflowError('모든 생산 대상을 포함한 생산계획서와 공정 일정이 필요합니다.')
  for doc_id in {row[0] for row in cited_rows}:
    for block in docs[doc_id].blocks:
      if block['kind'] != 'table' or len(block.get('rows', [])) < 2:
        continue
      headers = [HEADER_FIELDS.get(str(header or '').strip(), str(header or '').strip()) for header in block['rows'][0]]
      if not {'start_date', 'end_date'} <= set(headers):
        continue
      location = block.get('location', {})
      block_index = location.get('block_index')
      page = None if block_index else location.get('page_number', 1)
      for index, values in enumerate(block['rows'][1:], start=2):
        if any(values) and (doc_id, block_index, page, str(index)) not in cited_rows:
          raise WorkflowError('생산계획서의 일정 행이 누락되었습니다. 원문 후보를 다시 불러와 주세요.')
  visited: set[str] = set()
  active: set[str] = set()

  def visit(code: str) -> None:
    if code not in operations or code in active:
      raise WorkflowError(f'없는 선행 공정 또는 순환 참조: {code}')
    if code in visited:
      return
    active.add(code)
    for predecessor in operations[code]['predecessors']:
      visit(predecessor)
      if operations[predecessor]['end'] >= operations[code]['start']:
        warnings.append(f'명시된 선행 작업 역전: {predecessor} → {code}')
    active.remove(code)
    visited.add(code)

  for code in operations:
    visit(code)
  assigned = [entry for entry in operations.values() if entry['resource']]
  for index, entry in enumerate(assigned):
    for earlier in assigned[:index]:
      if (
        earlier['resource'] == entry['resource']
        and entry['start'] <= earlier['end']
        and earlier['start'] <= entry['end']
      ):
        warnings.append(f'자원 중복: {entry["resource"]} / {earlier["process"]} · {entry["process"]}')
  return warnings


def confirm_plan(session: Session, user: User, job_id: str, body: PlanIn | SchedulePlanIn) -> ProductionJob:
  require_department(user, PM)
  job = get_job(session, job_id, lock=True)
  check_revision(job.revision, body.revision)
  if not body.confirmed:
    raise WorkflowError('생산계획서의 수량·일정·배정을 직접 확인해 주세요.')
  if any(
    target['kind'] == 'material' and target['condition'].startswith('구매') and target['status'] not in ACCEPTED
    for target in job.targets.values()
  ):
    raise WorkflowConflict('구매 부품의 수입검사를 모두 승인한 뒤 생산계획을 확정해 주세요.')
  spec = get_specification(session, job.specification_id)
  expected = build_targets(spec.graph, body.quantity)
  targets = deepcopy(job.targets)
  expected.update(
    {key: target | {'quantity': body.quantity} for key, target in targets.items() if target.get('process_code')}
  )
  schedule = [entry.model_dump(mode='json') for entry in body.schedule] if isinstance(body, SchedulePlanIn) else []
  lines = [line.model_dump(mode='json') for line in body.lines] if isinstance(body, PlanIn) else []
  if any(target.get('process_code') for target in targets.values()) and not schedule:
    raise WorkflowError('공정 작업 순서를 연결한 생산 건은 선행 관계를 포함한 일 단위 계획이 필요합니다.')
  docs = [
    doc
    for doc in list_documents(session, job_id=job.id)
    if doc.scope['plan_version'] == job.plan_version + 1 and doc.scope['specification_id'] == job.specification_id
  ]
  covered: set[str] = set()
  operations: set[tuple[str, str]] = set()
  for line in lines:
    key = line['target_id']
    operation = (key, line['process'])
    if key not in expected or expected[key]['kind'] == 'material' or operation in operations:
      raise WorkflowError(f'없는 대상 또는 중복된 대상·공정: {key}')
    operations.add(operation)
    target = expected[key]
    start, end = datetime.fromisoformat(line['start']), datetime.fromisoformat(line['end'])
    if start.tzinfo is None or end.tzinfo is None or end <= start:
      raise WorkflowError(f'{key}: 시간대를 포함한 시작·종료 시각이 필요하며 종료는 시작 이후여야 합니다.')
    if line['quantity'] != target['quantity'] or line['unit'] != target['unit']:
      raise WorkflowError(f'{key}: 계획 수량·단위가 BOM 소요 수량과 일치하지 않습니다.')
    scoped_docs = [doc for doc in docs if key in doc.scope['target_ids']]
    expected_row = {
      field: line[field]
      for field in (
        'target_id',
        'quantity',
        'unit',
        'duration',
        'duration_unit',
        'time_basis',
        'process',
        'track',
        'resource',
        'start',
        'end',
      )
    }
    expected_row.update(item_code=target['code'], version=target['version'])
    kinds = validate_sources(session, line['sources'], scoped_docs, expected_row)
    if not kinds >= PLAN_KINDS:
      raise WorkflowError(f'{key}: 생산계획서의 근거를 연결해 주세요.')
    covered.add(key)
  production_ids = {key for key, target in expected.items() if target['kind'] != 'material'}
  if schedule:
    warnings = validate_schedule(session, schedule, docs, production_ids, body.quantity)
  elif covered != production_ids:
    raise WorkflowError('모든 생산 대상의 적용 계획이 필요합니다.')
  else:
    warnings = plan_warnings(lines)
  if warnings and not body.acknowledged_warnings:
    raise WorkflowError(' / '.join(warnings) + ' — 원문 확인 후 주의사항 확인을 선택해 주세요.')
  old_plans = list_plans(session, job.id)
  changed = {key for key in targets if targets[key]['quantity'] != expected[key]['quantity']}
  old_schedule = old_plans[-1].data.get('schedule', []) if old_plans else []
  if old_plans and (schedule or old_schedule):
    # shortcut: date schedule changes recheck all production targets; narrow this when per-process target links exist.
    def comparable_schedule(entries: list[dict]) -> list[dict]:
      return [{key: value for key, value in entry.items() if key != 'sources'} for entry in entries]

    if comparable_schedule(schedule) != comparable_schedule(old_schedule):
      changed.update(production_ids)
  fields = ('quantity', 'unit', 'process', 'track', 'resource', 'duration', 'duration_unit', 'time_basis')
  for key in targets:
    old = [line for line in old_plans[-1].data['lines'] if line['target_id'] == key] if old_plans else []
    new = [line for line in lines if line['target_id'] == key]

    def comparable(operations: list[dict]) -> list[tuple]:
      return sorted(
        tuple(line[field] for field in fields)
        + (
          datetime.fromisoformat(line['start']).timestamp(),
          datetime.fromisoformat(line['end']).timestamp(),
        )
        for line in operations
      )

    if old and comparable(old) != comparable(new):
      changed.add(key)
  affected = invalidate(targets, changed, body.reason) if changed else set()
  job.quantity = body.quantity
  job.plan_version += 1
  for key, target in targets.items():
    target['quantity'] = expected[key]['quantity']
    if target['kind'] != 'material' and (key in affected or not old_plans or not target['plan_version']):
      target['plan_version'] = job.plan_version
  if schedule:
    configure_processes(targets, schedule, body.quantity)
  data = body.model_dump(mode='json') | {'lines': lines, 'warnings': warnings}
  session.add(ProductionPlan(job_id=job.id, version=job.plan_version, data=data, created_by=user.id))
  record_event(
    session,
    user,
    'plan_confirmed',
    data | {'plan_version': job.plan_version, 'affected': sorted(affected)},
    job_id=job.id,
  )
  finish_job_change(session, job, targets)
  return job


def get_target(targets: dict, target_id: str) -> dict:
  if target_id not in targets:
    raise WorkflowError('이 생산 건에 없는 대상입니다.')
  return targets[target_id]


def waiting_reasons(job: ProductionJob, target: dict) -> list[str]:
  reasons = []
  if target.get('inventory_of'):
    return ['가공 부품 재고는 원문 공정의 승인 실적에서 자동 집계합니다.']
  for child in target['children']:
    if job.targets[child]['status'] not in ACCEPTED:
      reasons.append(f'{job.targets[child]["name"]}: 하위 대상 합격 대기')
  if target['kind'] != 'material' and not target['plan_version']:
    reasons.append('생산 전 계획 확정 대기')
  if target['kind'] != 'material' and any(
    item['kind'] == 'material' and item['condition'].startswith('구매') for item in job.targets.values()
  ):
    if any(
      item['kind'] == 'material' and item['condition'].startswith('구매') and item['status'] not in ACCEPTED
      for item in job.targets.values()
    ):
      reasons.append('구매 부품 전체 수입검사 승인 대기')
    if not target.get('process_code'):
      reasons.append('해당 단계 작업 순서 연결 대기')
  if target.get('pending_predecessors'):
    reasons.append('선행 공정 작업 순서 연결 대기: ' + ', '.join(target['pending_predecessors']))
  if target.get('process_code') and target['kind'] in ('assembly', 'product'):
    previous_kind = 'component' if target['kind'] == 'assembly' else 'assembly'
    previous = [item for item in job.targets.values() if item.get('process_code') and item['kind'] == previous_kind]
    if not previous or any(item['status'] not in ACCEPTED for item in previous):
      reasons.append(f'{"1차 모듈" if previous_kind == "component" else "2차 모듈"} 전체 검사 승인 대기')
  if target['status'] == 'held':
    reasons.append('불합격 전체 보류 · 담당 부서 보완 대기')
  return reasons


def start_production(session: Session, user: User, job_id: str, target_id: str, revision: int) -> ProductionJob:
  require_department(user, PM)
  job = get_job(session, job_id, lock=True)
  check_revision(job.revision, revision)
  targets = deepcopy(job.targets)
  target = get_target(targets, target_id)
  reasons = waiting_reasons(job, target)
  if target['kind'] == 'material' or target['status'] != 'waiting' or reasons:
    raise WorkflowConflict(' / '.join(reasons) or '현재 상태에서 생산을 시작할 수 없습니다.')
  target['status'] = 'producing'
  record_event(
    session,
    user,
    'production_started',
    {'round': target['round'], 'plan_version': target['plan_version']},
    job_id=job.id,
    target_id=target_id,
  )
  finish_job_change(session, job, targets)
  return job


def complete_production(session: Session, user: User, job_id: str, body: CompletionIn) -> ProductionJob:
  require_department(user, PM)
  job = get_job(session, job_id, lock=True)
  check_revision(job.revision, body.revision)
  targets = deepcopy(job.targets)
  target = get_target(targets, body.target_id)
  if target['status'] != 'producing' or not body.confirmed or waiting_reasons(job, target):
    raise WorkflowConflict('생산 착수와 담당자의 완료 확인이 필요합니다.')
  if target.get('process_code'):
    counts = count_source(
      session, target, [source.model_dump() for source in body.sources], target_documents(session, job, target)
    )
    if (
      Decimal(str(body.quantity)) != counts['input_quantity']
      or body.quantity > target['quantity']
      or body.unit != target['unit']
    ):
      raise WorkflowError('계획 범위와 해당 공정 원문의 실제 투입 수량·단위를 확인해 주세요.')
    reserve_inputs(targets, target, body.quantity)
    target['input_quantity'] = body.quantity
  elif body.quantity != target['quantity'] or body.unit != target['unit']:
    raise WorkflowError(
      f'계획 {target["quantity"]} {target["unit"]}와 완료 수량·단위가 일치해야 합니다. 부족·초과 모두 불가합니다.'
    )
  event = record_event(
    session,
    user,
    'production_completed',
    body.model_dump()
    | {
      'round': target['round'],
      'plan_version': target['plan_version'],
      'specification_id': job.specification_id,
    },
    job_id=job.id,
    target_id=body.target_id,
  )
  target.update(status='inspection', completion_id=event.id)
  finish_job_change(session, job, targets)
  return job


def inspect_target(session: Session, user: User, job_id: str, body: InspectionIn) -> ProductionJob:
  require_department(user, QA)
  job = get_job(session, job_id, lock=True)
  check_revision(job.revision, body.revision)
  targets = deepcopy(job.targets)
  target = get_target(targets, body.target_id)
  if target.get('inventory_of'):
    raise WorkflowError('가공 부품 재고의 검사는 해당 공정에서 기록해 주세요.')
  material = target['kind'] == 'material'
  if not body.confirmed or target['status'] != ('waiting' if material else 'inspection'):
    raise WorkflowConflict('해당 회차의 생산 완료 또는 품질 담당자 확인이 필요합니다.')
  if not material and (not target['completion_id'] or waiting_reasons(job, target)):
    raise WorkflowConflict('유효한 생산 완료와 직접 하위 대상 합격이 필요합니다.')
  docs = target_documents(session, job, target)
  kinds = validate_sources(
    session,
    [source.model_dump() for source in body.sources],
    docs,
    {
      'item_code': target['code'],
      'version': target['version'],
      'standard': body.standard,
      'measured_value': body.measured_value,
      'unit': body.unit,
      'grade': body.grade,
      'result': body.result,
    },
  )
  if body.result == 'pass' and INSPECTION_KINDS[target['kind']] not in kinds:
    raise WorkflowError('재료는 수입검사성적서, 생산품은 해당 공정 단계의 검사성적서가 필요합니다.')
  if body.result == 'fail' and (not body.cause or not body.reason.strip()):
    raise WorkflowError('불합격 원인과 보완 사유를 남겨 주세요.')
  if target.get('process_code'):
    counts = count_source(session, target, [source.model_dump() for source in body.sources], docs)
    if (
      body.good_quantity is None
      or body.defect_quantity is None
      or Decimal(str(body.good_quantity)) != counts['good_quantity']
      or Decimal(str(body.defect_quantity)) != counts['defect_quantity']
      or Decimal(str(target['input_quantity'])) != counts['input_quantity']
    ):
      raise WorkflowError('투입 = 양품 + 불량 수량을 원문 및 생산 완료 기록과 대조해 주세요.')
    if body.result == 'pass' and not body.good_quantity:
      raise WorkflowError('승인할 양품이 없습니다. 불합격으로 보류해 주세요.')
    target.update(good_quantity=body.good_quantity, defect_quantity=body.defect_quantity)
  event = record_event(
    session,
    user,
    'inspection',
    body.model_dump()
    | {
      'round': target['round'],
      'plan_version': target['plan_version'],
      'specification_id': job.specification_id,
      'completion_id': target['completion_id'],
      'stage': 1 if material else 3 if target['kind'] == 'product' else 2,
      'quantity': target.get('input_quantity', target['quantity']),
      'quantity_unit': target['unit'],
      'planned_quantity': target['quantity'],
      'condition': target['condition'],
      'responsible_department': {'physical': PM, 'specification': RD, 'evidence': QA}.get(body.cause),
    },
    job_id=job.id,
    target_id=body.target_id,
  )
  target.update(status='passed' if body.result == 'pass' else 'held', inspection_id=event.id)
  if body.result == 'pass' and target.get('process_code') and body.defect_quantity:
    target['status'] = 'partial'
  if body.result == 'fail':
    target['issue'] = {'cause': body.cause, 'reason': body.reason, 'event_id': event.id}
  finish_job_change(session, job, targets)
  return job


def rework_target(session: Session, user: User, job_id: str, body: ReworkIn) -> ProductionJob:
  responsible = {'physical': PM, 'specification': RD, 'evidence': QA}[body.cause]
  require_department(user, responsible)
  job = get_job(session, job_id, lock=True)
  check_revision(job.revision, body.revision)
  targets = deepcopy(job.targets)
  target = get_target(targets, body.target_id)
  if target.get('inventory_of'):
    raise WorkflowError('가공 부품 재고의 보완은 해당 공정에서 요청해 주세요.')
  if target['status'] not in ('held', 'passed', 'partial', 'inspection', 'producing'):
    raise WorkflowConflict('보완·변경할 현재 완료/검사 대상이 없습니다.')
  if target['issue'] and target['issue']['cause'] != body.cause:
    raise WorkflowError('최초 불합격 원인에 해당하는 부서에서 보완해 주세요.')
  old_specification_id = job.specification_id
  if body.cause == 'specification':
    if not body.specification_id:
      raise WorkflowError('R&D가 제출한 새 사양/BOM 버전을 선택해 주세요.')
    new_spec = get_specification(session, body.specification_id)
    old_spec = get_specification(session, job.specification_id)
    if new_spec.status != 'submitted' or new_spec.previous_id != old_spec.id:
      raise WorkflowError('현재 사양을 이전 버전으로 참조하는 새 제출본이 필요합니다.')
    replacement = build_targets(new_spec.graph, job.quantity)
    old_items = {(item['code'], item['version']): item for item in old_spec.graph['items']}
    new_items = {item['key']: item for item in new_spec.graph['items']}
    changed = set()
    for key, candidate in replacement.items():
      old = targets.get(key)
      item_key = candidate['item_key']
      old_item = old_items.get((candidate['code'], candidate['version']))
      if (
        not old
        or not old_item
        or semantic_item(old_item, old_spec.graph) != semantic_item(new_items[item_key], new_spec.graph)
      ):
        changed.add(key)
      if old:
        replacement[key] = old | {
          'quantity': candidate['quantity'],
          'children': candidate['children'],
          'item_key': candidate['item_key'],
          'name': candidate['name'],
        }
        if old['quantity'] != candidate['quantity']:
          changed.add(key)
    if not changed:
      raise WorkflowError('새 사양에서 변경된 대상이 없습니다.')
    if any(value.get('process_code') for value in targets.values()):
      replacement = {
        key: candidate | {'round': targets.get(key, {}).get('round', 1), 'plan_version': 0}
        for key, candidate in build_targets(new_spec.graph, job.quantity).items()
      }
      changed = set(replacement)
    affected = invalidate(replacement, changed, body.reason)
    targets = replacement
    job.specification_id = new_spec.id
    for key in affected:
      targets[key]['plan_version'] = 0
  elif body.cause == 'evidence':
    if not body.document_ids:
      raise WorkflowError('보충한 증빙 문서를 선택해 주세요.')
    docs = {doc.id: doc for doc in target_documents(session, job, target) if doc.status == 'parsed'}
    if any(doc_id not in docs for doc_id in body.document_ids):
      raise WorkflowError('현재 대상·회차의 보충 문서만 선택할 수 있습니다.')
    completion_id = target['completion_id']
    input_quantity = target.get('input_quantity')
    affected = invalidate(targets, {body.target_id}, body.reason)
    target['completion_id'] = completion_id
    if input_quantity is not None:
      target['input_quantity'] = input_quantity
    target['status'] = 'inspection' if completion_id else 'waiting'
  else:
    affected = invalidate(targets, {body.target_id}, body.reason)
  record_event(
    session,
    user,
    'rework',
    body.model_dump()
    | {
      'previous_specification_id': old_specification_id,
      'specification_id': job.specification_id,
      'affected': sorted(affected),
      'round': get_target(targets, body.target_id)['round'] if body.target_id in targets else None,
      'responsible_department': responsible,
    },
    job_id=job.id,
    target_id=body.target_id,
  )
  finish_job_change(session, job, targets)
  return job


def specification_composition_groups(session: Session, spec: Specification, targets: dict) -> list[dict]:
  root = next((target for target in targets.values() if target.get('item_key') == spec.graph.get('root')), None)
  if not root or not spec.graph.get('root'):
    return []
  sections = {}
  for doc in list_documents(session, specification_id=spec.id):
    if doc.kind != 'product_detail' or doc.status != 'parsed':
      continue
    for block in doc.blocks:
      location = block.get('location') or {}
      match = re.search(r'\(([^()]+모듈)\)\s*$', location.get('section_title') or '')
      if match and location.get('block_index'):
        sections[(doc.id, location['block_index'])] = match[1].strip()
  items = {item['key']: item for item in spec.graph['items']}
  groups: dict[str, list[str]] = {}
  for key in root['children']:
    target = targets[key]
    if target['children'] or target['item_key'] not in items:
      continue
    for attribute in items[target['item_key']]['attributes']:
      source = attribute.get('source') or {}
      name = sections.get((source.get('document_id'), source.get('block_index')))
      if name:
        members = groups.setdefault(name, [])
        if key not in members:
          members.append(key)
  return [{'name': name, 'target_ids': members} for name, members in groups.items()]


def serialize_job(session: Session, job: ProductionJob) -> dict:
  spec = get_specification(session, job.specification_id)
  targets = {
    key: target
    | {
      'waiting_reasons': waiting_reasons(job, target),
      'parents': [parent['id'] for parent in job.targets.values() if key in parent['children']],
      **(
        {
          'remaining_by_output': remaining_outputs(target),
          'remaining_quantity': next(iter(remaining_outputs(target).values()))
          if len(target.get('output_names', [])) == 1
          else None,
        }
        if target.get('process_code')
        else {}
      ),
    }
    for key, target in job.targets.items()
  }
  return {
    'id': job.id,
    'name': job.name,
    'specification_id': spec.id,
    'product_code': spec.code,
    'product_name': spec.name,
    'specification_version': spec.version,
    'quantity': job.quantity,
    'revision': job.revision,
    'plan_version': job.plan_version,
    'status': job.status,
    'targets': targets,
    'composition_groups': specification_composition_groups(session, spec, job.targets),
    'production_result': next(
      (
        {field: target.get(field, 0) for field in ('input_quantity', 'good_quantity', 'defect_quantity', 'unit')}
        for target in job.targets.values()
        if target['kind'] == 'product' and target.get('process_code') and target.get('input_quantity') is not None
      ),
      None,
    ),
    'created_at': job.created_at,
  }
