import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

from langfuse import Evaluation, Langfuse

from .extract import extract
from .files import DATA, model_folder, model_folders, resolve_file
from .parser import parse_docx
from .tracking import run_items, tracking
from .validate import RULE_NAMES, validate


def validation_scores(*, output: dict, metadata: dict, **kwargs: Any) -> list[Evaluation]:
  return [
    Evaluation(name='detected', value=output['caught'], data_type='BOOLEAN'),
    Evaluation(name='changed', value=output['changed'], data_type='BOOLEAN'),
    Evaluation(name='baseline_issues', value=metadata['baseline_issues']),
    Evaluation(name='uncovered_rules', value=metadata['uncovered_rules']),
  ]


def check_model(folder: Path, cases_folder: Path, *, client: Langfuse | None = None) -> dict:
  original = {unicodedata.normalize('NFC', p.name): parse_docx(p) for p in sorted(folder.glob('*.docx'))}
  if not original:
    raise ValueError(f'{folder}: 원본 문서가 없음')
  cases = json.loads((cases_folder / 'cases.json').read_text(encoding='utf-8'))['cases']
  if not cases or len({c['id'] for c in cases}) != len(cases):
    raise ValueError(f'{cases_folder}: 사례가 없거나 사례 ID가 중복됨')

  baseline = validate(extract([block for blocks in original.values() for block in blocks]))
  baseline_keys = {(i['rule'], i['message']) for i in baseline}
  items = []
  covered = {rule for case in cases for rule in case['expect']}
  uncovered = sorted(set(RULE_NAMES) - covered)
  for case in cases:
    if not case['files'] or not case['expect'] or any(rule not in RULE_NAMES for rule in case['expect']):
      raise ValueError(f'{case["id"]}: 변형 문서 또는 기대 규칙이 잘못됨')
    overrides = {}
    case_path = resolve_file(cases_folder, case['id'])
    for file in case['files']:
      name = unicodedata.normalize('NFC', file)
      if name not in original:
        raise ValueError(f'{case["id"]}: 원본에 없는 변형 문서: {file}')
      overrides[name] = parse_docx(resolve_file(case_path, file))
    changed = all(blocks != original[name] for name, blocks in overrides.items())
    items.append(
      dict(
        input=dict(
          id=case['id'],
          files=case['files'],
          blocks=[block for name, blocks in original.items() for block in overrides.get(name, blocks)],
        ),
        expected_output=case['expect'],
        metadata=dict(
          model=folder.name, changed=changed, baseline_issues=len(baseline), uncovered_rules=len(uncovered)
        ),
      )
    )

  def task(*, item: dict, **kwargs: Any) -> dict:
    issues = validate(extract(item['input']['blocks']))
    fresh = [i for i in issues if (i['rule'], i['message']) not in baseline_keys]
    found = {i['rule'] for i in fresh}
    return dict(
      id=item['input']['id'],
      changed=item['metadata']['changed'],
      expected=item['expected_output'],
      caught=item['metadata']['changed'] and set(item['expected_output']).issubset(found),
      issues=fresh,
    )

  results = run_items(f'golden-set-validation/{folder.name}', items, task, validation_scores, client)
  return dict(baseline=baseline, cases=results, uncovered=uncovered)


def main(args: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description='오류 주입 사례 R01–R17 검증 (원본 기준선도 오류가 없어야 통과)')
  parser.add_argument('models', nargs='*')
  parser.add_argument('--data', type=Path, default=DATA)
  parser.add_argument('--detail', action='store_true')
  parser.add_argument('--output', type=Path, default=DATA.parent / 'reports' / 'wrong_report.json')
  parser.add_argument('--langfuse', action='store_true', help='Langfuse에 오답 사례별 기대 규칙·검출 결과를 기록')
  options = parser.parse_args(args)
  models = options.models or [p.name.split('(', 1)[0] for p in model_folders(options.data)]
  if not models:
    raise ValueError('평가할 모델이 없음')
  report = {}
  with tracking(options.langfuse) as client:
    for model in models:
      result = check_model(model_folder(options.data, model), options.data / 'wrong_set' / model, client=client)
      report[model] = result
      caught = sum(c['caught'] for c in result['cases'])
      print(f'{model}: 원본 알림 {len(result["baseline"])}건 · {caught}/{len(result["cases"])}개 검출')
      for case in result['cases']:
        if options.detail or not case['caught']:
          print(f'  {case["id"]}: {"검출" if case["caught"] else "실패"} {case["issues"]}')
  options.output.parent.mkdir(parents=True, exist_ok=True)
  options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
  failed = any(r['baseline'] or r['uncovered'] or any(not c['caught'] for c in r['cases']) for r in report.values())
  print(
    f'전체 {sum(sum(c["caught"] for c in r["cases"]) for r in report.values())}/'
    f'{sum(len(r["cases"]) for r in report.values())}개 검출 · 보고서: {options.output}'
  )
  return int(failed)


if __name__ == '__main__':
  try:
    raise SystemExit(main())
  except Exception as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1) from error
