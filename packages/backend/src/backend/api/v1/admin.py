from typing import Annotated

from backend.api.guard import CurrentUserId
from backend.schemas.department import DepartmentOut
from backend.schemas.error import ErrorOut
from backend.schemas.user import UserCreateIn, UserListOut, UserListQuery, UserOut, UserUpdateIn
from backend.services.departments import get_departments
from backend.services.users import create_user, get_users, update_user
from fastapi import APIRouter, Path, Query

router = APIRouter(
  prefix='/admin',
  tags=['admin'],
  responses={401: {'model': ErrorOut}, 403: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)


@router.post(
  '/users',
  status_code=201,
  response_model=UserOut,
  summary='일반 사용자 생성',
  responses={409: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)
def create_user_account(actor_id: CurrentUserId, body: UserCreateIn) -> UserOut:
  return create_user(actor_id, body)


@router.patch(
  '/users/{user_id}',
  response_model=UserOut,
  summary='일반 사용자 이름·부서 수정',
  responses={403: {'model': ErrorOut}, 404: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)
def update_user_account(actor_id: CurrentUserId, user_id: Annotated[int, Path(gt=0)], body: UserUpdateIn) -> UserOut:
  return update_user(actor_id, user_id, body)


@router.get('/users', response_model=UserListOut, summary='일반 사용자 목록 조회')
def list_users(user_id: CurrentUserId, query: Annotated[UserListQuery, Query()]) -> UserListOut:
  return get_users(user_id, query)


@router.get('/departments', response_model=list[DepartmentOut], summary='배정 가능한 활성 부서 조회')
def list_departments(user_id: CurrentUserId) -> list[DepartmentOut]:
  return get_departments(user_id)
