from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic.script import ScriptDirectory
from backend import main
from backend.core.config import Settings


@pytest.mark.parametrize('environment', ['local', 'dev', 'prod'])
def test_api_migrates_before_serving_from_any_working_directory(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, environment: str
) -> None:
  # Given a configured environment, when the API starts, then migrations finish before it accepts requests.
  events = []
  upgrade = Mock(side_effect=lambda *_: events.append('migration'))
  serve = Mock(side_effect=lambda *_, **__: events.append('serve'))
  monkeypatch.setattr('alembic.command.upgrade', upgrade)
  monkeypatch.setattr('uvicorn.run', serve)
  monkeypatch.setattr(
    'backend.core.config.get_settings', lambda: api_settings.model_copy(update={'app_env': environment})
  )
  monkeypatch.chdir(tmp_path)

  main()

  assert events == ['migration', 'serve']
  config, revision = upgrade.call_args.args
  assert revision == 'head'
  assert Path(config.config_file_name).is_absolute()
  assert ScriptDirectory.from_config(config).get_current_head()
  assert serve.call_args.args == ('backend.app:app',)
  options = serve.call_args.kwargs
  assert options['host'] == ('0.0.0.0' if environment == 'prod' else '127.0.0.1')
  assert options['port'] == 8000
  assert options['reload'] is (environment != 'prod')
  assert bool(options['reload_dirs']) is (environment != 'prod')


def test_api_does_not_start_when_migration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
  # Given a failed migration, when starting the API, then the error escapes and the server never starts.
  monkeypatch.setattr('alembic.command.upgrade', Mock(side_effect=RuntimeError('migration failed')))
  serve = Mock()
  monkeypatch.setattr('uvicorn.run', serve)

  with pytest.raises(RuntimeError, match='migration failed'):
    main()

  serve.assert_not_called()
