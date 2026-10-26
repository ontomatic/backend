from backend.api.guard import CurrentUserId
from backend.schemas.llm import ChatIn, ChatOut
from backend.services.chat import generate_chat
from fastapi import APIRouter

router = APIRouter(prefix='/chat', tags=['chat'])


@router.post('', response_model=ChatOut)
async def chat(user_id: CurrentUserId, body: ChatIn) -> ChatOut:
  return await generate_chat(user_id, body.prompt)
