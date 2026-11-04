import argparse
import json
import sys
from collections import Counter
from functools import partial
from pathlib import Path
from typing import Any, Literal

from backend.core.config import get_settings
from backend.core.utils import utc_now
from backend.integrations.llm.factory import create_llm
from backend.integrations.llm.interface import LLM
from langfuse import Evaluation, Langfuse

from .extract import extract
from .files import model_folders, resolve_file
from .llm import OUTPUT_SCHEMA, extract_llm
from .parser import parse_docx
from .tracking import run_items, tracking

SCALARS = ('model', 'productName', 'specVersion', 'plannedQty', 'completedQty')
REPORT = Path(__file__).resolve().parents[1] / 'reports' / 'eval_report.json'


def canonical(value: Any) -> str:
  return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def compare(file: str, golden: dict, actual: dict) -> dict:
  rows, extras = [], []

  def record(field: str, want: Any, got: Any, tag: str, *, missing: bool = False) -> None:
    verdict = '맞음' if canonical(want) == canonical(got) else '빠짐' if got in (None, '', [], {}) else '틀림'
    rows.append(dict(file=file, path=field, tag=tag, verdict='빠짐' if missing else verdict, want=want, got=got))

  expected, source = golden['expected'], golden['src']
  for field in SCALARS:
    if field in expected:
      record(field, expected[field], actual.get(field), source.get(field, '?'))
  for array, fields in golden['match'].items():
    want, got = expected.get(array, []), actual.get(array, [])
    if not isinstance(want, list) or not isinstance(got, list) or not fields:
      raise ValueError(f'{file}: 잘못된 배열 또는 매칭 키: {array}')

    def key_of(item: dict, fields: list[str] = fields) -> str:
      return '|'.join(str(item[field]) for field in fields)

    wanted_keys = [key_of(item) for item in want]
    if len(set(wanted_keys)) != len(wanted_keys):
      raise ValueError(f'{file}: 정답 {array} 키 중복')
    by_key = {}
    for item in got:
      key = key_of(item)
      if key in by_key:
        extras.append(dict(file=file, arr=array, key=key, reason='중복'))
      by_key[key] = item
    for item in want:
      key = key_of(item)
      hit = by_key.get(key)
      for field, value in item.items():
        prefix = f'{array}[{key}].{field}'
        if field == 'meta' and isinstance(value, dict):
          for name, v in value.items():
            tag = source.get(f'{prefix}.{name}', source.get(f'{array}[].meta.{name}', '?'))
            record(f'{prefix}.{name}', v, hit.get('meta', {}).get(name) if hit else None, tag, missing=hit is None)
        else:
          tag = source.get(prefix, source.get(f'{array}[].{field}', source.get(field, '?')))
          record(prefix, value, hit.get(field) if hit else None, tag, missing=hit is None)
    extras.extend(dict(file=file, arr=array, key=key, reason='정답에 없음') for key in by_key if key not in wanted_keys)
  return dict(rows=rows, extras=extras)


def summarize(rows: list[dict], extras: list[dict]) -> dict:
  counts = Counter(row['verdict'] for row in rows)
  return dict(
    fields=len(rows),
    correct=counts['맞음'],
    wrong=counts['틀림'],
    missing=counts['빠짐'],
    extras=len(extras),
    accuracy=counts['맞음'] / len(rows) if rows else None,
  )


async def extraction_task(*, item: dict, llm: LLM | None = None, **kwargs: Any) -> dict:
  metadata = item['metadata']
  name = item['input']['files'][0]
  actual = await extract_llm(llm, item['input']['blocks']) if llm is not None else extract(item['input']['blocks'])
  compared = compare(name, dict(expected=item['expected_output'], **metadata), actual)
  return dict(actual=actual, **compared)


def extraction_scores(*, output: dict, **kwargs: Any) -> list[Evaluation]:
  stats = summarize(output['rows'], output['extras'])
  return [Evaluation(name=name, value=value) for name, value in stats.items() if value is not None]


def evaluate(folder: Path, *, client: Langfuse | None = None, extractor: Literal['rules', 'llm'] = 'rules') -> dict:
  goldens = sorted(folder.glob('*.golden.json'))
  if not goldens:
    raise ValueError(f'{folder}: 정답 파일이 없음')
  result = {'document': dict(rows=[], extras=[])}
  names, items = set(), []
  statuses = Counter()
  metadata = {'extractor': extractor}
  llm = None
  if extractor == 'llm':
    settings = get_settings()
    metadata.update(llm_provider=settings.llm_provider, llm_model=settings.llm_model)
    llm = create_llm(output_schema=OUTPUT_SCHEMA)

  for file in goldens:
    golden = json.loads(file.read_text(encoding='utf-8'))
    statuses[golden['status']] += 1
    if golden['scope'] != 'document':
      raise ValueError(f'{file}: 알 수 없는 평가 범위')
    name = golden['file']
    if name in names:
      raise ValueError(f'{folder}: 문서별 정답 중복: {name}')
    names.add(name)
    items.append(
      dict(
        input=dict(files=[name], blocks=parse_docx(resolve_file(folder, name))),
        expected_output=golden['expected'],
        metadata={**metadata, **{key: golden[key] for key in ('model', 'scope', 'status', 'match', 'src')}},
      )
    )
  name = f'golden-set-extraction/{folder.name}' if extractor == 'rules' else f'golden-set-llm/{folder.name}'
  outputs = run_items(name, items, partial(extraction_task, llm=llm), extraction_scores, client)
  for output in outputs:
    for key in ('rows', 'extras'):
      result['document'][key].extend(output[key])
  if not result['document']['rows']:
    raise ValueError(f'{folder}: 채점한 문서의 칸이 없음')
  result['statuses'] = dict(statuses)
  result['extractor'] = metadata
  return result


def print_summary(label: str, rows: list[dict], extras: list[dict]) -> None:
  stats = summarize(rows, extras)
  accuracy = f'{stats["accuracy"]:.1%}' if stats['accuracy'] is not None else '-'
  print(
    f'{label} 칸 {stats["fields"]}: 맞음 {stats["correct"]} · 틀림 {stats["wrong"]} · '
    f'빠짐 {stats["missing"]} → {accuracy} | 남음 항목 {stats["extras"]}'
  )


def main(args: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description='골든셋 문서별 추출 평가 (데이터는 읽기 전용)')
  parser.add_argument('folders', nargs='*', type=Path)
  parser.add_argument('--detail', action='store_true')
  parser.add_argument('--output', type=Path)
  parser.add_argument('--langfuse', action='store_true', help='Langfuse에 입력·정답·추출 결과와 점수를 기록')
  parser.add_argument('--extractor', choices=('rules', 'llm'), default='rules', help='추출 방식 (기본: rules)')
  options = parser.parse_args(args)
  if options.output is None:
    name = 'llm_eval_report.json' if options.extractor == 'llm' else REPORT.name
    options.output = REPORT.with_name(f'{utc_now():%Y%m%d_%H%M%S_%f}_{name}')
  models = options.folders or model_folders()
  if not models:
    raise ValueError('평가할 모델 폴더가 없음')
  report = {}
  totals = {'document': dict(rows=[], extras=[])}
  with tracking(options.langfuse) as client:
    for folder in models:
      result = evaluate(folder, client=client, extractor=options.extractor)
      report[str(folder)] = result
      print(f'\n===== {folder.name}')
      for scope in totals:
        print_summary(scope, **result[scope])
        for key in ('rows', 'extras'):
          totals[scope][key].extend(result[scope][key])
        if options.detail:
          for row in result[scope]['rows']:
            if row['verdict'] != '맞음':
              print(f'  {row["verdict"]} {row["file"]} {row["path"]}: {row["want"]!r} → {row["got"]!r}')
          for extra in result[scope]['extras']:
            print(f'  남음 {extra}')
  print('\n===== 전체')
  for scope, result in totals.items():
    print_summary(scope, **result)
  options.output.parent.mkdir(parents=True, exist_ok=True)
  options.output.write_text(
    json.dumps(
      dict(models=report, totals={scope: summarize(**result) for scope, result in totals.items()}),
      ensure_ascii=False,
      indent=2,
    )
    + '\n',
    encoding='utf-8',
  )
  print(f'보고서: {options.output}')
  return int(
    any(row['verdict'] != '맞음' for result in totals.values() for row in result['rows'])
    or any(result['extras'] for result in totals.values())
  )


if __name__ == '__main__':
  try:
    raise SystemExit(main())
  except Exception as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1) from error
