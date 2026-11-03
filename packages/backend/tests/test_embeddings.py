import hashlib
from urllib.error import URLError

import pytest
from backend.core.config import Settings
from backend.integrations import graph
from backend.integrations.embeddings import factory, ollama, upstage
from pydantic import SecretStr, ValidationError


@pytest.mark.parametrize('provider', ['ollama', 'upstage'])
def test_factory_uses_provider_for_documents_and_queries(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
  # Given configured credentials and an embedding model for the selected provider.
  model = 'solar-embedding-2-passage' if provider == 'upstage' else 'qwen3-embedding:0.6b'
  settings = api_settings.model_copy(
    update={
      'embedding_provider': provider,
      'embedding_model': model,
      'upstage_api_key': SecretStr('test-key'),
      'upstage_base_url': 'https://upstage.test/v1/',
    }
  )
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  requests = []

  def post(url: str, body: dict, *, authorization: str | None = None) -> dict:
    requests.append((url, body, authorization))
    vectors = [[float(index + 1), 0.5] for index in range(len(body['input']))]
    if provider == 'upstage':
      return {'data': [{'index': index, 'embedding': vector} for index, vector in reversed(list(enumerate(vectors)))]}
    return {'embeddings': vectors}

  module = upstage if provider == 'upstage' else ollama
  monkeypatch.setattr(module, 'post_json', post)

  # When the factory's embedder indexes documents and embeds a search question.
  embedder = factory.create_embedder()
  assert embedder.embed_documents(['문서 A', '문서 B']) == [[1.0, 0.5], [2.0, 0.5]]
  assert embedder.embed_query('질문') == [1.0, 0.5]

  # Then input order is preserved, and retrieval uses the provider's matching query model.
  assert requests[0][1]['input'] == ['문서 A', '문서 B']
  assert requests[1][1]['input'] == ['질문']
  assert requests[0][1]['model'] == model
  if provider == 'upstage':
    assert requests[1][1]['model'] == 'solar-embedding-2-query'
    assert all(url == 'https://upstage.test/v1/embeddings' for url, _, _ in requests)
    assert all(authorization == 'Bearer test-key' for _, _, authorization in requests)
  else:
    assert requests[1][1]['model'] == model
    assert all(url == settings.ollama_base_url.rstrip('/') + '/api/embed' for url, _, _ in requests)
    assert all(body['truncate'] is False for _, body, _ in requests)


def test_upstage_requires_credentials(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given Upstage without a key, when creating its embedder, then it fails before sending a request.
  settings = api_settings.model_copy(update={'embedding_provider': 'upstage', 'upstage_api_key': None})
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  with pytest.raises(ValueError, match='Upstage API key is required'):
    factory.create_embedder()


def test_upstage_requires_passage_model(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given an incompatible model, when creating Upstage, then its required configuration is explicit.
  settings = api_settings.model_copy(
    update={
      'embedding_provider': 'upstage',
      'embedding_model': 'qwen3-embedding:0.6b',
      'upstage_api_key': SecretStr('test-key'),
    }
  )
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  with pytest.raises(ValueError, match='passage'):
    factory.create_embedder()


@pytest.mark.parametrize('provider', ['ollama', 'upstage'])
@pytest.mark.parametrize(
  'vectors', [None, [], [[], [1.0]], [[1.0], [1.0, 2.0]], [[float('nan')], [1.0]], [['bad'], [1.0]]]
)
def test_embedders_reject_invalid_vectors(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, provider: str, vectors: object
) -> None:
  # Given missing, empty, ragged or nonnumeric vectors, when embedding, then indexing cannot use them.
  settings = api_settings.model_copy(
    update={
      'embedding_provider': provider,
      'embedding_model': 'solar-embedding-2-passage',
      'upstage_api_key': SecretStr('test-key'),
    }
  )
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  module = upstage if provider == 'upstage' else ollama
  payload = {'embeddings': vectors}
  if provider == 'upstage':
    payload = {'data': [{'index': index, 'embedding': vector} for index, vector in enumerate(vectors or [])]}
  monkeypatch.setattr(module, 'post_json', lambda *args, **kwargs: payload)
  with pytest.raises(RuntimeError, match='embedding response'):
    factory.create_embedder().embed_documents(['first', 'second'])


@pytest.mark.parametrize('indices', [[0, 0], [0, 2], [-1, 0], [False, 1]])
def test_upstage_rejects_invalid_response_indices(monkeypatch: pytest.MonkeyPatch, indices: list[int]) -> None:
  # Given duplicate or invalid response indices, when embedding, then vectors cannot attach to the wrong source.
  payload = {'data': [{'index': index, 'embedding': [1.0]} for index in indices]}
  monkeypatch.setattr(upstage, 'post_json', lambda *args, **kwargs: payload)
  with pytest.raises(RuntimeError, match='embedding response'):
    upstage.UpstageEmbedder('solar-embedding-2-passage', 'test-key', 'https://upstage.test/v1').embed_documents(
      ['a', 'b']
    )


@pytest.mark.parametrize('provider', ['ollama', 'upstage'])
def test_embedders_skip_empty_batches_and_propagate_network_errors(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
  # Given a failing network, when embedding an empty batch, then no request is needed; real input still fails.
  settings = api_settings.model_copy(
    update={
      'embedding_provider': provider,
      'embedding_model': 'solar-embedding-2-passage',
      'upstage_api_key': SecretStr('test-key'),
    }
  )
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)

  def fail(*args: object, **kwargs: object) -> dict:
    raise URLError('offline')

  monkeypatch.setattr(upstage if provider == 'upstage' else ollama, 'post_json', fail)
  embedder = factory.create_embedder()
  assert embedder.embed_documents([]) == []
  with pytest.raises(URLError):
    embedder.embed_query('question')


def test_embedding_provider_environment_and_default(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
  # Given environment configuration, when loading settings, then the provider is validated and defaults to Ollama.
  monkeypatch.delenv('EMBEDDING_PROVIDER', raising=False)
  assert Settings(_env_file=None).embedding_provider == 'ollama'
  monkeypatch.setenv('EMBEDDING_PROVIDER', 'upstage')
  monkeypatch.setenv('EMBEDDING_MODEL', 'solar-embedding-2-passage')
  settings = Settings(_env_file=None)
  assert settings.embedding_provider == 'upstage'
  assert settings.embedding_model == 'solar-embedding-2-passage'
  monkeypatch.setenv('EMBEDDING_PROVIDER', 'unknown')
  with pytest.raises(ValidationError, match='embedding_provider'):
    Settings(_env_file=None)


def test_vector_index_preserves_ollama_and_separates_providers(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given an existing model, when changing providers, then legacy Ollama names remain and other vectors are isolated.
  settings = api_settings.model_copy(update={'embedding_provider': 'ollama', 'embedding_model': 'same-model'})
  monkeypatch.setattr(graph, 'get_settings', lambda: settings)
  original = graph.vector_index()
  assert original == 'ontomatic_vectors_' + hashlib.sha256(b'same-model').hexdigest()[:12]
  settings.embedding_provider = 'upstage'
  upstage_index = graph.vector_index()
  assert upstage_index != original
  settings.embedding_model = 'other-model'
  assert graph.vector_index() not in (original, upstage_index)
