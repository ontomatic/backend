"""Generate R01–R17 document mutations in a new output directory.
Existing data is never deleted or overwritten."""

import argparse
import glob
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', 'data'))
OUT = os.path.join(DATA, 'wrong_set')
MODELS = ['LO-D100', 'LO-T400', 'LO-F35', 'LO-I100', 'LO-D200']
# R16(부품이 어느 모듈에도 없음)은 사양서에 '부속품' 소제목이 있어야 시험할 수 있다 (T400
# 사양서도 다른 모델과 같은 형식으로 정리했다).
# 작업 순서에서 빼 볼 부품: 그 부품이 들어가는 1차 모듈 조립 공정이 하나뿐이고 사양서 소제목 줄에 있는 것
R16_PART = {'LO-D100': '센서 칩', 'LO-T400': '센서 칩', 'LO-F35': '셔터막', 'LO-I100': '셔터막', 'LO-D200': '센서 칩'}
TITLE = dict(
  spec='제품사양서',
  bom='BOM 및 양산 이관',
  iqc='수입검사성적서',
  plan='생산계획서',
  ops1='작업 순서 (1차 모듈)',
  qc1='검사성적서 (1차 모듈)',
  ops2='작업 순서 (2차 모듈)',
  qc2='검사성적서 (2차 모듈)',
  qcf='검사성적서 (완제품)',
)
APPR = ['담당', '검토', '승인']


def cell_text(c):
  return '\n'.join(p.text for p in c.paragraphs)


def set_cell(cell, to):
  parts = to.split('\n')
  ps = cell.paragraphs
  if len(parts) > len(ps):
    raise ValueError(f'문단 {len(ps)}개인 칸에 {len(parts)}줄을 넣을 수 없음')
  for i, p in enumerate(ps):
    text = parts[i] if i < len(parts) else ''
    if p.runs:
      p.runs[0].text = text
      for r in p.runs[1:]:
        r.text = ''
    else:
      p.add_run(text)


def apply(d, at, to):
  if 'para' in at:
    p = next((p for p in d.paragraphs if p.text.strip() == at['para']), None)
    if p is None:
      raise ValueError(f'문단 없음: {at["para"]}')
    p.runs[0].text = to(p.text) if callable(to) else to
    for r in p.runs[1:]:
      r.text = ''
    return
  hdr = at['hdr']
  tbs = [t for t in d.tables if [cell_text(c) for c in t.rows[0].cells][: len(hdr)] == hdr]
  if not tbs:
    raise ValueError(f'표 없음: {hdr}')
  if 'row' in at:
    row = next((r for t in tbs for r in t.rows if any(cell_text(c) == at['row'] for c in r.cells)), None)
    if row is None:
      raise ValueError(f'줄 없음: {at["row"]}')
  else:
    row = tbs[0].rows[at['ri']]
  cell = row.cells[at['col']]
  set_cell(cell, to(cell_text(cell)) if callable(to) else to)


def heading_of(d, part):
  """사양서에서 그 부품 줄이 든 표 바로 앞의 소제목"""
  last = None
  for child in d.element.body.iterchildren():
    tag = child.tag.split('}')[1]
    if tag == 'p':
      p = Paragraph(child, d)
      if p.style.name.startswith('Heading 2'):
        last = p.text.strip()
    elif tag == 'tbl' and any(cell_text(r.cells[0]) == part for r in Table(child, d).rows):
      return last
  raise ValueError(f'사양서에 {part} 줄이 없음')


def model_folder(model):
  """문서 폴더는 '모델명(카메라분류)' (예: LO-D100(디지털카메라))"""
  found = [
    d for d in os.listdir(DATA) if (d == model or d.startswith(model + '(')) and os.path.isdir(os.path.join(DATA, d))
  ]
  if len(found) != 1:
    raise SystemExit(f'{DATA} 안에 {model}(…) 폴더가 하나가 아님: {found}')
  return os.path.join(DATA, found[0])


def build_cases(model, ctx):
  goldens = {
    unicodedata.normalize('NFC', path.name): json.loads(path.read_text(encoding='utf-8'))['expected']
    for path in Path(model_folder(model)).glob('*.golden.json')
  }
  g = {key: goldens[unicodedata.normalize('NFC', name[:-5] + '.golden.json')] for key, name in ctx['file'].items()}
  T = g['plan']['tasks']
  parts = g['bom']['parts']
  iqc = g['iqc']['iqc']
  DN = ctx['docno']

  def tid(pred):
    return next(t for t in T if pred(t))

  chain = tid(lambda t: t['preds'])  # 선행 공정이 있는 첫 공정
  pred_end = next(t['end'] for t in T if t['id'] == chain['preds'][0])
  longer = tid(lambda t: t['days'] >= 2)  # 기간 2일 이상인 첫 공정
  own = next(p for p in parts if p['sourcing'] == '자체 가공')  # 자체 가공 부품 (수입검사 대상 아님)
  buy = next(p for p in parts if p['sourcing'] == '구매')
  qc1_ins = next(i for i in g['qc1']['inspections'] if i['doc'] == DN['qc1'])
  crew_row = 1  # 작업자 배정표 첫 공정 줄
  cases = []

  def case(cid, desc, edits, rules):
    cases.append((cid, desc, edits, rules))

  case(
    'R01-형식',
    "생산계획서 문서번호에서 '-'를 지움",
    [('plan', dict(hdr=['문서번호'], ri=0, col=1), lambda s: s.replace('-', ''))],
    ['R01'],
  )
  case(
    'R01-중복',
    '검사성적서(1차) 문서번호를 작업 순서(1차 모듈)와 같은 번호로',
    [('qc1', dict(hdr=['문서번호'], ri=0, col=1), DN['ops1'])],
    ['R01'],
  )
  case(
    'R02-결재란빈칸',
    '수입검사성적서 담당 결재 칸(이름·직책·날짜)을 비움',
    [('iqc', dict(hdr=APPR, ri=1, col=0), '\n\n')],
    ['R02'],
  )
  case(
    'R03-결재일',
    '작업 순서(1차) 담당 결재일을 다른 날(2026-01-01)로',
    [('ops1', dict(hdr=APPR, ri=1, col=0), lambda s: '\n'.join(s.split('\n')[:2] + ['2026-01-01']))],
    ['R03'],
  )
  case(
    'R04-조직표에없는결재자',
    "검사성적서(완제품) 검토 결재자를 조직에 없는 '김아무개'로",
    [('qcf', dict(hdr=APPR, ri=1, col=1), lambda s: '\n'.join(['김아무개'] + s.split('\n')[1:]))],
    ['R04'],
  )
  case('R05-발행일형식', "BOM 발행일을 '10/27'로", [('bom', dict(hdr=['문서번호'], ri=1, col=1), '10/27')], ['R05'])
  case(
    'R05-공정시작일',
    f"생산계획서 {chain['id']} 시작일을 '10월30일'로",
    [('plan', dict(hdr=['공정번호', '공정'], row=chain['id'], col=2), '10월30일')],
    ['R05'],
  )
  case(
    'R06-품목코드',
    "BOM 3번째 부품 품목코드를 '부품-33'으로",
    [('bom', dict(hdr=['순번', '품목코드'], ri=3, col=1), '부품-33')],
    ['R06'],
  )
  case(
    'R06-대당수량',
    f'BOM {own["name"]} 대당 수량을 0으로',
    [('bom', dict(hdr=['순번', '품목코드'], ri=own['seq'], col=3), '0')],
    ['R06'],
  )
  case(
    'R06-조달',
    f"BOM {buy['name']} 조달을 '임대'로 (구매·자체 가공 아님)",
    [('bom', dict(hdr=['순번', '품목코드'], ri=buy['seq'], col=4), lambda s: s.replace('구매', '임대', 1))],
    ['R06'],
  )
  case(
    'R07-없는공정',
    f"BOM {own['name']}을 만드는 공정을 없는 '공정-99'로",
    [('bom', dict(hdr=['순번', '품목코드'], ri=own['seq'], col=4), '자체 가공 (공정-99)')],
    ['R07'],
  )
  case(
    'R08-수입검사누락',
    (
      f"수입검사성적서 마지막 부품 '"
      f'{iqc[-1]["part"]}'
      f"'을 '"
      f'{iqc[-1]["part"]}'
      f"2'로 (BOM의 구매 부품이 빠지고 없는 부품이 생김)"
    ),
    [('iqc', dict(hdr=['부품', '입고 수량'], ri=len(iqc), col=0), iqc[-1]['part'] + '2')],
    ['R08'],
  )
  case(
    'R08-자체가공부품',
    f"수입검사성적서 첫 줄을 자체 가공 부품 '{own['name']}'으로",
    [('iqc', dict(hdr=['부품', '입고 수량'], ri=1, col=0), own['name'])],
    ['R08'],
  )
  case(
    'R09-입고수량',
    f'수입검사 {iqc[0]["part"]} 입고 수량에 100을 더함 (대당 수량 × 생산 수량과 다름)',
    [('iqc', dict(hdr=['부품', '입고 수량'], ri=1, col=1), f'{iqc[0]["qty"] + 100:,}개')],
    ['R09'],
  )
  case(
    'R10-선행보다먼저',
    f'생산계획서 {chain["id"]} 시작일을 선행 공정 종료일({pred_end})로',
    [('plan', dict(hdr=['공정번호', '공정'], row=chain['id'], col=2), pred_end)],
    ['R10'],
  )
  case(
    'R10-없는선행',
    f"생산계획서 {chain['id']} 선행 작업에 없는 '공정-88'을 더함",
    [('plan', dict(hdr=['공정번호', '공정'], row=chain['id'], col=5), lambda s: s + ', 공정-88')],
    ['R10'],
  )
  case(
    'R11-기간',
    f'생산계획서 {longer["id"]} 기간을 {longer["days"]}일에서 {longer["days"] + 4}일로 (근무일 수와 다름)',
    [('plan', dict(hdr=['공정번호', '공정'], row=longer['id'], col=4), str(longer['days'] + 4))],
    ['R11'],
  )
  case(
    'R12-투입합',
    '검사성적서(1차) 첫 공정 양품을 7 줄임 (투입 ≠ 양품 + 불량)',
    [('qc1', dict(hdr=['공정번호', '공정', '투입'], ri=1, col=3), lambda s: str(int(s) - 7))],
    ['R12'],
  )
  case(
    'R13-검사자',
    f"검사성적서(1차) '{qc1_ins['item']}' 검사자를 담당자가 아닌 '김아무개'로",
    [('qc1', dict(hdr=['항목', '공정번호'], ri=1, col=4), '김아무개')],
    ['R13'],
  )
  case(
    'R13-없는공정',
    f"검사성적서(1차) '{qc1_ins['item']}' 검사의 공정번호를 없는 '공정-77'로",
    [('qc1', dict(hdr=['항목', '공정번호'], ri=1, col=1), '공정-77')],
    ['R13'],
  )
  case(
    'R14-인원',
    '생산계획서 작업자 배정표 첫 공정 인원에 2명을 더함 (책임자 1 + 담당 1 + 보조와 다름)',
    [('plan', dict(hdr=['품목', '공정', '기간'], ri=crew_row, col=6), lambda s: str(int(s) + 2))],
    ['R14'],
  )
  case(
    'R15-수입검사판정',
    "수입검사 둘째 부품 판정을 '불합격'으로",
    [('iqc', dict(hdr=['부품', '입고 수량'], ri=2, col=3), '불합격')],
    ['R15'],
  )
  case(
    'R15-종합판정없음',
    '검사성적서(1차) 종합 판정의 합격 체크를 지움',
    [('qc1', dict(hdr=['종합 판정'], ri=0, col=1), '☐ 합격      ☐ 불합격')],
    ['R15'],
  )
  # 생산계획 표에 비고(다음 모듈) 열이 없어졌으므로, 검사성적서 소제목에 없는 품목을 만들어 단계를 모르게 한다
  case(
    'R17-단계없는모듈',
    "생산계획서 첫 품목 이름을 검사성적서에 없는 '가짜 공정'으로 (단계를 알 수 없는 모듈)",
    [('plan', dict(hdr=['품목', '수량', '시작'], ri=1, col=0), '가짜 공정')],
    ['R17'],
  )
  # 2차 모듈 단계는 검사성적서(2차)와 작업 순서(2차 모듈) 두 제목에 적혀 있어 둘 다 지워야 알 수 없다
  case(
    'R17-단계없음',
    "검사성적서(2차)와 작업 순서(2차 모듈) 제목에서 '(2차 모듈)'을 지움 (2차 모듈 단계를 알 수 없음)",
    [('qc2', dict(para=TITLE['qc2']), '검사성적서'), ('ops2', dict(para=TITLE['ops2']), '작업 순서')],
    ['R17'],
  )
  # R16: 부품이 어느 모듈에도 없으려면 작업 순서의 투입에서도, 사양서 소제목에서도 빠져야 한다
  part = R16_PART.get(model)
  if part:
    spec = docx.Document(os.path.join(model_folder(model), ctx['file']['spec']))
    head = heading_of(spec, part)

    def drop(s):
      left, right = s.split('→', 1)
      return ', '.join(x.strip() for x in left.split(',') if x.strip() != part) + ' →' + right

    ops1 = docx.Document(os.path.join(model_folder(model), ctx['file']['ops1']))
    row_tid = next(
      r.cells[1].text
      for t in ops1.tables
      if [c.text for c in t.rows[0].cells][:2] == ['순서', '공정번호']
      for r in t.rows[1:]
      if part in [x.strip() for x in r.cells[5].text.split('→')[0].split(',')]
    )
    case(
      'R16-모듈없는부품',
      f"'{part}'을 작업 순서({row_tid}) 투입과 사양서 소제목('{head}')에서 모두 빼서 어느 모듈에도 없게 함",
      [
        ('ops1', dict(hdr=['순서', '공정번호'], row=row_tid, col=5), drop),
        ('spec', dict(para=head), lambda s: re.sub(r'^(\d+\.)\s*\S+(?=\s*사양)', r'\1 기타', s)),
      ],
      ['R16'],
    )
  return cases


def generate(output: Path) -> None:
  for model in MODELS:
    folder = model_folder(model)
    names = {
      unicodedata.normalize('NFC', re.sub(r'^\d+_|\.docx$', '', os.path.basename(f))): os.path.basename(f)
      for f in glob.glob(os.path.join(folder, '*.docx'))
    }
    file = {k: names[v] for k, v in TITLE.items()}
    docno = {}
    for k, f in file.items():
      d = docx.Document(os.path.join(folder, f))
      docno[k] = next(t for t in d.tables if cell_text(t.rows[0].cells[0]) == '문서번호').rows[0].cells[1].text
    ctx = dict(file=file, docno=docno)
    manifest = []
    for cid, desc, edits, rules in build_cases(model, ctx):
      out = os.path.join(output, model, cid)
      os.makedirs(out)
      files = []
      for key in dict.fromkeys(e[0] for e in edits):
        d = docx.Document(os.path.join(folder, file[key]))
        for k, at, to in edits:
          if k == key:
            apply(d, at, to)
        name = unicodedata.normalize('NFC', file[key])
        d.save(os.path.join(out, name))
        files.append(name)
      manifest.append(dict(id=cid, description=desc, files=files, expect=rules))
    with open(os.path.join(output, model, 'cases.json'), 'w', encoding='utf-8', newline='\n') as f:
      json.dump(
        dict(model=model, source=f'data/{os.path.basename(model_folder(model))}', cases=manifest),
        f,
        ensure_ascii=False,
        indent=2,
      )
      f.write('\n')
    print(model, len(manifest), '케이스')


def main() -> None:
  parser = argparse.ArgumentParser(description='기존 오답을 보존하고 새 폴더에 오답 세트 생성')
  parser.add_argument('--output', type=Path, default=Path(OUT))
  target = parser.parse_args().output
  if target.exists():
    raise SystemExit(f'기존 폴더는 덮어쓰지 않습니다. --output으로 새 경로를 지정하세요: {target}')
  target.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='.wrong-set-', dir=target.parent) as stage:
    generate(Path(stage))
    os.rename(stage, target)


if __name__ == '__main__':
  main()
