import asyncio
import json
import shutil
from collections.abc import Iterator
from inspect import isawaitable
from pathlib import Path
from typing import Any

import pytest
from backend.core.config import Settings, get_settings
from langfuse.experiment import EvaluatorFunction, ExperimentItemResult, ExperimentResult, TaskFunction

from evals.golden_set.extractor import check_wrong
from evals.golden_set.extractor import eval as evaluation
from evals.golden_set.extractor.files import DATA, resolve_file

from .test_golden_set_llm import RecordingModel, sample


class RecordingLangfuse:
  def __init__(self) -> None:
    self.runs: list[ExperimentResult] = []
    self.closed = False

  def auth_check(self) -> bool:
    return True

  def run_experiment(
    self, *, name: str, data: list[dict], task: TaskFunction, evaluators: list[EvaluatorFunction], **kwargs: Any
  ) -> ExperimentResult:
    results = []
    for item in data:
      output = task(item=item)
      if isawaitable(output):
        output = asyncio.run(output)
      scores = []
      for evaluator in evaluators:
        scores.extend(
          evaluator(
            input=item['input'],
            output=output,
            expected_output=item.get('expected_output'),
            metadata=item.get('metadata'),
          )
        )
      results.append(ExperimentItemResult(item=item, output=output, evaluations=scores, trace_id='test-trace'))
    result = ExperimentResult(
      name=name,
      run_name='test-run',
      description=None,
      item_results=results,
      run_evaluations=[],
      experiment_id='test-run',
    )
    self.runs.append(result)
    return result

  def shutdown(self) -> None:
    self.closed = True


@pytest.fixture
def langfuse(monkeypatch: pytest.MonkeyPatch, api_settings: Settings) -> Iterator[RecordingLangfuse]:
  client = RecordingLangfuse()
  monkeypatch.setenv('LANGFUSE_ENABLED', 'true')
  monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'test-public')
  monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'test-secret')
  monkeypatch.setattr('backend.integrations.langfuse.Langfuse', lambda **kwargs: client)
  get_settings.cache_clear()
  try:
    yield client
  finally:
    get_settings.cache_clear()


def test_eval_tracks_document_and_combined_answers(tmp_path: Path, langfuse: RecordingLangfuse) -> None:
  # Given real golden documents, when tracing the CLI, then every answer and score reaches Langfuse.
  code = evaluation.main([str(DATA / 'LO-D100'), '--langfuse', '--output', str(tmp_path / 'report.json')])
  assert code == 0
  assert len(langfuse.runs) == 1
  results = langfuse.runs[0].item_results
  assert len(results) == 11
  assert sum(r.item['metadata']['scope'] == 'document' for r in results) == 10
  assert sum(r.item['metadata']['scope'] == 'model' for r in results) == 1
  for result in results:
    assert result.item['expected_output']
    assert result.item['input']['blocks']
    assert result.item['metadata']['status'] == 'draft'
    assert result.output['actual']
    scores = {score.name: score.value for score in result.evaluations}
    assert scores['accuracy'] == 1
    assert scores['wrong'] == scores['missing'] == scores['extras'] == 0
  assert langfuse.closed
  combined = next(r for r in results if r.item['metadata']['scope'] == 'model')
  assert combined.output['actual']['model'] == 'LO-D100'


def test_traced_scoring_failure_still_fails_the_cli(tmp_path: Path, langfuse: RecordingLangfuse) -> None:
  # Given a wrong answer, when tracing evaluation, then the wrong value is recorded and the CLI still fails.
  shutil.copyfile(resolve_file(DATA / 'LO-D100', '01_제품사양서.docx'), tmp_path / 'sample.docx')
  golden = dict(
    file='sample.docx',
    scope='document',
    model='LO-D100',
    status='draft',
    match={},
    src={},
    expected={'model': 'LO-WRONG'},
  )
  (tmp_path / 'sample.golden.json').write_text(json.dumps(golden), encoding='utf-8')
  report = tmp_path / 'report.json'
  assert evaluation.main([str(tmp_path), '--langfuse', '--output', str(report)]) == 1
  result = langfuse.runs[0].item_results[0]
  assert result.item['expected_output'] == {'model': 'LO-WRONG'}
  assert result.output['actual']['model'] == 'LO-D100'
  assert {score.name: score.value for score in result.evaluations}['wrong'] == 1
  assert json.loads(report.read_text())['totals']['document']['accuracy'] == 0
  assert langfuse.closed


def test_undetected_mutation_is_recorded_as_failure(tmp_path: Path, langfuse: RecordingLangfuse) -> None:
  # Given an unchanged mutation, when tracing validation, then its failed detection is recorded.
  shutil.copytree(DATA / 'LO-D100', tmp_path / 'LO-D100')
  cases_folder = tmp_path / 'wrong_set' / 'LO-D100'
  shutil.copytree(DATA / 'wrong_set' / 'LO-D100', cases_folder)
  case = json.loads((cases_folder / 'cases.json').read_text())['cases'][0]
  shutil.copyfile(
    resolve_file(tmp_path / 'LO-D100', case['files'][0]), resolve_file(cases_folder / case['id'], case['files'][0])
  )
  code = check_wrong.main(['LO-D100', '--data', str(tmp_path), '--langfuse', '--output', str(tmp_path / 'wrong.json')])
  assert code == 1
  result = next(r for r in langfuse.runs[0].item_results if r.output['id'] == case['id'])
  assert {score.name: score.value for score in result.evaluations}['detected'] == 0
  assert langfuse.closed


@pytest.mark.parametrize('module,args', [(evaluation, [str(DATA / 'LO-D100')]), (check_wrong, ['LO-D100'])])
def test_without_flag_evaluation_never_connects(
  tmp_path: Path,
  langfuse: RecordingLangfuse,
  module: Any,
  args: list[str],
) -> None:
  # Given enabled backend tracing, when the CLI flag is absent, then evaluation stays offline.
  assert module.main([*args, '--output', str(tmp_path / 'report.json')]) == 0
  assert langfuse.runs == []
  assert not langfuse.closed


def test_explicit_tracing_rejects_disabled_configuration(
  tmp_path: Path,
  langfuse: RecordingLangfuse,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  # Given disabled tracing, when explicitly requested, then the CLI reports the configuration error.
  monkeypatch.setenv('LANGFUSE_ENABLED', 'false')
  get_settings.cache_clear()
  with pytest.raises(ValueError, match='LANGFUSE_ENABLED'):
    evaluation.main([str(DATA / 'LO-D100'), '--langfuse', '--output', str(tmp_path / 'report.json')])
  assert langfuse.runs == []


@pytest.mark.parametrize('failure', ['task', 'evaluator'])
def test_sdk_failures_cannot_produce_a_successful_report(
  tmp_path: Path,
  langfuse: RecordingLangfuse,
  monkeypatch: pytest.MonkeyPatch,
  failure: str,
) -> None:
  # Given a swallowed SDK failure, when evaluating, then it raises and closes the client without a success report.
  run_experiment = langfuse.run_experiment

  def failed_experiment(**kwargs: Any) -> ExperimentResult:
    result = run_experiment(**kwargs)
    if failure == 'task':
      result.item_results.pop()
    else:
      result.item_results[0].evaluations.clear()
    return result

  monkeypatch.setattr(langfuse, 'run_experiment', failed_experiment)
  report = tmp_path / 'report.json'
  with pytest.raises(RuntimeError, match='추출 또는 채점'):
    evaluation.main([str(DATA / 'LO-D100'), '--langfuse', '--output', str(report)])
  assert langfuse.closed
  assert not report.exists()


def test_wrong_cases_track_detection_and_validation_issues(tmp_path: Path, langfuse: RecordingLangfuse) -> None:
  # Given injected errors, when tracing validation, then each case retains its expected rules and issues.
  code = check_wrong.main(['LO-D100', '--langfuse', '--output', str(tmp_path / 'wrong.json')])
  assert code == 0
  assert len(langfuse.runs) == 1
  results = langfuse.runs[0].item_results
  assert len(results) == 26
  for result in results:
    assert result.item['expected_output']
    assert result.item['input']['blocks']
    assert result.output['issues']
    scores = {score.name: score.value for score in result.evaluations}
    assert scores['detected'] == 1
    assert scores['baseline_issues'] == scores['uncovered_rules'] == 0
  assert langfuse.closed


def test_llm_answers_and_model_metadata_are_traced(
  tmp_path: Path,
  langfuse: RecordingLangfuse,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  # Given LLM extraction with tracing, when evaluating, then results, scores and generation callbacks are connected.
  sample(tmp_path)
  model = RecordingModel()
  monkeypatch.setattr('backend.integrations.llm.factory.ChatOllama', lambda **kwargs: model)
  monkeypatch.setattr('backend.integrations.llm.chat.CallbackHandler', lambda: object())
  assert (
    evaluation.main([str(tmp_path), '--extractor', 'llm', '--langfuse', '--output', str(tmp_path / 'report.json')]) == 1
  )
  assert len(model.calls) == 2
  run = langfuse.runs[0]
  assert run.name == f'golden-set-llm/{tmp_path.name}'
  for result in run.item_results:
    assert result.item['metadata']['extractor'] == 'llm'
    assert result.item['metadata']['llm_provider'] == 'ollama'
    assert result.item['metadata']['llm_model']
    assert result.output['actual']['model'] == 'LLM-RESULT'
    assert {score.name: score.value for score in result.evaluations}['accuracy'] == 0
  assert langfuse.closed


@pytest.mark.parametrize('traced', [False, True])
@pytest.mark.parametrize('fails', [False, True])
def test_llm_progress_is_visible_while_running_and_when_finished(
  tmp_path: Path,
  langfuse: RecordingLangfuse,
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
  traced: bool,
  fails: bool,
) -> None:
  # Given a pending LLM call, when evaluating, then progress appears before the response and after success or failure.
  sample(tmp_path)
  model = RecordingModel()
  invoke = model.ainvoke
  observed = []

  async def respond(*args: Any, **kwargs: Any) -> Any:
    observed.append(capsys.readouterr().err)
    if fails:
      raise ValueError('LLM test failed')
    return await invoke(*args, **kwargs)

  monkeypatch.setattr(model, 'ainvoke', respond)
  monkeypatch.setattr('backend.integrations.llm.factory.ChatOllama', lambda **kwargs: model)
  monkeypatch.setattr('backend.integrations.llm.chat.CallbackHandler', lambda: object())
  report = tmp_path / 'report.json'
  args = [str(tmp_path), '--extractor', 'llm', '--output', str(report)]
  if traced:
    args.append('--langfuse')
  if fails:
    with pytest.raises(ValueError, match='LLM test failed'):
      evaluation.main(args)
  else:
    assert evaluation.main(args) == 1
  observed.append(capsys.readouterr().err)
  prefix = f'[golden-set-llm/{tmp_path.name}]'
  assert f'{prefix} [1/2] 시작: sample.docx' in observed[0]
  if fails:
    assert f'{prefix} [1/2] 실패: sample.docx' in observed[-1]
    assert '완료:' not in observed[-1]
    assert not report.exists()
  else:
    assert f'{prefix} [1/2] 완료: sample.docx' in observed[1]
    assert f'{prefix} [2/2] 시작: TEST 합본' in observed[1]
    assert f'{prefix} [2/2] 완료: TEST 합본' in observed[2]
