from pathlib import Path


def main() -> None:
  import uvicorn

  ROOT = Path(__file__).resolve().parent
  uvicorn.run('backend.app:app', reload=True, reload_dirs=[str(ROOT)])
