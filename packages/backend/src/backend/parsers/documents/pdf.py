from typing import BinaryIO

from backend.parsers.documents.interface import ParsedDocument


def parse_pdf(source: BinaryIO) -> ParsedDocument:
  raise NotImplementedError()
