from collections import defaultdict
from io import BytesIO
from typing import Any, cast

from backend.parsers.documents.interface import DocumentBlock, ParsedDocument, SourceLocation, TableBlock, TextBlock


def parse_pdf(source: BytesIO) -> ParsedDocument:
  import pdfplumber
  from camelot.core import Table
  from camelot.io import read_pdf

  tables_by_page: dict[int, list[Table]] = defaultdict(list)
  for table in read_pdf(source, pages='all', flavor='hybrid'):
    tables_by_page[cast(int, table.page)].append(table)

  blocks: list[DocumentBlock] = []
  with pdfplumber.open(source) as pdf:
    for page_num, page in enumerate(pdf.pages, 1):
      tables = tables_by_page[page_num]
      bboxes = []
      for table in tables:
        x0, y0, x1, y1 = cast(tuple[float, float, float, float], table._bbox)
        bboxes.append((x0, page.height - y1, x1, page.height - y0))

      def is_outside(obj: dict[str, Any], bboxes: list[tuple[float, float, float, float]] = bboxes) -> bool:
        center_x = (obj['x0'] + obj['x1']) / 2
        center_y = (obj['top'] + obj['bottom']) / 2
        return not any(x0 <= center_x < x1 and top <= center_y < bottom for x0, top, x1, bottom in bboxes)

      text = ((page.filter(is_outside) if bboxes else page).extract_text() or '').strip()
      if text:
        blocks.append(TextBlock(text=text, location=SourceLocation(page_number=page_num)))

      table_blocks = [
        TableBlock(rows=t.df.values.tolist(), location=SourceLocation(page_number=page_num)) for t in tables
      ]
      blocks.extend(table_blocks)

      page.close()

  return ParsedDocument(format='pdf', blocks=blocks)
