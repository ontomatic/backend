"""Read Korean document tables without treating printed approvals or quantities as workflow actions."""

HEADER_FIELDS = {
  '품목코드': 'item_code',
  '상위 품목코드': 'parent_code',
  '상위 품목': 'parent_code',
  '품목명': 'name',
  '부품': 'name',
  '대당 수량': 'quantity_per_product',
  '소요 수량': 'quantity_per_parent',
  '단위': 'unit',
  '조달·공급': 'procurement',
  '속성': 'field',
  '항목': 'field',
  '속성값': 'value',
  '값': 'value',
  '구성 상세': 'description',
  '공정번호': 'process_codes',
  '관련 공정': 'process_codes',
  '공정': 'process',
  '시작': 'start_date',
  '종료': 'end_date',
  '기간 (근무일)': 'working_days',
  '기간': 'raw_time_range',
  '작업장': 'workplace',
  '작업 내용': 'work_description',
  '투입 → 산출': 'input_output',
  '공정책임자': 'process_owner',
  '담당자': 'assignee',
  '보조담당자': 'assistants',
  '인원': 'headcount',
  '입고 수량': 'received_quantity',
  '투입': 'input_quantity',
  '양품': 'good_quantity',
  '불량': 'defect_quantity',
  '판정': 'raw_result',
  '허용 기준': 'criterion',
  '측정값': 'measured_value',
  '검사자': 'inspector',
  '검사 항목': 'inspection_field',
  '기준': 'criterion',
  '결과': 'raw_result',
  '분류': 'category',
  '확인 내용': 'check_description',
  '순번': 'sequence',
  '순서': 'sequence',
  '비고': 'note',
}


def reference_table_candidates(document_id: str, blocks: list[dict]) -> dict | None:
  candidates = []
  sections: dict[str, dict] = {}
  for block in blocks:
    if block['kind'] != 'table' or len(block.get('rows', [])) < 2:
      continue
    headers = [str(cell or '').strip() for cell in block['rows'][0]]
    if sum(header in HEADER_FIELDS for header in headers) < 2:
      continue
    location = block.get('location') or {}
    number = location.get('document_number')
    if number:
      sections[number] = {'document_number': number, 'section_title': location.get('section_title')}
    for index, values in enumerate(block['rows'][1:], start=2):
      if not any(values):
        continue
      original = dict(zip(headers, values, strict=False))
      row = {HEADER_FIELDS.get(header, header): value for header, value in original.items()}
      row.update(
        document_id=document_id,
        block_index=location.get('block_index'),
        page=location.get('page_number'),
        row=str(index),
        section_title=location.get('section_title'),
        document_number=number,
        original=original,
        confirmed=False,
      )
      candidates.append(row)
  if not candidates:
    return None
  return {
    'rows': candidates,
    'sections': list(sections.values()),
    'warnings': [
      '문서번호·문서 버전·공정번호와 품목별 사양 버전·생산/검사회차는 별도로 확인합니다.',
      '양품·불량·인쇄된 합격/서명은 원문 후보입니다. 생산 완료·품질판정을 자동 처리하지 않습니다.',
      '대당 수량·개·대분·매의 기준을 구분하며 근무일·날짜만 있는 일정에 시각·작업 달력을 추정하지 않습니다.',
      'DOCX는 실제 페이지를 추정하지 않고 문서번호·소제목·문단/표 블록·행으로 근거를 연결합니다.',
    ],
  }
