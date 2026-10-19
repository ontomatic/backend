from backend.api.guard import CurrentUserId
from backend.schemas.auth import LoginIn, TokenOut
from backend.schemas.user import UserOut
from backend.services.auth import get_current_user, login
from fastapi import APIRouter

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/login', response_model=TokenOut)
def login_user(body: LoginIn) -> TokenOut:
  access_token = login(body.emp_id, body.password.get_secret_value())
  return TokenOut(accessToken=access_token)


@router.get('/me', response_model=UserOut)
def current_user(user_id: CurrentUserId) -> UserOut:
  return get_current_user(user_id)
