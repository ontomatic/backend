from copy import deepcopy

import pytest
from backend.exceptions.workflow import WorkflowError
from backend.schemas.workflow import JobIn, SpecificationIn
from backend.services.workflow import build_targets, normalize_value, validate_graph
from pydantic import ValidationError


def graph() -> dict:
  return {
    'root': 'CAM@1',
    'items': [
      {'key': 'CAM@1', 'code': 'CAM', 'name': '카메라', 'kind': 'product', 'version': 1, 'unit': '개'},
      {'key': 'LENS@1', 'code': 'LENS', 'name': '렌즈 모듈', 'kind': 'assembly', 'version': 1, 'unit': '개'},
      {'key': 'BODY@1', 'code': 'BODY', 'name': '바디', 'kind': 'assembly', 'version': 1, 'unit': '개'},
      {'key': 'SCREW@1', 'code': 'SCREW', 'name': '나사', 'kind': 'material', 'version': 1, 'unit': '개'},
    ],
    'relations': [
      {'parent': 'CAM@1', 'child': 'LENS@1', 'quantity': 1, 'condition': 'common'},
      {'parent': 'CAM@1', 'child': 'BODY@1', 'quantity': 1, 'condition': 'common'},
      {'parent': 'LENS@1', 'child': 'SCREW@1', 'quantity': 4, 'condition': 'J8'},
      {'parent': 'BODY@1', 'child': 'SCREW@1', 'quantity': 6, 'condition': 'J8'},
    ],
  }


def test_shared_material_quantities_are_aggregated_without_cross_job_state() -> None:
  # Given a shared material in two branches, when two jobs are created, then quantities aggregate independently.
  first = build_targets(graph(), 10)
  second = build_targets(graph(), 2)
  assert sum(target['quantity'] for target in first.values() if target['code'] == 'SCREW') == 100
  assert sum(target['quantity'] for target in second.values() if target['code'] == 'SCREW') == 20
  for target in first.values():
    target['status'] = 'passed'
  assert all(target['status'] == 'waiting' for target in second.values())


@pytest.mark.parametrize('value,unit', [(0.8, 'cm'), (8, 'mm'), (0.008, 'm')])
def test_length_normalization_preserves_equivalence(value: float, unit: str) -> None:
  assert normalize_value(value, unit) == (8, 'mm')


@pytest.mark.parametrize('failure', ['cycle', 'missing', 'quantity', 'self', 'duplicate'])
def test_invalid_bom_is_rejected(failure: str) -> None:
  # Given an invalid relationship, when validating a draft, then submission is blocked.
  data = deepcopy(graph())
  if failure == 'cycle':
    data['relations'].append({'parent': 'SCREW@1', 'child': 'CAM@1', 'quantity': 1})
  elif failure == 'missing':
    data['relations'][0]['child'] = 'UNKNOWN@1'
  elif failure == 'quantity':
    data['relations'][0]['quantity'] = 0
  elif failure == 'self':
    data['relations'][0]['child'] = 'CAM@1'
  else:
    data['items'].append(deepcopy(data['items'][0]))
  with pytest.raises(WorkflowError):
    validate_graph(data)


def test_selective_revision_keeps_material_versions_and_quantities_separate() -> None:
  # Given a shared screw, when only the lens branch changes version, then old and new quantities stay separate.
  baseline = graph()
  revision = {
    'root': 'CAM@2',
    'items': [
      baseline['items'][0] | {'key': 'CAM@2', 'version': 2},
      baseline['items'][1] | {'key': 'LENS@2', 'version': 2},
      baseline['items'][2],
      baseline['items'][3],
      baseline['items'][3] | {'key': 'SCREW@2', 'version': 2},
    ],
    'relations': [
      baseline['relations'][0] | {'parent': 'CAM@2', 'child': 'LENS@2'},
      baseline['relations'][1] | {'parent': 'CAM@2'},
      baseline['relations'][2] | {'parent': 'LENS@2', 'child': 'SCREW@2', 'condition': 'J10'},
      baseline['relations'][3],
    ],
  }

  first = build_targets(baseline, 1)
  second = build_targets(revision, 1)

  assert sum(t['quantity'] for t in first.values() if t['code'] == 'SCREW') == 10
  assert sum(t['quantity'] for t in second.values() if t['code'] == 'SCREW' and t['version'] == 1) == 6
  assert sum(t['quantity'] for t in second.values() if t['code'] == 'SCREW' and t['version'] == 2) == 4


def test_input_lengths_match_persisted_columns() -> None:
  with pytest.raises(ValidationError):
    SpecificationIn(code='C' * 81, name='카메라', product_type='digital', graph=graph())
  with pytest.raises(ValidationError):
    JobIn(specification_id='specification', name='생' * 151, quantity=1)
