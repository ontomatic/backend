from dataclasses import asdict
from io import BytesIO

from backend.parsers.documents.docx import parse_docx
from backend.services.document_formats import reference_table_candidates
from docx import Document


def test_docx_tables_keep_document_number_heading_and_exact_block_without_inventing_pages() -> None:
  # Given a numbered Korean document with several tables, when parsed, then every source block remains distinct.
  doc = Document()
  doc.add_heading('제품사양서', 1)
  metadata = doc.add_table(rows=2, cols=4)
  for row, values in zip(
    metadata.rows, [['문서번호', '사양-01', '버전', '2.0'], ['발행일', '2026-10-23', '담당', '광학팀']], strict=True
  ):
    for cell, value in zip(row.cells, values, strict=True):
      cell.text = value
  doc.add_heading('광학 사양 (렌즈 모듈)', 2)
  table = doc.add_table(rows=2, cols=4)
  for row, values in zip(
    table.rows, [['부품', '구성 상세', '속성', '속성값'], ['렌즈', '24-70mm 줌렌즈', '재질', '광학 유리']], strict=True
  ):
    for cell, value in zip(row.cells, values, strict=True):
      cell.text = value
  doc.add_heading('검사성적서 (1차 모듈)', 1)
  table = doc.add_table(rows=2, cols=5)
  for row, values in zip(
    table.rows, [['공정번호', '공정', '투입', '양품', '불량'], ['공정-07', '광학 조립', '500', '495', '5']], strict=True
  ):
    for cell, value in zip(row.cells, values, strict=True):
      cell.text = value
  with BytesIO() as stream:
    doc.save(stream)
    stream.seek(0)
    parsed = parse_docx(stream)
  blocks = [asdict(block) for block in parsed.blocks]
  candidates = reference_table_candidates('document', blocks)
  optical = next(row for row in candidates['rows'] if row.get('name') == '렌즈')
  assert optical['document_number'] == '사양-01'
  assert optical['section_title'] == '제품사양서 / 광학 사양 (렌즈 모듈)'
  assert optical['block_index'] == 4
  assert optical['page'] is None
  inspection = next(row for row in candidates['rows'] if row.get('process_codes') == '공정-07')
  assert inspection['good_quantity'] == '495'
  assert inspection['defect_quantity'] == '5'
  assert inspection['confirmed'] is False
  assert 'status' not in inspection


def test_docx_preserves_heading_levels_without_guessing_from_paragraph_text() -> None:
  # Given skipped heading levels and repeated body text, when parsed, then only headings carry their level.
  doc = Document()
  doc.add_heading('제품 / 사양', 1)
  doc.add_paragraph('제품 / 사양')
  doc.add_heading('광학 사양', 3)
  doc.add_paragraph('광학 사양')
  with BytesIO() as stream:
    doc.save(stream)
    stream.seek(0)
    parsed = parse_docx(stream)
  assert [block.heading_level for block in parsed.blocks] == [1, None, 3, None]
  assert parsed.blocks[2].location.section_title == '제품 / 사양 / 광학 사양'
