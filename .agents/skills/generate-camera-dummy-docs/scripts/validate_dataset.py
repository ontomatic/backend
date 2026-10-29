"""Standard-library structural validator; does not claim visual/content accuracy."""

import argparse
import collections
import csv
import json
import math
import zipfile
from pathlib import Path
from typing import Any


def read(path: Path) -> Any:
  return json.loads(path.read_text(encoding='utf-8'))


def metadata(root: Path) -> Path:
  return root / '03_정답및평가자료' if (root / '03_정답및평가자료').is_dir() else root


def validate(root: Path) -> dict[str, Any]:
  root = root.resolve()
  meta = metadata(root)
  errors = []
  counts = collections.Counter()
  files = set()
  products = {p.stem: read(p) for p in (meta / 'gold/products').glob('*.json')}
  docs = {p.stem: read(p) for p in (meta / 'gold/documents').glob('*.json')}
  manifest = read(root / 'manifest.json')
  seen = set()
  groups = collections.defaultdict(set)

  def fail(*v: Any) -> None:
    errors.append(list(v))

  for pid, p in products.items():
    if p.get('product_id') != pid:
      fail(pid, 'product filename/id mismatch')
    if not all(k in p for k in ['identity_id', 'family_id', 'source_id', 'variant_type', 'class_id', 'attributes']):
      fail(pid, 'product fields missing')
    if p.get('variant_type') not in ['base', 'duplicate', 'similar']:
      fail(pid, 'unknown variant type')
    if p.get('variant_type') != 'base' and p.get('parent_product_id') not in products:
      fail(pid, 'variant parent missing')
  for m in manifest:
    did = m['document_id']
    pid = m['product_id']
    g = docs.get(did)
    if did in seen:
      fail(did, 'duplicate manifest ID')
    seen.add(did)
    groups[pid].add(m.get('group'))
    counts['logical_documents'] += 1
    if pid not in products:
      fail(did, 'unknown product')
    if not g:
      fail(did, 'missing document gold')
      continue
    if g.get('document_id') != did or g.get('product_id') != pid:
      fail(did, 'gold ID mismatch')
    if g.get('class_id') != products.get(pid, {}).get('class_id'):
      fail(did, 'gold class mismatch')
    if set(m.get('files', {})) != {'pdf', 'xlsx', 'docx', 'csv'}:
      fail(did, 'requires four formats')
    for ext, rel in m.get('files', {}).items():
      path = (root / rel).resolve()
      if not path.is_relative_to(root):
        fail(did, ext, 'path escapes dataset')
        continue
      if path in files:
        fail(did, ext, 'file reused by different manifest entries')
      files.add(path)
      if not path.is_file():
        fail(did, ext, 'file missing')
        continue
      if path.suffix.lower() != '.' + ext:
        fail(did, ext, 'extension mismatch')
      counts[ext] += 1
      if ext == 'pdf' and (not path.read_bytes().startswith(b'%PDF-')):
        fail(did, ext, 'invalid PDF header')
      elif ext in ['xlsx', 'docx']:
        try:
          with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
              fail(did, ext, 'CRC failed')
            if ('xl/workbook.xml' if ext == 'xlsx' else 'word/document.xml') not in z.namelist():
              fail(did, ext, 'wrong Office package type')
        except zipfile.BadZipFile:
          fail(did, ext, 'invalid Office ZIP')
      elif ext == 'csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
          rows = list(csv.reader(f))
        if not rows or len(rows[0]) != 8:
          fail(did, 'CSV v2 requires eight columns')
        if any(len(r) != 8 for r in rows):
          fail(did, 'CSV inconsistent column count')
    for k, v in g.get('fields', {}).items():
      counts['gold_fields'] += 1
      if not all(
        key in v for key in ['value', 'unit', 'value_norm', 'unit_norm', 'quote', 'pdf_page', 'xlsx_cell', 'csv_row']
      ):
        fail(did, k, 'field contract incomplete')
        continue
      if v['value'] is None:
        counts['null_fields'] += 1
        if any(
          v.get(key) is not None
          for key in ['value_norm', 'unit', 'unit_norm', 'quote', 'pdf_page', 'xlsx_cell', 'csv_row']
        ):
          fail(did, k, 'omitted field carries value/evidence/location')
      else:
        if v['value_norm'] is None or v['quote'] is None:
          fail(did, k, 'present field has no normalized value/evidence')
        if not isinstance(v['pdf_page'], int) or v['pdf_page'] < 1:
          fail(did, k, 'invalid PDF page')
        if not v['xlsx_cell'] or not isinstance(v['csv_row'], int) or v['csv_row'] < 2:
          fail(did, k, 'missing cell/row location')
        if (
          isinstance(v['value'], (float, int))
          and (not isinstance(v['value'], bool))
          and (v.get('unit') in ['cm', 'mm', 'mW', 'W'])
        ):
          factor = {'cm': 10, 'mm': 1, 'mW': 0.001, 'W': 1}[v['unit']]
          base = {'cm': 'mm', 'mm': 'mm', 'mW': 'W', 'W': 'W'}[v['unit']]
          norm = v['value_norm']
          valid = isinstance(norm, (int, float)) and math.isclose(
            v['value'] * factor, norm, rel_tol=1e-06, abs_tol=1e-06
          )
          if not valid or v['unit_norm'] != base:
            fail(did, k, 'unit normalization mismatch')
    for k in g.get('omitted_fields', []):
      if k not in g.get('fields', {}) or g['fields'][k].get('value') is not None:
        fail(did, k, 'omission list mismatch')
  for pid in products:
    if groups[pid] != {1, 2, 3, 4, 5}:
      fail(pid, 'must have five document groups')
  if set(docs) != seen:
    fail('document gold/manifest coverage mismatch')
  identities = collections.defaultdict(list)
  for pid, p in products.items():
    identities[p.get('identity_id')].append(pid)
  for ids in identities.values():
    specs = [
      {k: v for k, v in products[pid]['attributes'].items() if k not in ['name', 'model', 'product_code']}
      for pid in ids
    ]
    if any(s != specs[0] for s in specs):
      fail(ids, 'duplicate identity has differing technical attributes')
  pairs = read(meta / 'gold/pairs.json')
  ps = set()
  for pair in pairs:
    a, b = (pair['product_a'], pair['product_b'])
    key = tuple(sorted([a, b]))
    if a == b or key in ps:
      fail(key, 'self/duplicate pair')
    ps.add(key)
    if a not in products or b not in products:
      fail(key, 'unknown pair product')
      continue
    expected = (
      'duplicate'
      if products[a]['identity_id'] == products[b]['identity_id']
      else 'similar'
      if products[a]['family_id'] == products[b]['family_id']
      else 'unrelated'
    )
    if pair['label'] != expected:
      fail(key, 'pair label/identity mismatch')
    counts[pair['label'] + '_pairs'] += 1
  if len(ps) != len(products) * (len(products) - 1) // 2:
    fail('pair coverage incomplete')
  splits = read(meta / 'evaluation/splits.json')['products']
  families = collections.defaultdict(set)
  for pid, p in products.items():
    if splits.get(pid) not in ['train', 'dev', 'test']:
      fail(pid, 'split missing/unknown')
    families[p['family_id']].add(splits.get(pid))
  if any(len(s) > 1 for s in families.values()):
    fail('family leakage across splits')
  conflicts = read(meta / 'gold/conflicts.json')
  for c in conflicts:
    a, b = (c['document_a'], c['document_b'])
    key = c['key']
    if a not in docs or b not in docs:
      fail(c, 'unknown conflict document')
      continue
    if docs[a]['product_id'] != c['product_id'] or docs[b]['product_id'] != c['product_id']:
      fail(c, 'conflict product mismatch')
    av = docs[a]['fields'].get(key, {})
    bv = docs[b]['fields'].get(key, {})
    if av.get('value_norm') == bv.get('value_norm') and av.get('unit_norm') == bv.get('unit_norm'):
      fail(c, 'conflict values are equal after normalization')
  counts['products'] = len(products)
  counts['conflicts'] = len(conflicts)
  return {
    'status': 'PASS' if not errors else 'FAIL',
    'counts': dict(counts),
    'errors': errors,
    'limits': (
      'Structure, containers, normalization and references only. '
      'Independently verify actual rendered values and layout.'
    ),
  }


if __name__ == '__main__':
  p = argparse.ArgumentParser()
  p.add_argument('dataset_root', type=Path)
  p.add_argument('--output', type=Path)
  a = p.parse_args()
  try:
    result = validate(a.dataset_root)
  except (KeyError, ValueError, OSError, TypeError) as e:
    result = {'status': 'FAIL', 'errors': [['unreadable dataset', str(e)]]}
  s = json.dumps(result, ensure_ascii=False, indent=2)
  print(s)
  if a.output:
    a.output.write_text(s, encoding='utf-8')
  raise SystemExit(0 if result['status'] == 'PASS' else 1)
