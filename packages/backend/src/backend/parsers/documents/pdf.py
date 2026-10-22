from io import BytesIO

from backend.parsers.documents.interface import DocumentBlock, ParsedDocument, SourceLocation, TableBlock, TextBlock


def parse_pdf(source: BytesIO) -> ParsedDocument:
  import pdfplumber

  blocks: list[DocumentBlock] = []
  with pdfplumber.open(source) as pdf:
    for page_num, page in enumerate(pdf.pages, 1):
      tables = page.find_tables(table_settings={'vertical_strategy': 'lines', 'horizontal_strategy': 'lines'})
      bboxes = [t.bbox for t in tables]

      def is_outside(obj, bboxes=bboxes) -> bool:
        center_x = (obj['x0'] + obj['x1']) / 2
        center_y = (obj['top'] + obj['bottom']) / 2
        return not any(x0 <= center_x < x1 and top <= center_y < bottom for x0, top, x1, bottom in bboxes)

      text = (page.filter(is_outside) if bboxes else page).extract_text().strip()
      if text:
        blocks.append(TextBlock(text=text, location=SourceLocation(page_number=page_num)))

      table_blocks = [TableBlock(rows=t.extract(), location=SourceLocation(page_number=page_num)) for t in tables]
      blocks.extend(table_blocks)

      page.close()

  return ParsedDocument(format='pdf', blocks=blocks)
