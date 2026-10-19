from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from backend.core.config import get_settings
from backend.integrations.llm.chat import ChatLLM
from backend.integrations.llm.interface import LLM


def create_llm() -> LLM:
  settings = get_settings()
  provider, model = settings.llm_provider, settings.llm_model

  if provider == 'ollama':
    return ChatLLM(ChatOllama(model=model, base_url=settings.ollama_base_url))

  if provider == 'google':
    if not settings.google_api_key:
      raise ValueError('Google API key is required.')
    api_key = settings.google_api_key.get_secret_value()
    return ChatLLM(ChatGoogleGenerativeAI(model=model, api_key=api_key, vertexai=False))

  if provider == 'anthropic':
    if not settings.anthropic_api_key:
      raise ValueError('Anthropic API key is required')
    api_key = settings.anthropic_api_key.get_secret_value()
    return ChatLLM(ChatAnthropic(model=model, api_key=api_key))
