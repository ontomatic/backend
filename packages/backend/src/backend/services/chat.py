from fastapi.concurrency import run_in_threadpool

from backend.integrations.llm.factory import create_llm
from backend.schemas.llm import ChatOut
from backend.services.auth import validate_active_user


async def generate_chat(user_id: int, prompt: str) -> ChatOut:
  await run_in_threadpool(validate_active_user, user_id)
  llm = create_llm()
  text = await llm.generate(prompt)
  return ChatOut(text=text)
