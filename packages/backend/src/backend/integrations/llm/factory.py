from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from backend.core.config import get_settings
from backend.integrations.llm.chat import ChatLLM
from backend.integrations.llm.interface import LLM


def create_llm() -> LLM:
  settings = get_settings()
  provider, model = settings.llm_provider, settings.llm_model

  temperature = 0.0

  if provider == 'ollama':
    return ChatLLM(ChatOllama(model=model, base_url=settings.ollama_base_url, temperature=temperature))

  if provider == 'google':
    if not settings.google_api_key:
      raise ValueError('Google API key is required.')
    api_key = settings.google_api_key.get_secret_value()
    return ChatLLM(ChatGoogleGenerativeAI(model=model, api_key=api_key, vertexai=False, temperature=temperature))

  if provider == 'anthropic':
    if not settings.anthropic_api_key:
      raise ValueError('Anthropic API key is required')
    api_key = settings.anthropic_api_key
    return ChatLLM(
      ChatAnthropic(
        model_name=model,
        api_key=api_key,
        timeout=60,
        stop=None,
        temperature=temperature,
      )
    )

  raise ValueError(f'Unsupported LLM provider: {provider}')
