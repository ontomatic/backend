from backend.core.jwt import create_access_token
from backend.core.password import verify_password
from backend.db.session import get_session
from backend.exceptions.auth import InvalidCredentialsException
from backend.repositories.users import get_user_by_emp_id, get_user_by_id
from backend.schemas.user import UserOut


def login(emp_id: str, password: str) -> str:
  with get_session() as session:
    user = get_user_by_emp_id(session, emp_id)
    if user is None or not verify_password(password, user.password_hash):
      raise InvalidCredentialsException()

    return create_access_token(user.id)


def get_current_user(user_id: int) -> UserOut:
  with get_session() as session:
    user = get_user_by_id(session, user_id)
    if user is None:
      raise InvalidCredentialsException()

    return UserOut.model_validate(user)
