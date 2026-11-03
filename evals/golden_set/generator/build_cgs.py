"""Generate a new Word bundle with Python; existing output is never overwritten."""

import argparse
import os
import tempfile
from pathlib import Path

from docx import Document
from docx.document import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

from evals.golden_set.generator.make_golden import CFG, ORG_ROLE, PEOPLE, build, clean, stage_name


def new_document() -> WordDocument:
  document = Document()
  section = document.sections[0]
  section.page_width, section.page_height = Cm(21), Cm(29.7)
  section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Cm(2)
  for name, size in [('Normal', 10), ('Heading 1', 17), ('Heading 2', 11)]:
    style = document.styles[name]
    style.font.name = 'Malgun Gothic'
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string('000000')
    style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Malgun Gothic')
  document.core_properties.author = '온토메틱'
  footer = section.footer.paragraphs[0]
  footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
  field = OxmlElement('w:fldSimple')
  field.set(qn('w:instr'), 'PAGE')
  footer._p.append(field)
  return document


def table(document: WordDocument, headers: list[str], rows: list[list], *, header: bool = True) -> None:
  data = [headers, *rows] if header else rows
  output = document.add_table(rows=0, cols=len(headers))
  output.style = 'Table Grid'
  for index, values in enumerate(data):
    row = output.add_row()
    for cell, value in zip(row.cells, values, strict=True):
      cell.text = str(value).replace('|', '\n')
      for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_after = Pt(0)
        for run in paragraph.runs:
          run.font.size = Pt(9)
          run.bold = header and index == 0
      if header and index == 0:
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), 'D9E2F3')
        cell._tc.get_or_add_tcPr().append(shading)
    if header and index == 0:
      row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))


def organization(document: WordDocument, model: str, config: dict) -> None:
  rows = [[department, title, name, ORG_ROLE[key]] for key, (department, name, title) in PEOPLE.items()]
  rows.append(
    [
      '생산부서',
      '파트장 (공정책임자)',
      '\n'.join(CFG['leaders'].values()),
      '\n'.join(f'{stage} 공정 책임' for stage in ('1차 모듈', '2차 모듈', '완제품')),
    ]
  )
  count = len(config['owner']) + sum(len(names) for names in config['assist'].values())
  rows.append(
    [
      ('생산부서'),
      ('작업자'),
      (f'{count}명'),
      (f'{model} 라인의 공정별 담당자·보조담당자 (생산계획서의 작업자 배정표)'),
    ]
  )
  table(document, ['부서', '직책', '이름', '맡은 일'], rows)


def early_lines(source: dict, config: dict) -> list[str]:
  tasks = {t['id']: t for t in source['tasks']}
  output = []
  for stage, next_stage in [('M1', 'M2'), ('M2', 'F')]:
    previous = [tasks[f'공정-{n}'] for item in config['items'] if item['stage'] == stage for n in item['ids']]
    approval = max(t['end'] for t in previous)
    for item in config['items']:
      if item['stage'] == next_stage:
        for number in item['ids']:
          task = tasks[f'공정-{number}']
          if task['start'] <= approval:
            output.append(
              f'※ {task["id"]} {task["name"]}은 검사성적서 결재일({approval}) 전에 시작합니다. '
              '투입 공정은 먼저 끝나 검사 판정을 마쳤고, 문서 결재는 단계의 마지막 공정이 끝난 날에 합니다.'
            )
  return output


def render(document: WordDocument, expected: dict, source: dict, config: dict, image: Path) -> None:
  info = expected['documents'][0]
  table(document, ['담당', '검토', '승인'], [[f'{a["name"]}\n{a["title"]}\n{a["date"]}' for a in info['approval']]])
  document.add_heading(info['title'], level=1).alignment = WD_ALIGN_PARAGRAPH.CENTER
  meta = list(info['meta'].items())
  rows = []
  for i in range(0, len(meta), 2):
    pair = [*meta[i], *(meta[i + 1] if i + 1 < len(meta) else ('', ''))]
    rows.append(pair)
  table(document, ['', '', '', ''], rows, header=False)
  kind = info['kind']
  if kind == 'spec':
    picture = document.add_picture(str(image), width=Inches(1.6))
    picture._inline.docPr.set('descr', f'{source["model"]} 카메라 외관 콘셉트')
    document.add_heading('모델 개요', level=2)
    overview = [['모델명 / 제품군', f'{source["model"]} / {source["family"]}'], ['용도', clean(source['intro'])]]
    for label, part in [('렌즈', '렌즈'), ('이미지 센서', '센서 칩'), ('셔터', '셔터막'), ('화면', '보호 커버')]:
      detail = next((r[1] for s in source['sections'] for r in s['rows'] if r[0] == part), '해당 없음')
      overview.append([label, clean(detail)])
    table(document, ['항목', '값'], overview)
    for i, section in enumerate(source['sections'], 1):
      suffix = f' ({section["m2"]} 모듈)' if section['m2'] and section['m2'] != '부속품' else ''
      title = f'{i:02d}. {section["m1"].removesuffix("부")} 사양{suffix}'
      document.add_heading(title, level=2)
      table(document, ['부품', '구성 상세', '속성', '속성값'], [[clean(v) for v in r] for r in section['rows']])
  elif kind == 'bom':
    document.add_heading('구성', level=2)
    rows = [
      [
        p['seq'],
        p['code'],
        f'{p["name"]} ({p["spec"]})',
        p['qtyPerUnit'],
        f'구매 · {p["supplier"]}' if p['sourcing'] == '구매' else f'자체 가공 ({p["taskId"]})',
      ]
      for p in expected['parts']
    ]
    table(document, ['순번', '품목코드', '품목명', '대당 수량', '조달·공급'], rows)
    document.add_heading('양산 이관 확인', level=2)
    table(document, ['확인 항목', '담당', '상태'], [[r['item'], r['owner'], r['status']] for r in expected['handover']])
    document.add_heading('조직', level=2)
    organization(document, source['model'], config)
    table(
      document,
      ['R&D부서', '생산부서', '품질부서'],
      [[f'{PEOPLE[key][1]} {PEOPLE[key][2]}\n서명 완료 {info["date"]}' for key in ('RD_HEAD', 'PRD_HEAD', 'QA_HEAD')]],
    )
  elif kind == 'iqc':
    table(
      document,
      ['부품', '입고 수량', '확인 내용', '판정'],
      [[r['part'], f'{r["qty"]:,}개', r['check'], r['verdict']] for r in expected['iqc']],
    )
  elif kind == 'plan':
    document.add_heading('생산계획', level=2)
    table(
      document,
      ['품목', '수량', '시작', '종료'],
      [
        [m['name'], f'{m["qty"]:,}{"대" if m["name"] == "완제품 공정" else "개"}', m['start'], m['end']]
        for m in expected['modules']
      ],
    )
    document.add_heading('작업 일정', level=2)
    table(
      document,
      ['공정번호', '공정', '시작', '종료', '기간 (근무일)', '선행 작업'],
      [[t['id'], t['name'], t['start'], t['end'], t['days'], ', '.join(t['preds']) or '—'] for t in expected['tasks']],
    )
    for text in early_lines(source, config):
      document.add_paragraph(text)
    document.add_heading('작업자 배정표', level=2)
    leaders = {m['name']: m['leader'] for m in expected['modules']}
    table(
      document,
      ['품목', '공정', '기간', '공정책임자', '담당자', '보조담당자', '인원'],
      [
        [
          t['module'],
          f'{t["id"]} {t["name"]}',
          f'{t["start"]} ~ {t["end"]}',
          leaders[t['module']],
          t['owner'],
          ', '.join(t['assistants']) or '—',
          t['crew'],
        ]
        for t in expected['tasks']
      ],
    )
  elif kind == 'route':
    selected = {t['id'] for t in expected['tasks']}
    tasks = {t['id']: t for t in source['tasks']}
    for item in config['items']:
      if not any(f'공정-{n}' in selected for n in item['ids']):
        continue
      document.add_heading(item['name'], level=2)
      rows = []
      merged = item.get('merge', [])
      for number in item['ids']:
        task = tasks[f'공정-{number}']
        if merged and number == merged[1]:
          continue
        if number in config['steps']:
          for name, work, inputs, outputs, check in config['steps'][number]:
            rows.append(
              [
                len(rows) + 1,
                task['id'],
                f'{name}\n({task["name"]})',
                work.replace('{MODEL}', source['model']),
                task['line'],
                f'{inputs} → {outputs}'.replace('{MODEL}', source['model']),
                check,
              ]
            )
          continue
        identifier, name, work = task['id'], task['name'], task['work']
        inputs, outputs = task['input'], task['output']
        if merged and number == merged[0]:
          other = tasks[f'공정-{merged[1]}']
          identifier += f', {other["id"]}'
          name = f'{task["name"].removesuffix(" 조립")}·{other["name"]}'
          work += f' / {other["work"]}'
          inputs += f', {other["input"]}'
          outputs += f', {other["output"]}'
        rows.append(
          [
            len(rows) + 1,
            identifier,
            f'{name}\n({stage_name(task["stage"])})',
            work,
            task['line'],
            f'{inputs} → {outputs}',
            config['check'].get(number, '-'),
          ]
        )
      table(document, ['순서', '공정번호', '공정', '작업 내용', '작업장', '투입 → 산출', '확인 내용'], rows)
  elif kind == 'qc':
    selected = {t['id'] for t in expected['tasks']}
    for item in config['items']:
      records = [t for t in expected['tasks'] if t['module'] == item['name']]
      if not records:
        continue
      document.add_heading(item['name'], level=2)
      table(
        document,
        ['공정번호', '공정', '투입', '양품', '불량'],
        [[t['id'], t['name'], t['inQty'], t['good'], t['bad']] for t in records],
      )
      inspections = [r for r in expected['inspections'] if r['taskId'] in {t['id'] for t in records}]
      if inspections:
        table(
          document,
          ['항목', '공정번호', '허용 기준', '측정값', '검사자', '판정'],
          [[r['item'], r['taskId'], r['standard'], r['value'], r['inspector'], r['verdict']] for r in inspections],
        )
    for unit in expected['units']:
      document.add_heading(f'점검표 · 제품번호 {unit["serial"]}', level=2)
      table(
        document,
        ['분류', '관련 공정', '검사 항목', '기준', '결과'],
        [[r['cls'], '\n'.join(r['taskIds']), r['item'], r['standard'], r['result']] for r in unit['checks']],
      )
    document.add_heading('단계별 수량 종합', level=2)
    rows = []
    tasks = {t['id']: t for t in source['tasks']}
    causes = {m['name']: m['badCause'] for m in expected['modules']}
    for item in config['items']:
      identifiers = [f'공정-{n}' for n in item['ids']]
      if not selected.intersection(identifiers):
        continue
      finals = [n for n in identifiers if not any(n in tasks[t]['preds'] for t in identifiers)]
      good = min(config['rec'][n[-2:]][1] for n in finals)
      bad = sum(config['rec'][n[-2:]][2] for n in identifiers)
      inputs = config['rec'][identifiers[0][-2:]][0]
      rows.append(
        [item['name'], '\n'.join(finals), f'{good} / {inputs}', f'{bad}개' if bad else '', causes[item['name']] or '']
      )
    table(document, ['구분', '공정번호', '양품 / 투입', '불합격 제품 개수', '비고'], rows)
    for text in early_lines(source, config):
      document.add_paragraph(text)
    if expected['units']:
      document.add_paragraph(f'{source["model"]} 완성일 {info["date"]}')
  if kind in ('iqc', 'qc'):
    basis = f'구매 부품 {len(expected["iqc"])}종 전부 합격' if kind == 'iqc' else ''
    table(document, ['', '', ''], [['종합 판정', '☑ 합격      ☐ 불합격', basis]], header=False)


def generate(output: Path, source_file: Path, *, split: bool = False) -> None:
  if output.exists():
    raise FileExistsError(f'기존 출력은 덮어쓰지 않습니다: {output}')
  model, goldens, _, source = build(str(source_file))
  config = CFG['models'][model]
  image = source_file.with_name(f'{model.split("-")[1].lower()}_image.jpg')
  output.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='.camera-docs-', dir=output.parent) as temporary:
    stage = Path(temporary)
    combined = new_document()
    combined.add_paragraph(f'온토메틱 {model} 문서 {len(goldens)}종')
    combined.add_paragraph(f'완성일 {max(t["end"] for t in source["tasks"])}')
    organization(combined, model, config)
    for name, golden in goldens:
      document = new_document() if split else combined
      if not split:
        document.add_page_break()
      render(document, golden.expected(), source, config, image)
      if split:
        document.save(str(stage / name))
    if not split:
      combined.add_paragraph('부록 작성 근거')
      combined.add_paragraph(
        '자료는 모델 입력 JSON과 cgs_models.json을 따릅니다. 가상 값과 설계 값은 골든 src에 구분됩니다.'
      )
      combined.save(str(stage / output.name))
    if split:
      os.rename(stage, output)
    else:
      os.link(stage / output.name, output)


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('output', type=Path)
  parser.add_argument('source', type=Path)
  parser.add_argument('--split', action='store_true')
  args = parser.parse_args()
  generate(args.output, args.source, split=args.split)
  print(f'생성 완료: {args.output}')


if __name__ == '__main__':
  main()
