"""Extract model data from source Word specifications and the production workbook."""

import datetime
import glob
import json
import os
import re
import sys
from pathlib import Path

import docx
import openpyxl
from docx.image.image import Image

MODEL, START_ARG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
if Path(OUT).exists():
  raise SystemExit(f'기존 입력 데이터는 덮어쓰지 않습니다. 새 출력 경로를 지정하세요: {OUT}')
SHIFT = 3
EXCLUDE = ('부속품 키팅', '포장·출하')  # 포장 라인 공정은 다루지 않는다 (build_cgs.py·check_cgs.py 와 같은 규칙)
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sample')
XLSX = glob.glob(os.path.join(SAMPLE, '*Gantt.xlsx'))[0]

wb = openpyxl.load_workbook(XLSX)
hol = [c.value.date() for c in wb['휴일']['A'][1:] if isinstance(c.value, datetime.datetime)]


def is_work(d):
  return d.weekday() < 5 and d not in hol


def workday(d, n):  # 엑셀 WORKDAY 와 같은 뜻
  step = 1 if n >= 0 else -1
  while n != 0:
    d += datetime.timedelta(days=step)
    if is_work(d):
      n -= step
  return d


# 기준정보: 제품군, 모델, 생산 수량, 생산 시작일
base = [r for r in wb['기준정보'].iter_rows(min_row=5, max_row=8, values_only=True) if r[1]]
INFO = {r[1]: dict(family=r[0], qty=int(r[2]), orig_start=r[3].date()) for r in base}

ws = wb['생산일정']


def schedule(model, start):
  tasks = []
  for r in ws.iter_rows(min_row=5, values_only=True):
    if r[1] != model:
      continue
    t = dict(
      zip(
        [
          ('id'),
          ('model'),
          ('stage'),
          ('name'),
          ('work'),
          ('input'),
          ('output'),
          ('outtype'),
          ('line'),
          ('qty'),
          ('dur'),
          ('preds'),
        ],
        r[:12],
        strict=False,
      )
    )
    t['preds'] = [] if t['preds'] in (None, '—') else [p.strip() for p in t['preds'].split(',')]
    tasks.append(t)
  by = {t['id']: t for t in tasks}

  def calc(t):
    if 'start' in t:
      return
    for p in t['preds']:
      calc(by[p])
    s = (
      workday(start - datetime.timedelta(days=1), 1)
      if not t['preds']
      else workday(max(by[p]['end'] for p in t['preds']), 1)
    )
    t['start'], t['end'] = s, workday(s, int(t['dur']) - 1)

  for t in tasks:
    calc(t)
  for t in tasks:
    t['qty'] = INFO[model]['qty']
    t['start'], t['end'] = t['start'].isoformat(), t['end'].isoformat()
  return tasks


def auto_start(model):
  return workday(INFO[model]['orig_start'], -SHIFT)


START = auto_start(MODEL) if START_ARG == 'auto' else datetime.date.fromisoformat(START_ARG)
tasks = schedule(MODEL, START)
qty = INFO[MODEL]['qty']
# 회사 제품 4종: 같은 규칙으로 시작일을 앞당기고, 포장 라인을 뺀 마지막 공정 종료일이 완성일
lineup = []
for m, v in INFO.items():
  st = auto_start(m)
  ts = [t for t in schedule(m, st) if t['name'] not in EXCLUDE]
  lineup.append(dict(model=m, family=v['family'], qty=v['qty'], start=st.isoformat(), end=max(t['end'] for t in ts)))

bom = [
  dict(zip(['model', 'm2', 'm1', 'part', 'spec', 'tag', 'proc', 'task'], r, strict=False))
  for r in wb['제품 구성(BOM)'].iter_rows(min_row=2, values_only=True)
  if r[0] == MODEL
]

# 사양서
code = MODEL.split('-')[1]
spec_path = [p for p in glob.glob(os.path.join(SAMPLE, '*.docx')) if MODEL in os.path.basename(p)][0]
d = docx.Document(spec_path)
paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
rev = re.search(r'Rev\. ?([\d.]+)', ' '.join(paras)).group(1)
intro = next(p for p in paras if p.endswith('.') and '카메라' in p and len(p) > 20)
sections, i = [], 0
heads = [p for p in paras if re.match(r'\d\d\. .+ 사양', p)]
for h, t in zip(heads, d.tables, strict=False):
  rows = [[c.text.strip() for c in r.cells] for r in t.rows][1:]
  m1 = re.match(r'\d\d\. (.+?) 사양', h).group(1)
  m2 = re.search(r'2차 모듈 · (\S+)', h)
  sections.append(dict(m1=m1, m2=m2.group(1) if m2 else '', rows=rows))
# 옛 형식 사양서(T400): 소제목이 부품 종류별이고 모듈 표시가 없다. 값은 그대로 두고 다른 모델과
# 같은 소제목 구성(광학부·경통부 … 부속품, 모듈 표시)으로 정리한다
regrouped = any(not sec['m2'] for sec in sections)
if regrouped:
  GROUPS = [
    ('광학부', '렌즈', ['렌즈']),
    ('경통부', '렌즈', ['경통']),
    ('센서부', '본체', ['센서 칩', '보호 유리']),
    ('셔터부', '본체', ['셔터막', '셔터 프레임']),
    ('화면부', '본체', ['보호 커버', '디스플레이 프레임']),
    ('전원부', '본체', ['배터리 케이스', '접점 단자', '패킹']),
    (
      '외장부',
      '본체',
      ['외장 커버', '그립', '단자 덮개', 'O링', '나사', '와셔', '스트랩 고리', '제품 라벨', '로고 플레이트'],
    ),
    ('부속품', '부속품', ['렌즈 캡', '스트랩']),
  ]
  src = [r for sec in sections for r in sec['rows']]
  order = {n: k for _, _, ns in GROUPS for k, n in enumerate(ns)}
  sections = []
  for m1, m2, ns in GROUPS:
    rows = sorted((r for r in src if r[0] in ns), key=lambda r: (r[2] != '재질', ns.index(r[0])))
    assert rows, m1
    sections.append(dict(m1=m1, m2=m2, rows=rows))
  assert sum(len(sec['rows']) for sec in sections) == len(src), '사양서 줄이 빠지거나 겹침'
img = None
for rel in d.part.rels.values():
  if 'image' in rel.reltype:
    img = os.path.join(os.path.dirname(os.path.abspath(OUT)), f'{code.lower()}_image.{rel.target_part.partname.ext}')
    if Path(img).exists():
      raise SystemExit(f'기존 이미지는 덮어쓰지 않습니다: {img}')
    Path(img).write_bytes(rel.target_part.blob)
    break

image = Image.from_file(img) if img else None
image_size = [image.px_width, image.px_height] if image else None
Path(OUT).write_text(
  json.dumps(
    dict(
      image_size=image_size,
      model=MODEL,
      family=INFO[MODEL]['family'],
      qty=qty,
      start=START.isoformat(),
      orig_start=INFO[MODEL]['orig_start'].isoformat(),
      ship=max(t['end'] for t in tasks),
      rev=rev,
      intro=intro,
      lineup=lineup,
      sections=sections,
      spec_regrouped=regrouped,
      image=img,
      tasks=tasks,
      bom=bom,
      spec_file=os.path.basename(spec_path),
      xlsx=os.path.basename(XLSX),
    ),
    ensure_ascii=False,
    indent=1,
  ),
  encoding='utf-8',
)
print('start', START, 'ship', max(t['end'] for t in tasks), 'tasks', len(tasks), 'bom', len(bom), 'img', img)
