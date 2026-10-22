from io import BytesIO, TextIOWrapper

from backend.parsers.documents.interface import ParsedDocument, TableBlock


def parse_csv(source: BytesIO) -> ParsedDocument:
  import csv

  text_source = TextIOWrapper(source, encoding='utf-8')
  try:
    reader = csv.reader(text_source)
    block = TableBlock(rows=[list(row) for row in reader], location=None)
    return ParsedDocument(format='csv', blocks=[block])
  finally:
    text_source.detach()
