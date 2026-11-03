from backend.integrations.embeddings.validation import validate_vectors
from backend.integrations.http import post_json


class OllamaEmbedder:
  def __init__(self, model: str, base_url: str) -> None:
    self.model = model
    self.base_url = base_url.rstrip('/')

  def embed_documents(self, texts: list[str]) -> list[list[float]]:
    if not texts:
      return []

    url = f'{self.base_url}/api/embed'
    result = post_json(url, {'model': self.model, 'input': texts, 'truncate': False})
    vectors = result.get('embeddings') if isinstance(result, dict) else None

    return validate_vectors(vectors, len(texts))

  def embed_query(self, text: str) -> list[float]:
    return self.embed_documents([text])[0]
