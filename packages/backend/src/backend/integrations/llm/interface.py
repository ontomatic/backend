from abc import abstractmethod
from typing import Protocol


class LLM(Protocol):
  @abstractmethod
  async def generate(self, prompt: str, *, system: str | None = None) -> str: ...
