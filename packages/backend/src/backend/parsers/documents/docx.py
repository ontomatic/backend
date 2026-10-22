from io import BytesIO

from backend.parsers.documents.interface import ParsedDocument


def parse_docx(source: BytesIO) -> ParsedDocument:
  raise NotImplementedError()
