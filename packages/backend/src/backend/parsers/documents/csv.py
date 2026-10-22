from io import BytesIO, TextIOWrapper

from backend.parsers.documents.interface import ParsedDocument


def parse_csv(source: BytesIO) -> ParsedDocument:
  import csv

  text_source = TextIOWrapper(source, encoding='utf-8')

  try:
    reader = csv.reader(text_source)
    text = '\n'.join([', '.join(row) for row in reader])
    return ParsedDocument(text=text)
  finally:
    text_source.detach()
