from dataclasses import dataclass
from io import BytesIO

from backend.core.logger import get_logger
from backend.parsers.documents.interface import ParsedDocument

logger = get_logger(__file__)


@dataclass
class Table:
  idx: int
  rows: list[str]


@dataclass
class Page:
  page_num: int
  text: str
  tables: list[Table]


def parse_pdf(source: BytesIO) -> ParsedDocument:
  import pdfplumber

  parsed: list[Page] = []
  with pdfplumber.open(source) as pdf:
    for page_num, page in enumerate(pdf.pages, 1):
      table_list = page.find_tables(table_settings={'vertical_strategy': 'lines', 'horizontal_strategy': 'lines'})

      tables: list[Table] = []
      bboxes = [t.bbox for t in table_list]

      def is_outside(obj, bboxes=bboxes) -> bool:
        center_x = (obj['x0'] + obj['x1']) / 2
        center_y = (obj['top'] + obj['bottom']) / 2
        return not any(x0 <= center_x < x1 and top <= center_y < bottom for x0, top, x1, bottom in bboxes)

      text = (page.filter(is_outside) if bboxes else page).extract_text().strip()
      tables = [
        Table(idx=idx, rows=['\t'.join(cell or '' for cell in row) for row in table.extract()])
        for idx, table in enumerate(table_list, 1)
      ]
      parsed.append(Page(page_num=page_num, text=text, tables=tables))
      page.close()

  log = []
  for page in parsed:
    log.append(f'page num: {page.page_num}')
    log.append(f'texts: {page.text}')
    for table in page.tables:
      log.append(f'table num: {table.idx}')
      for row in table.rows:
        log.append(row + '\n')

  logger.info('\n'.join(log))

  return ParsedDocument(text='\n\n'.join([page.text for page in parsed]))
