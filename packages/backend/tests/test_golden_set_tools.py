import importlib.util
import json
import sys
import unicodedata
from pathlib import Path
from types import ModuleType

import pytest

GENERATOR = Path(__file__).resolve().parents[3] / 'evals' / 'golden_set' / 'generator'


def load_generator(name: str) -> ModuleType:
  spec = importlib.util.spec_from_file_location(name, GENERATOR / f'{name}.py')
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_wrong_set_never_deletes_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given existing cases, when regeneration is requested, then it refuses without changing them.
  module = load_generator('make_wrong_set')
  target = tmp_path / 'wrong_set'
  target.mkdir()
  sentinel = target / 'existing.docx'
  sentinel.write_bytes(b'keep this case')
  monkeypatch.setattr(module, 'OUT', str(target))
  monkeypatch.setattr(module, 'DATA', str(tmp_path / 'missing-input'))
  monkeypatch.setattr(sys, 'argv', ['make_wrong_set.py'])
  with pytest.raises(SystemExit):
    module.main()
  assert sentinel.read_bytes() == b'keep this case'


def test_failed_wrong_generation_does_not_publish_partial_output(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given a failure after a first model, when generating, then the destination stays unpublished.
  module = load_generator('make_wrong_set')
  target = tmp_path / 'new-cases'
  monkeypatch.setattr(module, 'OUT', str(target))
  monkeypatch.setattr(sys, 'argv', ['make_wrong_set.py'])
  monkeypatch.setattr(module, 'MODELS', ['LO-D100', 'LO-MISSING'])
  with pytest.raises(SystemExit):
    module.main()
  assert not target.exists()


def test_model_folder_accepts_current_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given the current model layout, when looking up a model, then generation finds that folder.
  module = load_generator('make_golden')
  (tmp_path / 'LO-D100').mkdir()
  monkeypatch.setattr(module, 'DATA', str(tmp_path))
  assert Path(module.model_folder('LO-D100')) == tmp_path / 'LO-D100'


def test_golden_generation_writes_only_document_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given model inputs, when generating goldens, then each document gets one answer and no model answer is created.
  module = load_generator('make_golden')
  folder = tmp_path / 'LO-D100'
  folder.mkdir()
  originals = list((GENERATOR.parent / 'data' / folder.name).glob('*.docx'))
  for file in originals:
    (folder / file.name).touch()
  monkeypatch.setattr(module, 'DATA', str(tmp_path))
  monkeypatch.setattr(sys, 'argv', ['make_golden.py', 'd100.json'])

  module.main()

  answers = list(folder.glob('*.golden.json'))
  assert len(answers) == len(originals) == 10
  assert all(json.loads(file.read_text())['scope'] == 'document' for file in answers)


def test_golden_check_preserves_unicode_filename_and_review_metadata(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given a reviewed NFD file, when checking an NFC reference, then its bytes and metadata stay intact.
  module = load_generator('make_golden')
  target = tmp_path / unicodedata.normalize('NFD', '제품사양서.golden.json')
  body = dict(expected={'model': 'LO-D100'}, match={}, absent=[], src={})
  saved = {**body, 'status': 'reviewed', 'reviewed_by': 'reviewer', 'notes': 'keep these notes'}
  content = json.dumps(saved, ensure_ascii=False).encode()
  target.write_bytes(content)
  monkeypatch.setattr(sys, 'argv', ['make_golden.py', '--check'])
  module.write(tmp_path / unicodedata.normalize('NFC', target.name), body, False)
  assert target.read_bytes() == content
