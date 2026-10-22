from io import BytesIO

from backend.parsers.documents.interface import DocumentBlock, ParsedDocument, TableBlock, TextBlock


def parse_docx(source: BytesIO) -> ParsedDocument:
  from docx import Document
  from docx.table import Table
  from docx.text.paragraph import Paragraph

  doc = Document(source)

  blocks: list[DocumentBlock] = []

  for item in doc.iter_inner_content():
    if isinstance(item, Paragraph) and item.text.strip():
      blocks.append(TextBlock(text=item.text))

    elif isinstance(item, Table):
      rows: list[list[str | None]] = []
      for row in item.rows:
        values: list[str | None] = [None] * row.grid_cols_before
        values.extend(cell.text for cell in row.cells)
        values.extend([None] * row.grid_cols_after)
        rows.append(values)

      blocks.append(TableBlock(rows=rows))

  return ParsedDocument(format='docx', blocks=blocks)
