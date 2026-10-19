from langfuse import Langfuse

from backend.core.config import get_settings
from backend.core.logger import get_logger

log = get_logger(__name__)

_langfuse_client: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
  return _langfuse_client


def initialize_langfuse() -> None:
  global _langfuse_client
  if _langfuse_client is not None:
    return

  settings = get_settings()
  if not settings.langfuse_enabled:
    return

  if not settings.langfuse_public_key or not settings.langfuse_secret_key:
    log.warning('Langfuse API keys are missing. Tracing is disabled.')
    return

  try:
    _langfuse_client = Langfuse(
      public_key=settings.langfuse_public_key,
      secret_key=settings.langfuse_secret_key.get_secret_value(),
      host=settings.langfuse_host,
    )
  except ValueError as exc:
    log.warning('Failed to Create Langfuse client. :%s', exc)
    _langfuse_client = None


def shutdown_langfuse() -> None:
  global _langfuse_client

  try:
    if _langfuse_client is not None:
      _langfuse_client.shutdown()
  finally:
    _langfuse_client = None
