"""Exercise the portable skill tools using temporary structural fixtures."""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any


def load_tool(name: str) -> ModuleType:
  path = Path(__file__).resolve().parents[1] / 'scripts' / f'{name}.py'
  spec = importlib.util.spec_from_file_location(f'camera_skill_{name}', path)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


inventory = load_tool('inventory_sources')
validator = load_tool('validate_dataset')
scorer = load_tool('score')


def write_json(path: Path, value: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class SkillToolsTests(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.root = Path(self.temporary.name)
    self.meta = self.root / '03_정답및평가자료'
    self.manifest = []
    self.predictions: dict[str, Any] = {'documents': {}, 'pairs': [], 'conflicts': []}
    for index in [1, 2]:
      pid = f'P{index:03}'
      product = {
        'product_id': pid,
        'identity_id': 'I001',
        'family_id': 'F001',
        'source_id': 'S01',
        'variant_type': 'base' if index == 1 else 'duplicate',
        'class_id': 'network/dome',
        'attributes': {'model': f'SYN-{index}', 'power_w': 4.2},
      }
      if index == 2:
        product['parent_product_id'] = 'P001'
      write_json(self.meta / 'gold/products' / f'{pid}.json', product)
      for group in range(1, 6):
        did = f'{pid}-D{group}'
        files = {ext: f'documents/{did}.{ext}' for ext in ['pdf', 'xlsx', 'docx', 'csv']}
        for ext, relative in files.items():
          path = self.root / relative
          path.parent.mkdir(exist_ok=True)
          if ext == 'pdf':
            path.write_bytes(b'%PDF-1.7\n%%EOF\n')
          elif ext in ['xlsx', 'docx']:
            with zipfile.ZipFile(path, 'w') as archive:
              archive.writestr('xl/workbook.xml' if ext == 'xlsx' else 'word/document.xml', '<fixture/>')
          else:
            path.write_text('a,b,c,d,e,f,g,h\n1,2,3,4,power,4200,mW,8\n', encoding='utf-8-sig')
        fields = {
          'power_w': {
            'value': 4200,
            'unit': 'mW',
            'value_norm': 4.2,
            'unit_norm': 'W',
            'quote': '4200 mW',
            'pdf_page': 1,
            'xlsx_cell': 'B1',
            'csv_row': 2,
          },
          'weight_g': dict.fromkeys(
            ['value', 'unit', 'value_norm', 'unit_norm', 'quote', 'pdf_page', 'xlsx_cell', 'csv_row']
          ),
        }
        write_json(
          self.meta / 'gold/documents' / f'{did}.json',
          {
            'document_id': did,
            'product_id': pid,
            'class_id': 'network/dome',
            'omitted_fields': ['weight_g'],
            'fields': fields,
          },
        )
        self.manifest.append({'document_id': did, 'product_id': pid, 'group': group, 'files': files})
        self.predictions['documents'][did] = {
          'class_id': 'network/dome',
          'fields': {key: {k: v[k] for k in ['value_norm', 'unit_norm']} for key, v in fields.items()},
        }
    pair = {'product_a': 'P001', 'product_b': 'P002', 'label': 'duplicate'}
    self.predictions['pairs'] = [pair]
    write_json(self.root / 'manifest.json', self.manifest)
    write_json(self.meta / 'gold/pairs.json', [pair])
    write_json(self.meta / 'gold/conflicts.json', [])
    write_json(self.meta / 'evaluation/splits.json', {'products': {'P001': 'train', 'P002': 'train'}})
    old_root = scorer.ROOT
    self.addCleanup(setattr, scorer, 'ROOT', old_root)
    scorer.ROOT = self.meta

  def test_consistent_structure_passes(self) -> None:
    result = validator.validate(self.root)
    self.assertEqual(result['status'], 'PASS', result['errors'])
    self.assertEqual(result['counts']['logical_documents'], 10)

  def test_wrong_normalization_is_rejected(self) -> None:
    path = self.meta / 'gold/documents/P001-D1.json'
    gold = json.loads(path.read_text())
    gold['fields']['power_w']['value_norm'] = 4200
    write_json(path, gold)
    self.assertIn(['P001-D1', 'power_w', 'unit normalization mismatch'], validator.validate(self.root)['errors'])

  def test_family_split_leak_is_rejected(self) -> None:
    write_json(self.meta / 'evaluation/splits.json', {'products': {'P001': 'train', 'P002': 'test'}})
    self.assertIn(['family leakage across splits'], validator.validate(self.root)['errors'])

  def test_manifest_path_escape_is_rejected(self) -> None:
    self.manifest[0]['files']['pdf'] = '../outside.pdf'
    write_json(self.root / 'manifest.json', self.manifest)
    self.assertIn(['P001-D1', 'pdf', 'path escapes dataset'], validator.validate(self.root)['errors'])

  def test_source_zip_is_inventoried_without_guessing_class(self) -> None:
    path = self.root / 'input.zip'
    with zipfile.ZipFile(path, 'w') as archive:
      archive.writestr('sample.pdf', b'%PDF-1.7\n%%EOF\n')
    result = inventory.inventory(path)
    self.assertEqual(result['pdf_count'], 1)
    self.assertIsNone(result['files'][0]['classification'])

  def test_unsafe_source_zip_is_rejected(self) -> None:
    path = self.root / 'input.zip'
    with zipfile.ZipFile(path, 'w') as archive:
      archive.writestr('../sample.pdf', b'%PDF-1.7\n')
    with self.assertRaisesRegex(ValueError, 'Unsafe ZIP member path'):
      inventory.inventory(path)

  def test_empty_predictions_do_not_get_credit(self) -> None:
    result = scorer.score({})
    self.assertEqual(result['field_accuracy'], 0)
    self.assertEqual(result['classification_accuracy'], 0)

  def test_null_hallucination_and_wrong_unit_are_detected(self) -> None:
    perfect = scorer.score(self.predictions)
    self.assertEqual(perfect['field_accuracy'], 1)
    fields = self.predictions['documents']['P001-D1']['fields']
    fields['power_w']['unit_norm'] = 'mW'
    fields['weight_g'] = {'value_norm': 300, 'unit_norm': 'g'}
    result = scorer.score(self.predictions)
    self.assertLess(result['field_accuracy'], 1)
    self.assertEqual(result['hallucination_count'], 1)


if __name__ == '__main__':
  unittest.main()
