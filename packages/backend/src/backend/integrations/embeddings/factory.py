from backend.core.config import get_settings
from backend.integrations.embeddings.interface import Embedder
from backend.integrations.embeddings.ollama import OllamaEmbedder
from backend.integrations.embeddings.upstage import UpstageEmbedder


def create_embedder() -> Embedder:
  settings = get_settings()

  if settings.embedding_provider == 'ollama':
    return OllamaEmbedder(settings.embedding_model, settings.ollama_base_url)

  if settings.embedding_provider == 'upstage':
    if not settings.upstage_api_key:
      raise ValueError('Upstage API key is required.')

    return UpstageEmbedder(
      settings.embedding_model, settings.upstage_api_key.get_secret_value(), settings.upstage_base_url
    )
