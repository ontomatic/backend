from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.v1 import router
from backend.core.config import get_settings
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

app.add_middleware(
  CORSMiddleware,
  allow_origin_regex=(
    r'https?://(localhost|127\.0\.0\.1)(:[0-9]+)?' if get_settings().app_env in ('local', 'dev') else None
  ),
  allow_methods=['*'],
  allow_headers=['Authorization', 'Content-Type'],
)


@app.get('/health-check')
def health_check():
  return JSONResponse(status_code=200, content={'status': 'ok'})


app.include_router(router)


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
