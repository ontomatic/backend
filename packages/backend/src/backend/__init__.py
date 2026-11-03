from pathlib import Path


def _dev() -> None:
  import uvicorn

  dir = Path(__file__).resolve().parent
  uvicorn.run('backend.app:app', host='127.0.0.1', port=8000, reload=True, reload_dirs=[str(dir)])


def _prod() -> None:
  import uvicorn

  uvicorn.run('backend.app:app', host='0.0.0.0', port=8000, reload=False, reload_dirs=None)


def main() -> None:
  from alembic import command
  from alembic.config import Config

  from backend.core.config import BACKEND_ROOT, get_settings

  command.upgrade(Config(str(BACKEND_ROOT / 'alembic.ini')), 'head')

  env = get_settings().app_env
  if env == 'prod':
    _prod()
  else:
    _dev()
