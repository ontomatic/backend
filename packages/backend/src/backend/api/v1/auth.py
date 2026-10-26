from backend.api.dependencies import RequestSession
from backend.api.guard import CurrentUserId
from backend.schemas.auth import LoginIn, TokenOut
from backend.schemas.user import UserOut
from backend.services.auth import get_current_user, login
from fastapi import APIRouter

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/login', response_model=TokenOut)
def login_user(session: RequestSession, body: LoginIn) -> TokenOut:
  access_token = login(session, body.emp_id, body.password.get_secret_value())
  return TokenOut(accessToken=access_token)


@router.get('/me', response_model=UserOut)
def current_user(user_id: CurrentUserId, session: RequestSession) -> UserOut:
  return UserOut.model_validate(get_current_user(session, user_id))
