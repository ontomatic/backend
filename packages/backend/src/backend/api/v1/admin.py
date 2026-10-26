from typing import Annotated

from backend.api.dependencies import RequestSession
from backend.api.guard import system_admin_required
from backend.schemas.department import DepartmentOut
from backend.schemas.error import ErrorOut
from backend.schemas.user import UserCreateIn, UserListOut, UserListQuery, UserOut, UserUpdateIn
from backend.services.departments import get_departments
from backend.services.users import create_user, get_users, update_user
from fastapi import APIRouter, Depends, Path, Query

router = APIRouter(
  prefix='/admin',
  tags=['admin'],
  dependencies=[Depends(system_admin_required)],
  responses={401: {'model': ErrorOut}, 403: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)


@router.post(
  '/users',
  status_code=201,
  response_model=UserOut,
  summary='일반 사용자 생성',
  responses={409: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)
def create_user_account(session: RequestSession, body: UserCreateIn) -> UserOut:
  return UserOut.model_validate(create_user(session, body))


@router.patch(
  '/users/{user_id}',
  response_model=UserOut,
  summary='일반 사용자 이름·부서 수정',
  responses={403: {'model': ErrorOut}, 404: {'model': ErrorOut}, 422: {'model': ErrorOut}},
)
def update_user_account(session: RequestSession, user_id: Annotated[int, Path(gt=0)], body: UserUpdateIn) -> UserOut:
  return UserOut.model_validate(update_user(session, user_id, body))


@router.get('/users', response_model=UserListOut, summary='일반 사용자 목록 조회')
def list_users(session: RequestSession, query: Annotated[UserListQuery, Query()]) -> UserListOut:
  users, total = get_users(session, query)
  return UserListOut(
    items=[UserOut.model_validate(user) for user in users],
    total=total,
    page=query.page,
    page_size=query.page_size,
  )


@router.get('/departments', response_model=list[DepartmentOut], summary='배정 가능한 활성 부서 조회')
def list_departments(session: RequestSession) -> list[DepartmentOut]:
  return [DepartmentOut.model_validate(department) for department in get_departments(session)]
