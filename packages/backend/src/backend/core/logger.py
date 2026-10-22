import logging
import sys

_FORMAT = '%(asctime)s %(levelname)-8s %(name)s: %(message)s\n'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
_NOISY = ('httpx', 'httpcore', 'urllib3', 'asyncio')
_handler: logging.StreamHandler | None = None


def setup_logger(level: int = logging.INFO, stream=None) -> None:
  global _handler
  output = sys.stdout if stream is None else stream
  if _handler is None:
    _handler = logging.StreamHandler(output)
    _handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
  else:
    _handler.setStream(output)

  root = logging.getLogger()
  root.setLevel(level)
  root.addHandler(_handler)

  for name in _NOISY:
    logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
  return logging.getLogger(name)
