import json
from html.parser import HTMLParser
from io import BytesIO
from urllib.request import Request, urlopen
from uuid import uuid4

from backend.parsers.documents.interface import DocumentBlock, ParsedDocument, SourceLocation, TableBlock, TextBlock
from pydantic import BaseModel, Field


class _Content(BaseModel):
  text: str
  html: str


class _Element(BaseModel):
  category: str
  page: int | None = Field(default=None, ge=1)
  content: _Content


class _Response(BaseModel):
  elements: list[_Element]


class _TableParser(HTMLParser):
  def __init__(self) -> None:
    super().__init__()
    self.rows: list[list[tuple[str, int, int]]] = []
    self.text: list[str] | None = None
    self.colspan = self.rowspan = 1
    self.depth = 0

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    if tag == 'table':
      self.depth += 1
      # shortcut: nested tables are rejected; add recursive blocks when such documents are required.
      if self.depth > 1:
        raise ValueError('Nested Upstage tables are unsupported.')
    elif tag == 'tr':
      self.rows.append([])
    elif tag in ('td', 'th'):
      if not self.rows or self.text is not None:
        raise ValueError('Invalid Upstage table cell.')
      attributes = dict(attrs)
      self.colspan = int(attributes.get('colspan') or '1')
      self.rowspan = int(attributes.get('rowspan') or '1')
      if not 1 <= self.colspan <= 1000 or self.rowspan < 1:
        raise ValueError('Invalid Upstage table span.')
      self.text = []
    elif tag == 'br' and self.text is not None:
      self.text.append('\n')

  def handle_endtag(self, tag: str) -> None:
    if tag == 'table':
      self.depth -= 1
    elif tag in ('td', 'th') and self.text is not None:
      self.rows[-1].append((''.join(self.text).strip(), self.colspan, self.rowspan))
      self.text = None
    elif tag in ('p', 'div', 'li') and self.text is not None:
      self.text.append('\n')

  def handle_data(self, data: str) -> None:
    if self.text is not None:
      self.text.append(data)

  def table_rows(self) -> list[list[str | None]]:
    grid: dict[tuple[int, int], str] = {}
    for row_index, cells in enumerate(self.rows):
      column = 0
      for text, colspan, rowspan in cells:
        while (row_index, column) in grid:
          column += 1
        for row in range(row_index, min(row_index + rowspan, len(self.rows))):
          for col in range(column, column + colspan):
            if (row, col) in grid:
              raise ValueError('Overlapping Upstage table cells.')
            grid[row, col] = text
        column += colspan
    if not grid or self.text is not None:
      raise ValueError('Missing or incomplete Upstage table HTML.')
    width = max(col for _, col in grid) + 1
    return [[grid.get((row, col)) for col in range(width)] for row in range(len(self.rows))]


class UpstageParser:
  def __init__(self, file_format: str, api_key: str, base_url: str) -> None:
    self.file_format = file_format
    self.api_key = api_key
    self.base_url = base_url.rstrip('/')

  def __call__(self, source: BytesIO, /) -> ParsedDocument:
    boundary = uuid4().hex
    parts = [
      f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
      for name, value in {'model': 'document-parse', 'output_formats': '["text", "html"]'}.items()
    ]
    parts.extend(
      [
        (
          f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
          f'filename="document.{self.file_format}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode(),
        source.read(),
        f'\r\n--{boundary}--\r\n'.encode(),
      ]
    )
    request = Request(
      f'{self.base_url}/document-digitization',
      data=b''.join(parts),
      headers={
        'Authorization': f'Bearer {self.api_key}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Accept': 'application/json',
      },
      method='POST',
    )
    with urlopen(request, timeout=120) as response:
      result = _Response.model_validate(json.load(response))

    blocks: list[DocumentBlock] = []
    for element in result.elements:
      location = SourceLocation(page_number=element.page, block_index=len(blocks) + 1)
      if element.category == 'table':
        table = _TableParser()
        table.feed(element.content.html)
        table.close()
        blocks.append(TableBlock(rows=table.table_rows(), location=location))
      elif text := element.content.text.strip():
        blocks.append(TextBlock(text=text, location=location))
    return ParsedDocument(format=self.file_format, blocks=blocks)
