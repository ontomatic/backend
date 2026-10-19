from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from backend.integrations.llm.interface import LLM


class ChatLLM(LLM):
  def __init__(self, model: BaseChatModel) -> None:
    self._model = model

  async def generate(self, prompt: str, *, system: str | None = None) -> str:
    messages: list[BaseMessage] = []
    if system is not None:
      messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    response = await self._model.ainvoke(messages)
    return response.text
