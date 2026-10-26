from typing import Annotated

from backend.api.dependencies import RequestSession
from backend.core.jwt import decode_access_token
from backend.exceptions.auth import InvalidCredentialsException
from backend.models.user import User
from backend.services.auth import get_current_user, require_system_admin
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

bearer = HTTPBearer(auto_error=False)


def require_user_id(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> int:
  if credentials is None:
    raise InvalidCredentialsException()

  try:
    return decode_access_token(credentials.credentials)
  except InvalidTokenError as exc:
    raise InvalidCredentialsException() from exc


CurrentUserId = Annotated[int, Depends(require_user_id)]


def login_required(user_id: CurrentUserId, session: RequestSession) -> User:
  return get_current_user(session, user_id)


def system_admin_required(user_id: CurrentUserId, session: RequestSession) -> User:
  return require_system_admin(session, user_id)


CurrentUser = Annotated[User, Depends(login_required)]
