from backend.api.guard import CurrentUserId
from backend.integrations.llm.factory import create_llm
from backend.schemas.llm import ChatIn, ChatOut
from fastapi import APIRouter

router = APIRouter(prefix='/chat', tags=['chat'])


@router.post('', response_model=ChatOut)
async def chat(user_id: CurrentUserId, body: ChatIn) -> ChatOut:
  llm = create_llm()
  text = await llm.generate(body.prompt)

  return ChatOut(text=text)
