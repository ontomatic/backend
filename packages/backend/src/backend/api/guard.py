from typing import Annotated

from backend.core.jwt import decode_access_token
from backend.exceptions.auth import InvalidCredentialsException
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
