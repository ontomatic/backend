import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from backend.core.config import Settings, get_settings
from docx import Document
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from evals.golden_set.extractor import eval as evaluation
from evals.golden_set.extractor.files import DATA
from evals.golden_set.extractor.llm import Extraction


class RecordingModel:
  def __init__(self) -> None:
    self.response = '{"model":"LLM-RESULT"}'
    self.calls: list[list[BaseMessage]] = []

  async def ainvoke(self, messages: list[BaseMessage], config: RunnableConfig) -> AIMessage:
    self.calls.append(messages)
    return AIMessage(content=self.response)


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch, api_settings: Settings) -> Iterator[RecordingModel]:
  model = RecordingModel()
  monkeypatch.setattr('backend.integrations.llm.factory.ChatOllama', lambda **kwargs: model)
  monkeypatch.setenv('LLM_PROVIDER', 'ollama')
  get_settings.cache_clear()
  try:
    yield model
  finally:
    get_settings.cache_clear()


def sample(folder: Path) -> None:
  document = Document()
  document.add_heading('원문 문서', 1)
  document.add_paragraph('모델명은 SOURCE-MODEL입니다.')
  document.save(folder / 'sample.docx')
  golden = dict(
    file='sample.docx',
    scope='document',
    model='TEST',
    status='draft',
    match={},
    src={},
    expected={'model': 'GOLDEN-ANSWER-CANARY'},
  )
  (folder / 'sample.golden.json').write_text(json.dumps(golden), encoding='utf-8')
  combined = {**golden, 'file': ['sample.docx'], 'scope': 'model'}
  (folder / 'combined.golden.json').write_text(json.dumps(combined), encoding='utf-8')


def test_llm_cli_scores_generated_output_without_leaking_answers(
  tmp_path: Path,
  ollama: RecordingModel,
) -> None:
  # Given an independent LLM answer, when evaluating it, then only source text reaches the model and it is scored.
  sample(tmp_path)
  report = tmp_path / 'llm-report.json'
  code = evaluation.main([str(tmp_path), '--extractor', 'llm', '--output', str(report)])
  assert code == 1
  assert len(ollama.calls) == 2
  messages = '\n'.join(message.text for messages in ollama.calls for message in messages)
  assert 'SOURCE-MODEL' in messages
  assert 'GOLDEN-ANSWER-CANARY' not in messages
  result = json.loads(report.read_text())
  assert result['totals']['document']['wrong'] == 1
  assert result['totals']['model']['wrong'] == 1
  assert result['models'][str(tmp_path)]['extractor']['llm_provider'] == 'ollama'
  row = result['models'][str(tmp_path)]['document']['rows'][0]
  assert row['got'] == 'LLM-RESULT'
  assert row['want'] == 'GOLDEN-ANSWER-CANARY'


def test_valid_fenced_llm_answer_passes(tmp_path: Path, ollama: RecordingModel) -> None:
  # Given a correct fenced JSON response, when evaluating, then both document and combined scores pass.
  sample(tmp_path)
  ollama.response = '```json\n{"model":"GOLDEN-ANSWER-CANARY"}\n```'
  assert evaluation.main([str(tmp_path), '--extractor', 'llm', '--output', str(tmp_path / 'report.json')]) == 0


@pytest.mark.parametrize('response', ['not JSON', '[]', '{"tasks":[{}]}', '{"plannedQty":NaN}'])
def test_malformed_llm_answers_do_not_publish_a_report(
  tmp_path: Path,
  ollama: RecordingModel,
  response: str,
) -> None:
  # Given malformed JSON or an invalid record, when evaluating, then it fails before publishing scores.
  sample(tmp_path)
  ollama.response = response
  report = tmp_path / 'report.json'
  with pytest.raises(ValidationError):
    evaluation.main([str(tmp_path), '--extractor', 'llm', '--output', str(report)])
  assert not report.exists()


def test_llm_output_contract_covers_all_golden_fields() -> None:
  # Given the saved golden formats, when validating the fixed output contract, then all are representable.
  for file in DATA.glob('LO-*/*.golden.json'):
    Extraction.model_validate(json.loads(file.read_text())['expected'])
