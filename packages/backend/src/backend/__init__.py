def main() -> None:
  import uvicorn

  uvicorn.run('backend.app:app', reload=True)
