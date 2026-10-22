from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal, Protocol


@dataclass
class SourceLocation:
  page_number: int | None = None  # pdf, docx... 페이지 명
  sheet_name: str | None = None  # xlsx 시트명
  cell_range: str | None = None  # A1:D20


@dataclass
class TextBlock:
  kind: Literal['text'] = field(default='text', init=False)
  text: str
  location: SourceLocation | None = None


@dataclass
class TableBlock:
  kind: Literal['table'] = field(default='table', init=False)
  rows: list[list[str | None]]
  location: SourceLocation | None = None


type DocumentBlock = TextBlock | TableBlock


@dataclass
class ParsedDocument:
  format: Literal['csv', 'docx', 'pdf', 'xlsx']
  blocks: list[DocumentBlock]


class DocumentParser(Protocol):
  def __call__(self, source: BytesIO, /) -> ParsedDocument: ...
