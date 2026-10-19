from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.logger import setup_logger
from backend.integrations.langfuse import initialize_langfuse, shutdown_langfuse

setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  initialize_langfuse()
  try:
    yield
  finally:
    shutdown_langfuse()


app = FastAPI(lifespan=lifespan)
