from io import BytesIO

from backend.parsers.documents.interface import DocumentBlock, ParsedDocument, SourceLocation, TableBlock, TextBlock


def parse_docx(source: BytesIO) -> ParsedDocument:
  from docx import Document
  from docx.table import Table
  from docx.text.paragraph import Paragraph

  doc = Document(source)

  blocks: list[DocumentBlock] = []
  headings: dict[int, str] = {}
  document_number: str | None = None

  for item in doc.iter_inner_content():
    if isinstance(item, Paragraph) and item.text.strip():
      style = item.style.name if item.style else ''
      level = None
      if style.startswith('Heading ') and style.rsplit(' ', 1)[-1].isdigit():
        level = int(style.rsplit(' ', 1)[-1])
        headings = {depth: title for depth, title in headings.items() if depth < level}
        headings[level] = item.text
        if level == 1:
          document_number = None
      blocks.append(
        TextBlock(
          text=item.text,
          heading_level=level,
          location=SourceLocation(
            block_index=len(blocks) + 1,
            section_title=' / '.join(headings.values()) or None,
            document_number=document_number,
          ),
        )
      )

    elif isinstance(item, Table):
      rows: list[list[str | None]] = []
      for row in item.rows:
        values: list[str | None] = [None] * row.grid_cols_before
        values.extend(cell.text for cell in row.cells)
        values.extend([None] * row.grid_cols_after)
        rows.append(values)

      for row in rows[:3]:
        for index, value in enumerate(row[:-1]):
          if value == '문서번호':
            document_number = row[index + 1]
      blocks.append(
        TableBlock(
          rows=rows,
          location=SourceLocation(
            block_index=len(blocks) + 1,
            section_title=' / '.join(headings.values()) or None,
            document_number=document_number,
          ),
        )
      )

  return ParsedDocument(format='docx', blocks=blocks)
