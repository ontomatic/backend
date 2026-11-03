from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from backend.core.config import get_settings
from backend.integrations.llm.chat import ChatLLM
from backend.integrations.llm.interface import LLM


def _ollama_schema(value: Any) -> Any:
  if isinstance(value, dict):
    return {key: _ollama_schema(child) for key, child in value.items() if key not in ('maxLength', 'maxItems')}
  if isinstance(value, list):
    return [_ollama_schema(child) for child in value]

  return value


def create_llm(*, output_schema: dict | None = None) -> LLM:
  settings = get_settings()
  provider, model = settings.llm_provider, settings.llm_model

  temperature = 0.0

  if provider == 'ollama':
    return ChatLLM(
      ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        format=_ollama_schema(output_schema) if output_schema else None,
        num_ctx=16_384 if output_schema else None,
      )
    )

  if provider == 'google':
    if not settings.google_api_key:
      raise ValueError('Google API key is required.')

    api_key = settings.google_api_key.get_secret_value()
    return ChatLLM(ChatGoogleGenerativeAI(model=model, api_key=api_key, vertexai=False, temperature=temperature))

  if provider == 'anthropic':
    if not settings.anthropic_api_key:
      raise ValueError('Anthropic API key is required')

    api_key = settings.anthropic_api_key
    return ChatLLM(ChatAnthropic(model_name=model, api_key=api_key, timeout=60, stop=None))
