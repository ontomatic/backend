"""Document-backed process targets and lot quantities, separate from immutable BOM definitions."""

import re
from copy import deepcopy
from decimal import Decimal
from graphlib import CycleError, TopologicalSorter

from sqlalchemy.orm import Session

from backend.exceptions.workflow import WorkflowError
from backend.models.user import User
from backend.models.workflow import ProductionJob, WorkDocument
from backend.repositories.workflow import list_documents, list_plans
from backend.services.document_formats import HEADER_FIELDS, reference_table_candidates

ACCEPTED = {'passed', 'partial'}
INSTRUCTION_KINDS = {
  'work_instruction_module1': 'component',
  'work_instruction_lens': 'assembly',
  'work_instruction_body': 'assembly',
  'work_instruction_final': 'product',
}


def names(value: str) -> list[str]:
  return [part.strip() for part in re.split(r'[,，+]', value) if part.strip()]


def normalized(value: str) -> str:
  return ''.join(value.split())


def register_instruction(session: Session, user: User, job: ProductionJob, doc: WorkDocument) -> None:
  from backend.services.workflow import finish_job_change, record_event

  if doc.kind not in INSTRUCTION_KINDS or doc.status != 'parsed':
    return
  reference = reference_table_candidates(doc.id, doc.blocks)
  rows = reference['rows'] if reference else []
  targets = deepcopy(job.targets)
  selected = []
  changed = False
  for row in rows:
    flow = str(row.get('input_output') or '')
    codes = names(str(row.get('process_codes') or ''))
    if '→' not in flow or not codes or not row.get('process'):
      continue
    inputs, outputs = flow.split('→', 1)
    output_names = names(outputs)
    if len(codes) > 1 and len(codes) != len(output_names):
      raise WorkflowError('여러 공정번호의 산출물을 각각 구분해 주세요.')
    for index, code in enumerate(codes):
      if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', code):
        raise WorkflowError('공정번호 형식을 확인해 주세요.')
      kind = INSTRUCTION_KINDS[doc.kind]
      key = (
        next(key for key, target in targets.items() if target['kind'] == 'product')
        if kind == 'product'
        else f'process:{code}'
      )
      selected.append(key)
      existing = targets.get(key)
      if existing and existing.get('process_code'):
        if (
          existing['process_code'] != code
          or existing['kind'] != kind
          or existing['input_names'] != names(inputs)
          or existing['output_names'] != ([output_names[index]] if len(codes) > 1 else output_names)
        ):
          raise WorkflowError('같은 대상의 공정번호·단계가 다른 작업 순서와 충돌합니다.')
        continue
      if job.plan_version and doc.scope['plan_version'] != job.plan_version:
        raise WorkflowError('새 공정 작업 순서는 현재 확정 계획에 연결해 주세요.')
      if existing and (
        existing['status'] != 'waiting' or existing.get('completion_id') or existing.get('inspection_id')
      ):
        raise WorkflowError('생산·검사가 진행된 대상에는 새 공정을 연결할 수 없습니다.')
      if not names(inputs) or not output_names:
        raise WorkflowError('공정의 투입·산출 이름이 필요합니다.')
      source = {
        'document_id': doc.id,
        'page': row.get('page'),
        'block_index': row.get('block_index'),
        'row': row['row'],
      }
      target = existing or {
        'id': key,
        'item_key': '',
        'code': code,
        'kind': kind,
        'version': 1,
        'quantity': job.quantity,
        'unit': '개',
        'condition': str(row.get('workplace') or row.get('section_title') or ''),
        'children': [],
        'status': 'waiting',
        'round': 1,
        'completion_id': None,
        'inspection_id': None,
        'plan_version': job.plan_version,
        'issue': None,
      }
      targets[key] = target | {
        'name': str(row['process']).split('\n', 1)[0],
        'process_code': code,
        'input_names': names(inputs),
        'output_names': [output_names[index]] if len(codes) > 1 else output_names,
        'instruction_group': f'{doc.id}:{row.get("block_index") or row.get("page")}:{row["row"]}',
        'preparation': '부품 준비' in str(row['process']),
        'instruction_source': source,
        'predecessor_ids': [],
        'allocations': {},
      }
      changed = True
  if selected:
    doc.scope = doc.scope | {'target_ids': list(dict.fromkeys(selected))}
  if changed:
    if job.plan_version:
      plan = next(plan for plan in list_plans(session, job.id) if plan.version == job.plan_version)
      if not plan.data.get('schedule'):
        raise WorkflowError('공정 작업 순서를 연결하려면 공정번호가 포함된 일 단위 생산계획이 필요합니다.')
      configure_processes(targets, plan.data['schedule'], job.quantity)
      for key in selected:
        targets[key]['plan_version'] = job.plan_version
    for plan in list_documents(session, job_id=job.id):
      if plan.kind != 'production_plan' or plan.scope['plan_version'] != doc.scope['plan_version']:
        continue
      plan_rows = reference_table_candidates(plan.id, plan.blocks)
      codes = {str(row.get('process_codes') or '') for row in (plan_rows or {}).get('rows', [])}
      added = [key for key in selected if targets[key]['process_code'] in codes]
      plan.scope = plan.scope | {'target_ids': list(dict.fromkeys([*plan.scope['target_ids'], *added]))}
    record_event(session, user, 'processes_registered', {'document_id': doc.id, 'target_ids': selected}, job_id=job.id)
    finish_job_change(session, job, targets)


def configure_processes(targets: dict, schedule: list[dict], quantity: float) -> None:
  processes = {target['process_code']: target for target in targets.values() if target.get('process_code')}
  if not processes:
    return
  entries = {entry['code']: entry for entry in schedule if entry['kind'] == 'operation'}
  purchased = [
    target['id']
    for target in targets.values()
    if target['kind'] == 'material' and target['condition'].startswith('구매')
  ]
  for code, target in processes.items():
    entry = entries.get(code)
    if not entry:
      raise WorkflowError(f'{code}: 작업 순서에 해당하는 계획 일정이 없습니다.')
    dependencies = []
    pending = []
    for predecessor in entry['predecessors']:
      if predecessor in processes:
        dependencies.append(processes[predecessor]['id'])
      elif predecessor in entries and '수입검사' in entries[predecessor]['process'] and purchased:
        dependencies.extend(purchased)
      elif predecessor in entries:
        pending.append(predecessor)
      else:
        raise WorkflowError(f'{predecessor}: 선행 공정의 작업 순서 또는 수입검사 대상이 없습니다.')
    target['predecessor_ids'] = [key for key in dependencies if targets[key].get('process_code')]
    target['pending_predecessors'] = pending
    bom_children = (
      [key for key in target['children'] if not targets[key].get('process_code')] if target['kind'] == 'product' else []
    )
    target['children'] = list(dict.fromkeys([*bom_children, *dependencies]))
    raw_quantity = entry['quantity']
    if target['kind'] == 'product' and not raw_quantity:
      raw_quantity = next(
        (
          entry['quantity']
          for entry in schedule
          if entry['kind'] == 'summary' and re.fullmatch(r'\d+\s*(대|개)', entry['quantity'])
        ),
        '',
      )
    match = re.fullmatch(r'\d+(?:\.\d+)?\s*(대분|대|개)', raw_quantity)
    if match:
      target['unit'] = match[1]
    target['quantity'] = quantity
  for target in targets.values():
    if target.get('process_code') or not target['condition'].startswith('자체 가공'):
      continue
    matches = [
      process
      for code, process in processes.items()
      if code in re.findall(r'[A-Za-z0-9]+(?:[-._][A-Za-z0-9]+)+', target['condition'])
    ]
    if not matches and any(
      code in entries for code in re.findall(r'[A-Za-z0-9]+(?:[-._][A-Za-z0-9]+)+', target['condition'])
    ):
      continue
    if len(matches) != 1:
      raise WorkflowError(f'{target["name"]}: 자체 가공 공정번호를 확인해 주세요.')
    process = matches[0]
    output = next(
      (name for name in process['output_names'] if normalized(name) == normalized(target['name'].partition(' (')[0])),
      None,
    )
    if not output:
      raise WorkflowError(f'{target["name"]}: 작업 순서의 산출물과 BOM 품목이 일치하지 않습니다.')
    target.update(
      inventory_of=process['id'],
      inventory_output=output,
      inventory_factor=target['quantity'] / quantity,
      children=[process['id']],
    )

  try:
    TopologicalSorter({key: target['children'] for key, target in targets.items()}).prepare()
  except CycleError as exc:
    raise WorkflowError('BOM 재고와 선행 공정 사이에 순환 참조가 있습니다.') from exc


def count_source(session: Session, target: dict, sources: list[dict], documents: list[WorkDocument]) -> dict:
  from backend.services.workflow import INSPECTION_KINDS, source_row, validate_sources

  eligible = [doc for doc in documents if doc.kind == INSPECTION_KINDS[target['kind']]]
  validate_sources(session, sources, documents)
  docs = {doc.id: doc for doc in eligible}
  for source in sources:
    if source['document_id'] not in docs:
      continue
    row = {HEADER_FIELDS.get(key, key): value for key, value in source_row(docs[source['document_id']], source).items()}
    if target['process_code'] not in names(str(row.get('process_codes') or '')):
      continue
    try:
      counts = {field: Decimal(str(row[field])) for field in ('input_quantity', 'good_quantity', 'defect_quantity')}
    except (KeyError, ArithmeticError, ValueError):
      continue
    if (
      any(not value.is_finite() or value < 0 for value in counts.values())
      or counts['input_quantity'] != counts['good_quantity'] + counts['defect_quantity']
    ):
      raise WorkflowError('원문의 투입 = 양품 + 불량 수량을 확인해 주세요.')
    return counts
  raise WorkflowError('해당 공정의 투입·양품·불량 수량이 있는 원문 행을 연결해 주세요.')


def reserve_inputs(targets: dict, target: dict, quantity: float) -> None:
  group = f'{target["instruction_group"]}:{target["round"]}'
  for key in target['predecessor_ids']:
    parent = targets[key]
    outputs = [
      name
      for name in parent['output_names']
      if any(normalized(name) == normalized(value) for value in target['input_names'])
    ]
    if not outputs:
      raise WorkflowError(f'{parent["name"]} → {target["name"]}: 투입·산출 관계를 원문에서 확인해 주세요.')
    allocations = parent.setdefault('allocations', {})
    current = allocations.get(group, {})
    amount = max(quantity, current.get('quantity', 0))
    outputs = list(dict.fromkeys([*current.get('outputs', []), *outputs]))
    for output in outputs:
      used = sum(
        Decimal(str(item['quantity']))
        for other, item in allocations.items()
        if other != group and output in item['outputs']
      )
      if Decimal(str(amount)) + used > Decimal(str(parent.get('good_quantity', 0))):
        raise WorkflowError(f'{parent["name"]}: 승인된 양품 재고보다 투입 수량이 많습니다.')
    allocations[group] = {'quantity': amount, 'outputs': outputs}


def remaining_outputs(target: dict) -> dict[str, float]:
  return {
    output: float(
      Decimal(str(target.get('good_quantity', 0)))
      - sum(
        (
          Decimal(str(item['quantity'])) for item in target.get('allocations', {}).values() if output in item['outputs']
        ),
        Decimal(0),
      )
    )
    for output in target.get('output_names', [])
  }


def update_inventory(targets: dict) -> None:
  for target in targets.values():
    if not target.get('inventory_of'):
      continue
    process = targets[target['inventory_of']]
    factor = Decimal(str(target['inventory_factor']))
    target['status'] = process['status'] if process['status'] in ACCEPTED else 'waiting'
    target['completion_id'] = process['completion_id']
    target['inspection_id'] = process['inspection_id']
    for field in ('input_quantity', 'good_quantity', 'defect_quantity'):
      target[field] = float(Decimal(str(process.get(field, 0))) * factor)
    target['remaining_quantity'] = float(
      Decimal(str(remaining_outputs(process).get(target['inventory_output'], 0))) * factor
    )


def rebuild_allocations(targets: dict) -> None:
  for target in targets.values():
    if target.get('process_code'):
      target['allocations'] = {}
  for target in targets.values():
    if target.get('process_code') and target.get('input_quantity') is not None:
      reserve_inputs(targets, target, target['input_quantity'])
