from datetime import timedelta

import jwt

from backend.core.config import get_settings
from backend.core.utils import utc_now


def create_access_token(user_id: int) -> str:
  settings = get_settings()
  now = utc_now()

  return jwt.encode(
    {'sub': str(user_id), 'iat': now, 'exp': now + timedelta(minutes=settings.jwt_expire_minutes)},
    settings.jwt_secret_key.get_secret_value(),
    algorithm='HS256',
  )


def decode_access_token(token: str) -> int:
  jwt_secret = get_settings().jwt_secret_key.get_secret_value()
  payload = jwt.decode(token, jwt_secret, algorithms=['HS256'], options={'require': ['sub', 'iat', 'exp']})

  try:
    user_id = int(payload['sub'])
    if user_id <= 0:
      raise jwt.InvalidTokenError('Invalid user ID')
    return user_id
  except (TypeError, ValueError) as exc:
    raise jwt.InvalidTokenError('Invalid user ID') from exc
