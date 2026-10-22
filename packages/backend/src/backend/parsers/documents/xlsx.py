from io import BytesIO

from backend.parsers.documents.interface import ParsedDocument


def parse_xlsx(source: BytesIO) -> ParsedDocument:
  raise NotImplementedError()
