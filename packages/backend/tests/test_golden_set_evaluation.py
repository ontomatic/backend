import hashlib
import json
import shutil
import subprocess
import sys
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from docx import Document

from evals.golden_set.extractor import eval as evaluation
from evals.golden_set.extractor.check_wrong import check_model
from evals.golden_set.extractor.eval import compare, evaluate, summarize
from evals.golden_set.extractor.extract import extract
from evals.golden_set.extractor.files import DATA, resolve_file
from evals.golden_set.extractor.parser import parse_docx
from evals.golden_set.extractor.validate import validate
from evals.golden_set.generator.build_cgs import generate

ROOT = DATA.parents[2]
GOLDEN = {
  'file': 'sample.docx',
  'scope': 'document',
  'model': 'LO-TEST',
  'status': 'draft',
  'match': {'parts': ['name']},
  'src': {},
  'absent': [],
  'expected': {'parts': [{'name': '렌즈', 'qtyPerUnit': 1}]},
}


def run_cli(module: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    [sys.executable, '-m', module, *map(str, args)], cwd=ROOT, capture_output=True, text=True, check=False
  )


def hashes(folder: Path) -> dict[str, str]:
  return {
    str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()
  }


def test_duplicate_outputs_are_counted_even_when_a_correct_copy_follows() -> None:
  # Given a wrong duplicate before a correct part, when scoring, then the duplicate is an extra.
  actual = {'parts': [{'name': '렌즈', 'qtyPerUnit': 0}, {'name': '렌즈', 'qtyPerUnit': 1}]}
  assert len(compare('sample', GOLDEN, actual)['extras']) == 1
  duplicate = deepcopy(GOLDEN)
  duplicate['expected']['parts'] *= 2
  with pytest.raises(ValueError, match='중복'):
    compare('sample', duplicate, actual)


def test_unicode_filename_resolution_does_not_rename_data(tmp_path: Path) -> None:
  # Given an NFD filename, when an NFC reference is resolved, then the original stays unchanged.
  original = tmp_path / unicodedata.normalize('NFD', '제품사양서.docx')
  original.write_bytes(b'keep this file')
  before = hashes(tmp_path)
  assert resolve_file(tmp_path, unicodedata.normalize('NFC', original.name)).read_bytes() == b'keep this file'
  assert hashes(tmp_path) == before


def test_golden_adapter_keeps_backend_heading_and_merged_cell_semantics(tmp_path: Path) -> None:
  # Given a repeated body label and merged cells, when adapted, then backend block semantics are retained.
  document = Document()
  document.add_heading('제품사양서', 1)
  document.add_paragraph('제품사양서')
  table = document.add_table(rows=2, cols=2)
  table.cell(0, 0).merge(table.cell(0, 1)).text = '묶음'
  table.cell(1, 0).text = '부품'
  table.cell(1, 1).text = '렌즈'
  file = tmp_path / 'merged.docx'
  document.save(file)
  blocks = parse_docx(file)
  assert blocks[:2] == [{'t': 'h', 'level': 1, 'text': '제품사양서'}, {'t': 'p', 'text': '제품사양서'}]
  assert blocks[2]['rows'] == [['묶음', '묶음'], ['부품', '렌즈']]


def test_cli_fails_for_empty_data_and_scoring_errors(tmp_path: Path) -> None:
  # Given an empty dataset or a wrong expected model, when evaluating, then the CLI exits with 1.
  report = tmp_path / 'report.json'
  empty = run_cli('evals.golden_set.extractor.eval', tmp_path, '--output', report)
  assert empty.returncode == 1
  source = resolve_file(DATA / 'LO-D100', '01_제품사양서.docx')
  shutil.copyfile(source, tmp_path / 'sample.docx')
  wrong = {**GOLDEN, 'expected': {'model': 'LO-WRONG', 'parts': []}}
  (tmp_path / 'sample.golden.json').write_text(json.dumps(wrong), encoding='utf-8')
  failed = run_cli('evals.golden_set.extractor.eval', tmp_path, '--output', report)
  assert failed.returncode == 1
  assert json.loads(report.read_text())['totals']['document']['wrong'] > 0


@pytest.mark.parametrize('extractor', ['rules', 'llm'])
@pytest.mark.parametrize('explicit_output', [False, True])
def test_cli_report_paths_preserve_previous_runs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extractor: str, explicit_output: bool
) -> None:
  # Given an existing report, when running twice, then defaults create dated reports and explicit output is reused.
  report_name = 'llm_eval_report.json' if extractor == 'llm' else 'eval_report.json'
  previous = tmp_path / report_name
  previous.write_text('previous report', encoding='utf-8')
  monkeypatch.setattr(evaluation, 'REPORT', tmp_path / 'eval_report.json')
  monkeypatch.setattr(
    evaluation,
    'evaluate',
    lambda *args, **kwargs: {scope: dict(rows=[], extras=[]) for scope in ('document', 'model')},
  )
  args = [str(tmp_path), '--extractor', extractor]
  if explicit_output:
    args.extend(['--output', str(previous)])

  for _ in range(2):
    assert evaluation.main(args) == 0

  reports = sorted(tmp_path.glob('*.json'))
  if explicit_output:
    assert reports == [previous]
    assert str(tmp_path) in json.loads(previous.read_text())['models']
  else:
    assert previous.read_text() == 'previous report'
    assert len(reports) == 3
    for report in reports:
      if report != previous:
        datetime.strptime(report.name.removesuffix(f'_{report_name}'), '%Y%m%d_%H%M%S_%f')
        assert str(tmp_path) in json.loads(report.read_text())['models']


@pytest.mark.parametrize('model', ['LO-D100', 'LO-F35', 'LO-I100', 'LO-T400'])
def test_original_documents_and_wrong_cases_are_preserved_and_pass(model: str) -> None:
  # Given the saved fixtures, when both evaluations run, then all answers match without data writes.
  folder = DATA / model
  before = hashes(folder)
  result = evaluate(folder)
  for scope in ('document', 'model'):
    stats = summarize(**result[scope])
    assert stats['fields'] > 0 and stats['accuracy'] == 1
    assert stats['extras'] == 0
  wrong = check_model(folder, DATA / 'wrong_set' / model)
  assert wrong['baseline'] == []
  assert wrong['uncovered'] == []
  assert len(wrong['cases']) == 26 and all(case['caught'] for case in wrong['cases'])
  assert hashes(folder) == before


def test_wrong_cli_fails_for_unchanged_mutation(tmp_path: Path) -> None:
  # Given a case that is actually unchanged, when checking errors, then the CLI fails.
  shutil.copytree(DATA / 'LO-D100', tmp_path / 'LO-D100')
  target = tmp_path / 'wrong_set' / 'LO-D100'
  shutil.copytree(DATA / 'wrong_set' / 'LO-D100', target)
  case = json.loads((target / 'cases.json').read_text())['cases'][0]
  shutil.copyfile(
    resolve_file(tmp_path / 'LO-D100', case['files'][0]), resolve_file(target / case['id'], case['files'][0])
  )
  result = run_cli('evals.golden_set.extractor.check_wrong', '--data', tmp_path, '--output', tmp_path / 'report.json')
  assert result.returncode == 1
  assert '25/26' in result.stdout


def test_validator_detects_cycles_and_invalid_calendar_dates() -> None:
  # Given a cycle and a nonexistent date, when validating, then neither is accepted as normal.
  data = extract([block for file in sorted((DATA / 'LO-D100').glob('*.docx')) for block in parse_docx(file)])
  data['tasks'][0]['preds'] = [data['tasks'][-1]['id']]
  data['tasks'][0]['start'] = '2026-02-30'
  issues = validate(data)
  assert any(i['rule'] == 'R10' and '순환' in i['message'] for i in issues)
  assert any(i['rule'] == 'R05' for i in issues)


@pytest.mark.parametrize(
  'model,source', [('LO-D100', 'd100'), ('LO-T400', 't400'), ('LO-F35', 'f35'), ('LO-I100', 'i100')]
)
def test_python_document_generation_matches_existing_answers(tmp_path: Path, model: str, source: str) -> None:
  # Given the same model inputs, when Python generates documents, then existing answers still match.
  folder = tmp_path / model
  generate(folder, DATA.parent / 'generator' / f'{source}.json', split=True)
  for golden in (DATA / model).glob('*.golden.json'):
    shutil.copyfile(golden, folder / golden.name)
  result = evaluate(folder)
  assert all(summarize(**result[scope])['accuracy'] == 1 for scope in ('document', 'model'))
  with pytest.raises(FileExistsError):
    generate(folder, DATA.parent / 'generator' / f'{source}.json', split=True)
