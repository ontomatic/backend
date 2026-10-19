from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.v1.auth import router as auth_router
from backend.api.v1.chat import router as chat_router
from backend.core.logger import setup_logger
from backend.exceptions.base import AppException
from backend.integrations.langfuse import initialize_langfuse, shutdown_langfuse
from backend.schemas.error import ErrorDetail, ErrorOut

setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  initialize_langfuse()
  try:
    yield
  finally:
    shutdown_langfuse()


app = FastAPI(
  lifespan=lifespan,
  responses={422: {'model': ErrorOut}},
)
app.include_router(auth_router, prefix='/api/v1')
app.include_router(chat_router, prefix='/api/v1')


@app.exception_handler(AppException)
async def app_exception_handler(_req: Request, exc: AppException) -> JSONResponse:
  headers = {'WWW-Authenticate': 'Bearer'} if exc.status_code == 401 else None

  return JSONResponse(
    status_code=exc.status_code,
    content=ErrorOut(code=exc.code, message=exc.message).model_dump(),
    headers=headers,
  )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_req: Request, exc: RequestValidationError) -> JSONResponse:
  return JSONResponse(
    status_code=422,
    content=ErrorOut(
      code='VALIDATION_ERROR',
      message='입력값이 올바르지 않습니다.',
      errors=[ErrorDetail(loc=err['loc'][1:], msg=err['msg']) for err in exc.errors()],
    ).model_dump(),
  )
