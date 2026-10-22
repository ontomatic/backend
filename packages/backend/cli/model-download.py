import argparse
from pathlib import Path

import yaml
from huggingface_hub import HfApi, snapshot_download

CURRENT = Path(__file__)
BACKEND_ROOT = CURRENT.resolve().parents[2]


def main() -> None:
  parser = argparse.ArgumentParser(description='설정된 Hugging Face 모델을 다운로드합니다.')

  try:
    config = yaml.safe_load(CURRENT.with_name('config.yaml').read_text(encoding='utf-8'))
    models = config['models']
    OUTPUT = BACKEND_ROOT / 'models'

    if not isinstance(models, dict) or not models:
      raise ValueError('models에는 모델명과 설정이 필요합니다.')
  except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as error:
    parser.error(f'config.yaml을 읽을 수 없습니다: {error}')

  parser.add_argument('--model', choices=models, help='다운로드할 모델명')
  args = parser.parse_args()
  model = models[args.model]
  if not isinstance(model, dict) or not isinstance(model.get('repo_id'), str) or not model['repo_id'].strip():
    parser.error(f'{args.model_name}의 repo_id는 비어 있지 않은 문자열이어야 합니다.')

  repo_id = model['repo_id']
  output_dir = OUTPUT / args.model
  completed = output_dir / '.download_complete'
  if completed.is_file() and completed.read_text(encoding='utf-8') == repo_id:
    print(f'이미 다운로드되어 건너뜁니다: {output_dir}')
    return

  print(f'다운로드: {repo_id} -> {output_dir}')
  info = HfApi().model_info(repo_id=repo_id)
  snapshot_download(repo_id=repo_id, revision=info.sha, local_dir=output_dir)
  if any(not (output_dir / file.rfilename).is_file() for file in (info.siblings or [])):
    raise RuntimeError(f'누락된 파일이 있습니다. 다시 실행하세요: {output_dir}')
  completed.write_text(repo_id, encoding='utf-8')
  print(f'다운로드 완료: {output_dir}')
