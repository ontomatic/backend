"""Reproducible, explicitly fictional four-camera documents for workflow verification."""

import csv
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from backend.services.workflow import build_targets

PRODUCTS = {
  'digital': ('CAM-DIG-001', '일반 디지털 카메라'),
  'telephoto': ('CAM-TEL-001', '초망원 렌즈 장착 디지털 카메라'),
  'film': ('CAM-FIL-001', '필름 카메라'),
  'polaroid': ('CAM-POL-001', '폴라로이드 카메라'),
}
HEADERS = [
  'record_type',
  'item_code',
  'name',
  'kind',
  'version',
  'field',
  'value',
  'unit',
  'parent',
  'child',
  'quantity',
  'condition',
  'notice',
]
NOTICE = 'DEMO ONLY — 가상 사양·수량·시험 기준. 실제 제품 인증 기준이 아닙니다.'


def write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
  with path.open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)


def generate_demo(output: Path) -> dict:
  output.mkdir(parents=True, exist_ok=True)
  manifest = {'notice': NOTICE, 'products': []}
  for product_type, (code, name) in PRODUCTS.items():
    directory = output / product_type
    directory.mkdir(exist_ok=True)
    nodes = [
      (code, name, 'product'),
      (f'{code}-LENS', '렌즈 모듈', 'assembly'),
      (f'{code}-SENSOR', '감광 모듈', 'assembly'),
      (f'{code}-OPTIC', '광학 주요 부품', 'component'),
      (f'{code}-CORE', '감광 주요 부품', 'component'),
      (f'{code}-GLASS', '광학 재료', 'material'),
      (f'{code}-SILICON', '감광 재료', 'material'),
      ('MAT-SCR-001', '공통 체결 나사', 'material'),
    ]
    edges = [
      (code, f'{code}-LENS', 1, 'DEMO'),
      (code, f'{code}-SENSOR', 1, 'DEMO'),
      (f'{code}-LENS', f'{code}-OPTIC', 1, 'DEMO'),
      (f'{code}-SENSOR', f'{code}-CORE', 1, 'DEMO'),
      (f'{code}-OPTIC', f'{code}-GLASS', 1, 'DEMO'),
      (f'{code}-CORE', f'{code}-SILICON', 1, 'DEMO'),
      (f'{code}-LENS', 'MAT-SCR-001', 4, 'J8-DEMO'),
      (f'{code}-SENSOR', 'MAT-SCR-001', 6, 'J8-DEMO'),
    ]
    rows = []
    for item_code, item_name, kind in nodes:
      rows.append(
        dict(record_type='item', item_code=item_code, name=item_name, kind=kind, version=1, unit='개', notice=NOTICE)
      )
      for field, value, unit in [('길이', '0.8', 'cm'), ('질량', '0.01', 'kg'), ('재질', 'DEMO-MATERIAL', '')]:
        rows.append(dict(record_type='attribute', item_code=item_code, version=1, field=field, value=value, unit=unit))
    for parent, child, amount, condition in edges:
      rows.append(
        dict(record_type='relation', parent=f'{parent}@1', child=f'{child}@1', quantity=amount, condition=condition)
      )
    write_csv(directory / 'product_detail.csv', rows, HEADERS)
    write_csv(directory / 'bom_transfer.csv', [row for row in rows if row['record_type'] != 'attribute'], HEADERS)
    amount = 10
    targets = build_targets(
      {
        'root': f'{code}@1',
        'items': [
          {'key': f'{item_code}@1', 'code': item_code, 'name': item_name, 'kind': kind, 'version': 1, 'unit': '개'}
          for item_code, item_name, kind in nodes
        ],
        'relations': [
          {'parent': f'{parent}@1', 'child': f'{child}@1', 'quantity': count, 'condition': condition}
          for parent, child, count, condition in edges
        ],
      },
      amount,
    )
    production = list(reversed([node for node in nodes if node[2] != 'material']))
    plan_rows = []
    start = datetime.fromisoformat('2026-11-02T09:00:00+09:00')
    for index, (item_code, item_name, _kind) in enumerate(production):
      begin = start + timedelta(hours=index)
      target_id = next(target['id'] for target in targets.values() if target['code'] == item_code)
      plan_rows.append(
        {
          'target_id': target_id,
          'item_code': item_code,
          'version': 1,
          'name': item_name,
          'process': '시연 조립',
          'track': f'DEMO-T{index + 1}',
          'quantity': amount,
          'unit': '개',
          'duration': 1,
          'duration_unit': 'hour',
          'time_basis': 'batch',
          'resource': f'가상 작업자 {index + 1}',
          'start': begin.isoformat(),
          'end': (begin + timedelta(hours=1)).isoformat(),
          'notice': NOTICE,
        }
      )
    write_csv(directory / 'production_plan.csv', plan_rows, list(plan_rows[0]))
    for document_kind, codes in {
      'work_instruction_module1': {item_code for item_code, _, kind in nodes if kind == 'component'},
      'work_instruction_lens': {f'{code}-LENS'},
      'work_instruction_body': {f'{code}-SENSOR'},
      'work_instruction_final': {code},
    }.items():
      write_csv(
        directory / f'{document_kind}.csv', [row for row in plan_rows if row['item_code'] in codes], list(plan_rows[0])
      )
    for document_kind, target_kind in {
      'incoming_inspection': 'material',
      'inspection_module1': 'component',
      'inspection_module2': 'assembly',
      'inspection_final': 'product',
    }.items():
      quality_rows = [
        {
          'item_code': item_code,
          'version': 1,
          'name': item_name,
          'standard': 'DEMO-8-v1',
          'criterion': '가상 길이 8 mm ± 0.1 mm',
          'measured_value': '8',
          'unit': 'mm',
          'grade': 'A-DEMO',
          'result': 'pass',
          'notice': NOTICE,
        }
        for item_code, item_name, kind in nodes
        if kind == target_kind
      ]
      write_csv(directory / f'{document_kind}.csv', quality_rows, list(quality_rows[0]))
      if product_type == 'digital' and document_kind == 'inspection_module2':
        failure = deepcopy(quality_rows)
        for row in failure:
          if row['item_code'] == f'{code}-LENS':
            row.update(measured_value='7', result='fail')
        write_csv(directory / 'inspection_module2_failure.csv', failure, list(failure[0]))
    if product_type == 'digital':
      revision_rows = deepcopy(rows)
      for row in revision_rows:
        if row.get('record_type') in ('item', 'attribute') and row.get('item_code') in (code, f'{code}-LENS'):
          row['version'] = 2
        if row.get('record_type') == 'relation':
          for field in ('parent', 'child'):
            if row[field] in (f'{code}@1', f'{code}-LENS@1'):
              row[field] = row[field][:-1] + '2'
          if row['parent'] == f'{code}-LENS@2' and row['child'] == 'MAT-SCR-001@1':
            row.update(child='MAT-SCR-001@2', condition='J10-DEMO')
      for original in rows:
        if original.get('item_code') == 'MAT-SCR-001':
          new = deepcopy(original) | {'version': 2}
          if new.get('field') == '길이':
            new['value'] = '1'
          revision_rows.append(new)
      write_csv(directory / 'product_detail_revision.csv', revision_rows, HEADERS)
      changed_plan = [row | {'quantity': 12} for row in plan_rows]
      write_csv(directory / 'production_plan_quantity_12.csv', changed_plan, list(changed_plan[0]))
    expected = {
      'code': code,
      'name': name,
      'product_type': product_type,
      'item_count': 8,
      'attribute_count': 24,
      'relation_count': 8,
      'quantity': amount,
      'screw_quantity': 100,
      'canonical_length': {'value': 8, 'unit': 'mm'},
      'canonical_mass': {'value': 10, 'unit': 'g'},
      'workflow_order': [
        next(target['id'] for target in targets.values() if target['code'] == item_code)
        for item_code, _, kind in production
      ],
    }
    (directory / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2) + '\n')
    manifest['products'].append(expected)
  manifest['digital_exceptions'] = [
    {'case': 'quantity_shortage', 'planned': 10, 'completed': 8, 'expected': 'reject'},
    {'case': 'quantity_excess', 'planned': 10, 'completed': 12, 'expected': 'reject'},
    {'case': 'partial_failure', 'expected': 'hold_entire_unit'},
    {'case': 'physical_rework', 'expected': 'new_round_preserve_unaffected_passes'},
    {'case': 'specification_change', 'expected': 'new_item_and_ancestor_versions_explicit_job_application'},
    {'case': 'missing_evidence', 'expected': 'uploader_supplements_then_quality_reinspection'},
    {'case': 'plan_change', 'expected': 'reason_new_version_preserve_history'},
  ]
  (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
  return manifest
