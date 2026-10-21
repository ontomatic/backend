from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass
class ParsedDocument:
  pass


class DocumentParser(Protocol):
  def __call__(self, source: bytes, /) -> ParsedDocument: ...
