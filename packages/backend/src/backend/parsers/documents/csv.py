import csv
from io import StringIO

from backend.parsers.documents.interface import ParsedDocument


def parse_csv(source: bytes) -> ParsedDocument:
  try:
    text = source.decode('utf-8-sig')
  except UnicodeDecodeError:
    text = source.decode('cp949')

  reader = csv.reader(StringIO(text, newline=''))
  raise NotImplementedError()
