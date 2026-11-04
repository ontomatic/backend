from backend.integrations.embeddings.validation import validate_vectors
from backend.integrations.http import post_json


class UpstageEmbedder:
  def __init__(self, model: str, api_key: str, base_url: str) -> None:
    if not model.endswith('-passage'):
      raise ValueError('Upstage requires a passage model, such as solar-embedding-2-passage, in EMBEDDING_MODEL.')

    self.model = model
    self.api_key = api_key
    self.base_url = base_url.rstrip('/')

  def _embed(self, texts: list[str], model: str) -> list[list[float]]:
    if not texts:
      return []

    url = f'{self.base_url}/embeddings'
    result = post_json(url, {'model': model, 'input': texts}, authorization=f'Bearer {self.api_key}')

    data = result.get('data') if isinstance(result, dict) else None
    if not isinstance(data, list) or any(
      not isinstance(item, dict) or type(item.get('index')) is not int for item in data
    ):
      raise RuntimeError('Invalid embedding response')

    data = sorted(data, key=lambda item: item['index'])
    if [item['index'] for item in data] != list(range(len(texts))):
      raise RuntimeError('Invalid embedding response')

    return validate_vectors([item.get('embedding') for item in data], len(texts))

  def embed_documents(self, texts: list[str]) -> list[list[float]]:
    return self._embed(texts, self.model)

  def embed_query(self, text: str) -> list[float]:
    return self._embed([text], self.model.removesuffix('-passage') + '-query')[0]
