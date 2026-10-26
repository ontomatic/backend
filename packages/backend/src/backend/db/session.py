from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import get_settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
  engine = create_engine(get_settings().database_url, pool_pre_ping=True)
  return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
  with get_session_factory().begin() as session:
    yield session
