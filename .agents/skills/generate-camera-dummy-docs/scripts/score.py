"""Standard-library evaluator. python scripts/score.py --dataset-root DATASET predictions.json [--split test]

Prediction shape: see evaluation/reference_predictions.json. This reference is an
oracle to check evaluator wiring, NOT the output of an actual parser or LLM.
Use value_norm and unit_norm; units mm/W/g/degC are canonical.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path.cwd()


def load(p: str | Path) -> Any:
  return json.loads(Path(p).read_text(encoding='utf-8'))


def equal(a: Any, b: Any) -> bool:
  if isinstance(a, bool) or isinstance(b, bool):
    return type(a) is type(b) and a == b
  if isinstance(a, (int, float)) and isinstance(b, (int, float)):
    return math.isclose(a, b, rel_tol=1e-06, abs_tol=1e-06)
  return a == b


def ratio(a: int | float, b: int | float) -> float:
  return a / b if b else 0.0


def prf(truth: set[Any], pred: set[Any]) -> dict[str, Any]:
  tp = len(truth & pred)
  pre = ratio(tp, len(pred))
  rec = ratio(tp, len(truth))
  return {
    'precision': pre,
    'recall': rec,
    'f1': ratio(2 * pre * rec, pre + rec),
    'true_positive': tp,
    'expected': len(truth),
    'predicted': len(pred),
  }


def score(pred: dict[str, Any], split: str | None = None) -> dict[str, Any]:
  splits = load(ROOT / 'evaluation/splits.json')['products']
  allowed = {p for p, s in splits.items() if split is None or s == split}
  gold = {
    g['document_id']: g for p in (ROOT / 'gold/documents').glob('*.json') if (g := load(p))['product_id'] in allowed
  }
  docs = pred.get('documents', {})
  nfields = correct = class_ok = present = present_ok = absent = absent_ok = hall = nonnull = 0
  for did, g in gold.items():
    d = docs.get(did, {})
    class_ok += d.get('class_id') == g['class_id']
    fields = d.get('fields', {})
    for k, v in g['fields'].items():
      nfields += 1
      x = fields.get(k, {})
      exists = k in fields
      ok = exists and equal(x.get('value_norm'), v['value_norm']) and (x.get('unit_norm') == v['unit_norm'])
      correct += ok
      if v['value_norm'] is None:
        absent += 1
        absent_ok += ok
      else:
        present += 1
        present_ok += ok
    for k, v in fields.items():
      if v.get('value_norm') is not None:
        nonnull += 1
        if k not in g['fields'] or g['fields'][k]['value_norm'] is None:
          hall += 1
  known_all = {p.stem for p in (ROOT / 'gold/documents').glob('*.json')}
  for did, d in docs.items():
    if did not in known_all:
      nn = sum(x.get('value_norm') is not None for x in d.get('fields', {}).values())
      nonnull += nn
      hall += nn
  pairs = [p for p in load(ROOT / 'gold/pairs.json') if p['product_a'] in allowed and p['product_b'] in allowed]

  def pk(p: dict[str, Any]) -> tuple[str, str]:
    return tuple(sorted([p['product_a'], p['product_b']]))

  expected = {pk(p): p['label'] for p in pairs}
  predpairs = {
    pk(p): p['label'] for p in pred.get('pairs', []) if p['product_a'] in allowed and p['product_b'] in allowed
  }
  classes = {
    label: prf({k for k, v in expected.items() if v == label}, {k for k, v in predpairs.items() if v == label})
    for label in ['duplicate', 'similar', 'unrelated']
  }

  def ck(c: dict[str, Any]) -> tuple[str, ...]:
    return (c['product_id'], c['key'], *sorted([c['document_a'], c['document_b']]))

  ct = {ck(c) for c in load(ROOT / 'gold/conflicts.json') if c['product_id'] in allowed}
  cp = {ck(c) for c in pred.get('conflicts', []) if c['product_id'] in allowed}
  return {
    'split': split or 'all',
    'documents_expected': len(gold),
    'documents_submitted': len(set(docs) & set(gold)),
    'classification_accuracy': ratio(class_ok, len(gold)),
    'field_accuracy': ratio(correct, nfields),
    'present_field_accuracy': ratio(present_ok, present),
    'explicit_null_accuracy': ratio(absent_ok, absent),
    'hallucination_rate': ratio(hall, nonnull),
    'hallucination_count': hall,
    'field_count': nfields,
    'omitted_field_count': absent,
    'pair_accuracy': ratio(sum((predpairs.get(k) == v for k, v in expected.items())), len(expected)),
    'pair_macro_f1': sum(x['f1'] for x in classes.values()) / 3,
    'pair_per_class': classes,
    'conflict_detection': prf(ct, cp),
  }


if __name__ == '__main__':
  ap = argparse.ArgumentParser()
  ap.add_argument('predictions')
  ap.add_argument('--dataset-root', default='.', help='Dataset root or its metadata folder')
  ap.add_argument('--split', choices=['train', 'dev', 'test'])
  ap.add_argument('--output')
  a = ap.parse_args()
  ROOT = Path(a.dataset_root).resolve()
  ROOT = ROOT / '03_정답및평가자료' if (ROOT / '03_정답및평가자료').is_dir() else ROOT
  result = score(load(a.predictions), a.split)
  s = json.dumps(result, ensure_ascii=False, indent=2)
  print(s)
  if a.output:
    Path(a.output).write_text(s, encoding='utf-8')
