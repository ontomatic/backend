from dataclasses import dataclass
from io import BytesIO
from typing import Protocol


@dataclass
class ParsedDocument:
  text: str


class DocumentParser(Protocol):
  def __call__(self, source: BytesIO, /) -> ParsedDocument: ...
