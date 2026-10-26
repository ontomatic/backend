import sqlite3
from collections.abc import Generator

import pytest
from backend.core.config import Settings, get_settings
from backend.core.jwt import create_access_token
from backend.db import session as db_session_module
from backend.db.base import Base
from backend.models import Department, User, UserRole
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

from .factories import create_department, create_user


@pytest.fixture(scope='session')
def api_settings() -> Generator[Settings, None, None]:
  # Keep imported references to get_settings consistent by using its normal environment loader.
  with pytest.MonkeyPatch.context() as monkeypatch:
    for name, value in {
      'POSTGRES_USER': 'test',
      'POSTGRES_PASSWORD': 'test',
      'POSTGRES_DB': 'test',
      'JWT_SECRET_KEY': 'admin-api-test-signing-key-at-least-32-characters',
      'S3_ACCESS_KEY_ID': 'test',
      'S3_SECRET_ACCESS_KEY': 'test',
      'LANGFUSE_ENABLED': 'false',
    }.items():
      monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
      yield get_settings()
    finally:
      get_settings.cache_clear()


@pytest.fixture(scope='session')
def api_app(api_settings: Settings) -> FastAPI:
  # Storage configuration is read during app import, after api_settings has prepared the environment.
  from backend.app import app

  return app


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
  engine = create_engine(
    'sqlite+pysqlite:///:memory:',
    connect_args={'check_same_thread': False},
    poolclass=StaticPool,
  )

  @event.listens_for(engine, 'connect')
  def enable_foreign_keys(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
    connection.execute('PRAGMA foreign_keys=ON')

  Base.metadata.create_all(
    engine,
    tables=[Base.metadata.tables[Department.__tablename__], Base.metadata.tables[User.__tablename__]],
  )
  factory = sessionmaker(bind=engine, expire_on_commit=False)
  monkeypatch.setattr(db_session_module, 'get_session_factory', lambda: factory)
  try:
    yield factory
  finally:
    engine.dispose()


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
  with session_factory() as session:
    yield session


@pytest.fixture
def client(api_app: FastAPI, session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
  with TestClient(api_app) as client:
    yield client


@pytest.fixture
def admin_user(db_session: Session) -> User:
  return create_user(db_session, emp_id='SYS001', name='시스템 관리자', role=UserRole.SYSTEM_ADMIN)


@pytest.fixture
def admin_client(client: TestClient, admin_user: User) -> TestClient:
  client.headers['Authorization'] = f'Bearer {create_access_token(admin_user.id)}'
  return client


@pytest.fixture
def active_department(db_session: Session) -> Department:
  return create_department(db_session, code='research', name='연구개발')


@pytest.fixture
def user_create_body(active_department: Department) -> dict[str, object]:
  return {
    'emp_id': 'NEW001',
    'name': '신규 사용자',
    'department_id': active_department.id,
    'password': 'InitialPass123!',
  }
