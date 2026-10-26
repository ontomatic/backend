"""Keep the existing verification command connected to the shared harness."""

import runpy
from pathlib import Path

if __name__ == '__main__':
  checker = Path(__file__).resolve().parents[1] / '.agents' / 'scripts' / 'check.py'
  runpy.run_path(str(checker), run_name='__main__')
