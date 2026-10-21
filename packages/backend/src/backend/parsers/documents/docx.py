from typing import BinaryIO

from backend.parsers.documents.interface import ParsedDocument


def parse_docx(source: BinaryIO) -> ParsedDocument:
  raise NotImplementedError()
