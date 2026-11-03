import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'


def model_folders(data: Path = DATA) -> list[Path]:
  return sorted(p for p in data.iterdir() if p.is_dir() and re.fullmatch(r'LO-[A-Z0-9]+(?:\(.+\))?', p.name))


def model_folder(data: Path, model: str) -> Path:
  matches = [p for p in model_folders(data) if p.name.split('(', 1)[0] == model]
  if len(matches) != 1:
    raise ValueError(f'{data} 안에서 모델 폴더를 하나로 확인할 수 없음: {model}')
  return matches[0]


def resolve_file(folder: Path, name: str) -> Path:
  """Resolve NFC references against NFD filenames without changing the dataset."""
  if Path(name).name != name or name in ('.', '..'):
    raise ValueError(f'파일 이름에 경로가 포함됨: {name}')
  matches = [p for p in folder.iterdir() if unicodedata.normalize('NFC', p.name) == unicodedata.normalize('NFC', name)]
  if len(matches) != 1:
    raise ValueError(f'{folder} 안에서 파일을 하나로 확인할 수 없음: {name}')
  return matches[0]
