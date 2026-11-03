import asyncio
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from inspect import isawaitable
from typing import Any

from backend.integrations.langfuse import get_langfuse, initialize_langfuse, shutdown_langfuse
from langfuse import Langfuse
from langfuse.experiment import EvaluatorFunction, TaskFunction


@contextmanager
def tracking(enabled: bool) -> Iterator[Langfuse | None]:
  if not enabled:
    yield None
    return
  initialize_langfuse()
  client = get_langfuse()
  if client is None:
    raise ValueError('Langfuse 추적에는 LANGFUSE_ENABLED=true와 public/secret key 설정이 필요합니다.')
  try:
    if not client.auth_check():
      raise ValueError('Langfuse 인증에 실패했습니다. 서버 주소와 API key 설정을 확인하세요.')
    yield client
  finally:
    shutdown_langfuse()


def run_items(
  name: str,
  data: list[dict],
  task: TaskFunction,
  evaluator: EvaluatorFunction,
  client: Langfuse | None,
) -> list[dict]:
  current = 0

  async def run_task(*, item: dict, **kwargs: Any) -> dict:
    nonlocal current
    current += 1
    if 'id' in item['input']:
      label = item['input']['id']
    elif item['metadata']['scope'] == 'model':
      label = f'{item["metadata"]["model"]} 합본'
    else:
      label = item['input']['files'][0]
    prefix = f'[{name}] [{current}/{len(data)}]'
    print(f'{prefix} 시작: {label}', file=sys.stderr, flush=True)
    try:
      output = task(item=item, **kwargs)
      output = await output if isawaitable(output) else output
    except Exception:
      print(f'{prefix} 실패: {label}', file=sys.stderr, flush=True)
      raise
    print(f'{prefix} 완료: {label}', file=sys.stderr, flush=True)
    return output

  if client is None:

    async def run_local() -> list[dict]:
      results = []
      for item in data:
        results.append(await run_task(item=item))
      return results

    return asyncio.run(run_local())
  result = client.run_experiment(
    name=name,
    data=data,
    task=run_task,
    evaluators=[evaluator],
    max_concurrency=1,
  )
  # The SDK logs and omits failed tasks, and can return an item without evaluator scores.
  if len(result.item_results) != len(data) or any(not item.evaluations for item in result.item_results):
    raise RuntimeError('Langfuse 실험의 추출 또는 채점에 실패했습니다. 실행 로그를 확인하세요.')
  print(f'Langfuse: {result.experiment_url or result.run_name}')
  return [item.output for item in result.item_results]
