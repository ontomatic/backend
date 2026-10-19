def main() -> None:
  import uvicorn

  uvicorn.run('api.app:app', reload=True)
