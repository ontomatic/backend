"""Run the repository's local checks without fixing files or installing dependencies."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
  root = Path(__file__).resolve().parents[1]
  checks = (
    ('Ruff lint', ('ruff', 'check', '.')),
    ('Ruff format', ('ruff', 'format', '--check', '.')),
    ('Backend tests', ('pytest', 'packages/backend/tests', '-q')),
  )
  results = []

  for name, args in checks:
    print(f'\n== {name} ==', flush=True)
    try:
      result = subprocess.run([sys.executable, '-m', *args], cwd=root, check=False)
      returncode = result.returncode
    except OSError as exc:
      print(f'Could not run {name}: {exc}', file=sys.stderr, flush=True)
      returncode = 1
    results.append((name, returncode))

  print('\nCheck results:', flush=True)
  for name, returncode in results:
    status = 'PASS' if returncode == 0 else f'FAIL (exit {returncode})'
    print(f'  {name}: {status}', flush=True)

  return int(any(returncode != 0 for _, returncode in results))


if __name__ == '__main__':
  raise SystemExit(main())
