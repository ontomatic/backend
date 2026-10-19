from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.v1.auth import router as auth_router
from backend.core.logger import setup_logger
from backend.exceptions.base import AppException
from backend.integrations.langfuse import initialize_langfuse, shutdown_langfuse
from backend.schemas.error import ErrorOut

setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  initialize_langfuse()
  try:
    yield
  finally:
    shutdown_langfuse()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router, prefix='/api/v1')


@app.exception_handler(AppException)
async def app_exception_handler(req: Request, exc: AppException) -> JSONResponse:
  headers = {'WWW-Authenticate': 'Bearer'} if exc.status_code == 401 else None

  return JSONResponse(
    status_code=exc.status_code,
    content=ErrorOut(code=exc.code, message=exc.message).model_dump(),
    headers=headers,
  )
