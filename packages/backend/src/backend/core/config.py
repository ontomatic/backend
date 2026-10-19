from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
  model_config = SettingsConfigDict(
    env_file=BACKEND_ROOT / '.env',
    env_file_encoding='utf-8',
    extra='ignore',
    case_sensitive=False,
    env_ignore_empty=True,
  )

  postgres_user: str
  postgres_password: SecretStr
  postgres_host: str = 'localhost'
  postgres_port: int = Field(default=5432, ge=1, le=65535)
  postgres_db: str

  jwt_secret_key: SecretStr
  jwt_expire_minutes: int = Field(default=480, ge=1)

  langfuse_enabled: bool = False
  langfuse_secret_key: SecretStr | None = None
  langfuse_public_key: str | None = None
  langfuse_host: str = 'http://localhost:3000'

  llm_provider: Literal['ollama', 'gemini', 'claude'] = 'ollama'
  llm_model: str = 'llama3.2'
  ollama_base_url: str = 'http://localhost:11434'

  google_api_key: SecretStr | None = None
  anthropic_api_key: SecretStr | None = None

  @property
  def database_url(self) -> URL:
    return URL.create(
      drivername='postgresql+psycopg',
      username=self.postgres_user,
      password=self.postgres_password.get_secret_value(),
      host=self.postgres_host,
      port=self.postgres_port,
      database=self.postgres_db,
    )


@lru_cache
def get_settings() -> Settings:
  return Settings()
