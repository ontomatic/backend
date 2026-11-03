from importlib import reload

import pytest
from backend.core.config import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
  'origin',
  [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:5174',
    'http://127.0.0.1:3000',
    'http://localhost',
    'http://127.0.0.1',
    'https://localhost:3000',
    'https://127.0.0.1',
  ],
)
def test_frontend_origin_can_preflight_upload(client: TestClient, origin: str) -> None:
  # Given a frontend requesting an authenticated JSON upload.
  headers = {
    'Origin': origin,
    'Access-Control-Request-Method': 'POST',
    'Access-Control-Request-Headers': 'authorization,content-type',
  }

  # When the browser sends its preflight request.
  response = client.options('/api/v1/uploads', headers=headers)

  # Then the origin, method, and headers are permitted.
  assert response.status_code == 200
  assert response.headers['access-control-allow-origin'] == origin
  assert 'POST' in response.headers['access-control-allow-methods']
  assert 'authorization' in response.headers['access-control-allow-headers'].lower()
  assert 'content-type' in response.headers['access-control-allow-headers'].lower()


@pytest.mark.parametrize(
  'origin',
  [
    'https://example.com',
    'http://localhost.example.com:5173',
    'http://127.0.0.1.example.com:5173',
    'http://127x0x0x1:5173',
    'http://localhost:5173/path',
    'null',
  ],
)
def test_other_origins_are_not_allowed(client: TestClient, origin: str) -> None:
  # Given an origin outside the frontend development addresses.
  headers = {'Origin': origin, 'Access-Control-Request-Method': 'POST'}

  # When it sends a preflight request.
  response = client.options('/api/v1/uploads', headers=headers)

  # Then CORS access is denied.
  assert response.status_code == 400
  assert 'access-control-allow-origin' not in response.headers


def test_authentication_errors_include_cors_headers(client: TestClient) -> None:
  # Given a frontend request without a bearer token.
  headers = {'Origin': 'http://localhost:5173'}

  # When it calls an authenticated endpoint.
  response = client.get('/api/v1/auth/me', headers=headers)

  # Then the browser can read the authentication error.
  assert response.status_code == 401
  assert response.headers['access-control-allow-origin'] == headers['Origin']


@pytest.mark.parametrize('app_env', ['local', 'dev', 'prod'])
@pytest.mark.parametrize('origin', ['http://localhost:5173', 'http://127.0.0.1:3000'])
def test_cors_is_limited_to_local_and_dev(
  api_settings: Settings, api_app: FastAPI, monkeypatch: pytest.MonkeyPatch, app_env: str, origin: str
) -> None:
  from backend import app as app_module

  # Given an application initialized with the selected environment.
  monkeypatch.setattr(api_settings, 'app_env', app_env)
  try:
    application = reload(app_module).app
    with TestClient(application) as client:
      # When the browser preflights a loopback origin.
      response = client.options('/api/v1/uploads', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
      simple_response = client.get('/health-check', headers={'Origin': origin})

    # Then only local and dev grant CORS access, including on ordinary responses.
    assert response.status_code == (200 if app_env in ('local', 'dev') else 400)
    expected_origin = origin if app_env in ('local', 'dev') else None
    assert response.headers.get('access-control-allow-origin') == expected_origin
    assert simple_response.headers.get('access-control-allow-origin') == expected_origin
  finally:
    app_module.app = api_app


def test_unspecified_environment_defaults_to_local(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given no environment selection in the process or a dotenv file.
  monkeypatch.delenv('APP_ENV')

  # When settings are loaded without a dotenv file.
  settings = Settings(_env_file=None)

  # Then development CORS is enabled by default.
  assert settings.app_env == 'local'
