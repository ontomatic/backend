import base64
import hashlib
from urllib.parse import quote

from backend.core.config import get_settings
from backend.integrations.http import post_json


def cypher(statement: str, parameters: dict | None = None) -> list[dict]:
  settings = get_settings()
  if not settings.graph_rag_enabled or not settings.neo4j_password:
    raise RuntimeError('Neo4j is not configured')

  credentials = f'{settings.neo4j_user}:{settings.neo4j_password.get_secret_value()}'
  authorization = 'Basic ' + base64.b64encode(credentials.encode()).decode()
  url = f'{settings.neo4j_url.rstrip("/")}/db/{quote(settings.neo4j_database, safe="")}/query/v2'
  result = post_json(url, {'statement': statement, 'parameters': parameters or {}}, authorization=authorization)
  if result.get('errors'):
    raise RuntimeError('Neo4j query failed')

  data = result.get('data', {})
  return [dict(zip(data['fields'], row, strict=True)) for row in data.get('values', [])]


def vector_index() -> str:
  settings = get_settings()
  identity = settings.embedding_model

  if settings.embedding_provider != 'ollama':
    identity = f'{settings.embedding_provider}:{identity}'

  fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:12]
  return f'ontomatic_vectors_{fingerprint}'
