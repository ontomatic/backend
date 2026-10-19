from fastapi import FastAPI

from backend.core.logger import setup_logger

setup_logger()

app = FastAPI()
