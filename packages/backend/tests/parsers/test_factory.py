from io import BytesIO

import pytest
from backend.core.config import Settings
from backend.parsers.documents.factory import create_parser
from backend.parsers.documents.upstage import UpstageParser
from pydantic import SecretStr, ValidationError


@pytest.mark.parametrize('extension', ['pdf', '.PDF', 'docx', '.DOCX', 'xlsx', '.XLSX', 'csv', '.CSV'])
def test_local_provider_keeps_existing_parsers(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
  # Given the local provider, when selecting a format, then the existing parser is returned.
  from backend.parsers.documents import factory

  monkeypatch.setattr(factory, 'get_settings', lambda: api_settings.model_copy(update={'parser_provider': 'local'}))
  assert create_parser(extension).__name__ == f'parse_{extension.lower().lstrip(".")}'


@pytest.mark.parametrize('extension', ['pdf', '.DOCX', 'xlsx'])
def test_upstage_provider_selects_remote_parser(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
  # Given Upstage credentials, when selecting a supported format, then its adapter is returned.
  from backend.parsers.documents import factory

  settings = api_settings.model_copy(update={'parser_provider': 'upstage', 'upstage_api_key': SecretStr('test-key')})
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  assert isinstance(create_parser(extension), UpstageParser)


def test_upstage_keeps_csv_local_without_credentials(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given CSV is unsupported by Upstage, when parsing CSV, then the local result is preserved.
  from backend.parsers.documents import factory

  settings = api_settings.model_copy(update={'parser_provider': 'upstage', 'upstage_api_key': None})
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  assert create_parser('.csv')(BytesIO(b'name,value\na,1')).blocks[0].rows == [['name', 'value'], ['a', '1']]


def test_upstage_requires_api_key(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given missing credentials, when selecting Upstage, then configuration fails before any request.
  from backend.parsers.documents import factory

  settings = api_settings.model_copy(update={'parser_provider': 'upstage', 'upstage_api_key': None})
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  with pytest.raises(ValueError, match='Upstage API key is required'):
    create_parser('pdf')


@pytest.mark.parametrize('provider', ['local', 'upstage'])
def test_factory_rejects_unsupported_format(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
  # Given either provider, when selecting an unsupported format, then the original error is preserved.
  from backend.parsers.documents import factory

  monkeypatch.setattr(factory, 'get_settings', lambda: api_settings.model_copy(update={'parser_provider': provider}))
  with pytest.raises(ValueError, match='Unsupported file format: .exe'):
    create_parser('.exe')


def test_settings_load_parser_environment(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given environment configuration, when loading settings, then the provider and secret are loaded.
  monkeypatch.setenv('PARSER_PROVIDER', 'upstage')
  monkeypatch.setenv('UPSTAGE_API_KEY', 'test-key')
  monkeypatch.setenv('UPSTAGE_BASE_URL', 'https://upstage.test/v1')
  settings = Settings(_env_file=None)
  assert settings.parser_provider == 'upstage'
  assert settings.upstage_api_key.get_secret_value() == 'test-key'
  assert settings.upstage_base_url == 'https://upstage.test/v1'
  assert 'test-key' not in repr(settings)


def test_settings_default_to_local_parser(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given no provider configuration, when loading settings, then parsing remains local.
  monkeypatch.delenv('PARSER_PROVIDER', raising=False)
  monkeypatch.delenv('UPSTAGE_BASE_URL', raising=False)
  settings = Settings(_env_file=None)
  assert settings.parser_provider == 'local'
  assert settings.upstage_base_url == 'https://api.upstage.ai/v1'


def test_settings_reject_unknown_parser_provider(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given a misspelled provider, when loading settings, then it cannot silently use another parser.
  monkeypatch.setenv('PARSER_PROVIDER', 'unknown')
  with pytest.raises(ValidationError, match='parser_provider'):
    Settings(_env_file=None)


def test_existing_get_parser_import_remains_available() -> None:
  # Given the existing public import, when resolving it, then it uses the same factory.
  from backend.parsers.documents import get_parser

  assert get_parser is create_parser
