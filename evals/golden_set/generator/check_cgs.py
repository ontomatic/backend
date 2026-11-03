"""문서 사이 연결 검사. 사용: python check_cgs.py 문서.docx 데이터.json"""

import datetime
import json
import os
import re
import sys
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

sys.stdout.reconfigure(encoding='utf-8')
d = docx.Document(sys.argv[1])
CFG = json.loads(Path(__file__).with_name('cgs_models.json').read_text(encoding='utf-8'))
# 포장·수입검사는 공정번호에서 제외하고 남은 생산 공정을 순서대로 매긴다.
_raw = Path(sys.argv[2]).read_text(encoding='utf-8')
_R = json.loads(_raw)
_code = _R['model'].split('-')[1]
_map, _k = {}, 0
for _t in _R['tasks']:
  _n = _t['id'].split('-')[1]
  if _t['name'] in CFG['exclude'] or _t['name'].startswith('구매 부품 입고'):
    _map[_n] = f'제외-{_n}'  # 수입검사는 품질부서 일이라 공정번호 없음
  else:
    _k += 1
    _map[_n] = f'공정-{_k:02d}'
J = json.loads(re.sub(rf'\b{_code}-(\d\d)\b', lambda m: _map[m.group(1)], _raw))
T_ALL = {t['id']: t for t in J['tasks']}  # 뺀 공정(수입검사, 포장 라인)까지 포함: 시작일 규칙에 쓴다
IQC_RAW = next(t for t in _R['tasks'] if t['name'].startswith('구매 부품 입고'))
J['tasks'] = [t for t in J['tasks'] if not t['id'].startswith('제외-')]
for t in J['tasks']:
  t['pre_all'] = list(t['preds'])
  t['preds'] = [x for x in t['preds'] if not x.startswith('제외-')]
# 공정 이름의 '부'만 뺀다. 투입·산출은 일정표의 결과물 이름을 유지한다.
for t in J['tasks']:
  t['name'] = re.sub(r'(광학|경통|센서|셔터|화면|전원|외장)부 조립', r'\1 조립', t['name'])
CODE = J['model'].split('-')[1]
MODEL = J['model']  # 모델명은 회사 자료 그대로
docs, cur = {}, '표지'
for el in d.element.body.iterchildren():
  tag = el.tag.split('}')[1]
  if tag == 'p':
    p = Paragraph(el, d)
    if p.style.name.startswith('Heading 1'):
      cur = p.text.strip()
    docs.setdefault(cur, []).append(('p', p.text.strip()))
  elif tag == 'tbl':
    t = Table(el, d)
    docs.setdefault(cur, []).append(('t', [[c.text.strip() for c in r.cells] for r in t.rows]))

res = []


def ok(name, cond, detail=''):
  res.append((cond, name, detail))


def tables(doc):
  return [x[1] for x in docs.get(doc, []) if x[0] == 't']


def paras(doc):
  return [x[1] for x in docs.get(doc, []) if x[0] == 'p']


def find_table(doc, first_header):
  return next((t for t in tables(doc) if t and t[0] and t[0][0] == first_header), None)


def meta(doc):
  m = {}
  for t in tables(doc):
    if t and len(t[0]) == 4 and t[0][0] == '문서번호':
      for r in t:
        m[r[0]] = r[1]
        m[r[2]] = r[3]
      break
  return m


def num(s):
  m = re.search(r'[\d,]+', s)
  return int(m.group().replace(',', '')) if m else None


def day(s):
  return datetime.date.fromisoformat(re.search(r'\d{4}-\d{2}-\d{2}', s).group())


HOL = {datetime.date(2026, 12, 25), datetime.date(2027, 1, 1)}


def is_work(x):
  return x.weekday() < 5 and x not in HOL


def workdays(a, b):
  n, x = 0, a
  while x <= b:
    n += is_work(x)
    x += datetime.timedelta(days=1)
  return n


def next_work(x):
  x += datetime.timedelta(days=1)
  while not is_work(x):
    x += datetime.timedelta(days=1)
  return x


SPEC, BOM, IQC, WO = '제품사양서', 'BOM 및 양산 이관', '수입검사성적서', '생산계획서'
MC = CFG['models'][MODEL]
# 회사 자료의 작업 내용 중 사양서와 어긋나는 곳은 모델 설정의 task_fix 로 고친다 (build_cgs.py 와 같은 규칙)
for t in J['tasks']:
  t.update(MC.get('task_fix', {}).get(t['id'][-2:], {}))
IQC_ID = _map[IQC_RAW['id'].split('-')[1]]  # 수입검사의 바뀐 번호 (제외-01)
# 품목: 모델 설정(cgs_models.json)의 품목 구성. 이름은 '~ 공정', src 는 일정표의 옛 이름.
# 생산계획 표의 완제품 줄도 작업자 배정표와 같은 '완제품 공정'
IT = {
  x['key']: dict(
    key=x['key'], name=x['name'], src=x['src'], stage=x['stage'], tids=[f'공정-{n}' for n in x['ids']], plan=x['name']
  )
  for x in MC['items']
}
M2KEYS = [k for k, v in IT.items() if v['stage'] == 'M2']
# 작업 순서: 1차 모듈 품목은 한 문서, 2차 모듈 품목(렌즈·본체)도 한 문서, 완제품 공정은 한 문서
RT = {
  k: {'M1': '작업 순서 (1차 모듈)', 'M2': '작업 순서 (2차 모듈)'}.get(v['stage'], f'작업 순서 ({v["name"]})')
  for k, v in IT.items()
}
STEPS = {
  f'공정-{n}': rows for n, rows in MC.get('steps', {}).items()
}  # 렌즈·본체·완제품 공정은 한 공정번호 안을 단계로 나눈다
# 문서번호: 종류-순번, 숫자는 문서 흐름 순서(표지의 순서)와 같다
_flow = [
  ('사양', '사양'),
  ('부품표', 'BOM'),
  ('수입검사', '수입검사'),
  ('계획', '계획'),
  ('순서M1', '순서'),
  ('검사M1', '검사'),
] + [('순서M2', '순서'), ('검사M2', '검사'), ('순서F', '순서'), ('검사F', '검사')]
NO = {k: f'{kind}-{i:02d}' for i, (k, kind) in enumerate(_flow, 1)}
NDOC = len(_flow)
RTNO = {k: NO['순서' + v['stage']] for k, v in IT.items()}
RT_DOCS = list(dict.fromkeys(RT.values()))
QC = {'M1': '검사성적서 (1차 모듈)', 'M2': '검사성적서 (2차 모듈)', 'F': '검사성적서 (완제품)'}
LEADER = CFG['leaders']
ALL = [SPEC, BOM, IQC, WO] + RT_DOCS + list(QC.values())
ORDER = [
  '표지',
  SPEC,
  BOM,
  IQC,
  WO,
  RT[next(k for k, v in IT.items() if v['stage'] == 'M1')],
  QC['M1'],
  RT[M2KEYS[0]],
  QC['M2'],
  RT['F'],
  QC['F'],
]
NOLIST = [NO[k] for k, _ in _flow]
FIN = IT['F']['tids'][-1]  # 완제품 공정 (D100: 공정-16)
ok(
  '문서가 공정 흐름 순서대로 있음 (사양서 → BOM → 수입검사 → 생산계획 → 작업 순서·검사성적서 번갈아)',
  list(docs) == ORDER,
  ' > '.join(docs),
)
no_prob = []
for doc, want in zip(ORDER[1:], NOLIST, strict=False):
  got = meta(doc).get('문서번호') if doc in docs else None
  if got != want:
    no_prob.append(f'{doc}: {got} ≠ {want}')
ok(f"문서번호가 '종류-순번'이고 순번이 문서 흐름 순서(1~{NDOC})와 같음", not no_prob, '; '.join(no_prob))
ok(f'문서 {NDOC}종이 모두 있음', all(x in docs for x in ALL), '없음: ' + ', '.join(x for x in ALL if x not in docs))
if any(x not in docs for x in ALL):
  for c, n, dt in res:
    print(('OK   ' if c else 'FAIL ') + n + ('' if c else '\n       -> ' + dt))
  sys.exit(1)

T = {t['id']: t for t in J['tasks']}
QTY = J['qty']

# 1. 사양서 ↔ 부품표
bom_t = find_table(BOM, '순번')
parts = bom_t[1:]  # 부품만 적음 (모듈 줄·구분·분류 태그 없음)
bom_names = [re.sub(r'\s*\(.*\)$', '', r[2]) for r in parts]
src_names = [b['part'] for b in J['bom']]
ok(
  f'부품표의 부품이 엑셀 BOM({len(J["bom"])}종)과 같음',
  sorted(bom_names) == sorted(src_names) and len(parts) == len(J['bom']),
  f'문서 {len(parts)} / 자료 {len(J["bom"])}',
)
spec_rows = [r for s in J['sections'] for r in s['rows']]
spec_doc = ' '.join(' '.join(r) for t in tables(SPEC) for r in t)
bom_doc = ' '.join(' '.join(r) for r in bom_t)
miss = [r[0] for r in spec_rows if r[0] not in spec_doc]
ok(
  '사양서 문서에 원본 사양서의 모든 부품 행이 있음',
  not miss and sum(1 for r in spec_rows if r[0]) == sum(len(t) - 1 for t in tables(SPEC) if t[0][0] == '부품'),
  '없음: ' + ', '.join(miss),
)
val_miss = [r[3] for r in spec_rows if r[3] != '해당 없음' and r[3].replace('루멘옵틱스', '온토메틱') not in spec_doc]
ok('사양서 문서의 속성값이 원본과 같음', not val_miss, ', '.join(val_miss))
mat_miss = [
  f'{b["part"]}:{b["spec"].split(" · ")[0].replace("재질: ", "")}'
  for b in J['bom']
  if b['spec'].split(' · ')[0].replace('재질: ', '') not in bom_doc
]
ok('부품표에 모든 부품의 재질이 사양서와 같게 적혀 있음', not mat_miss, ', '.join(mat_miss))

# 2. 부품표 열·조달
prob = []
if bom_t[0] != ['순번', '품목코드', '품목명', '대당 수량', '조달·공급']:
  prob.append(f'부품표 머리글 {bom_t[0]}')
src_by = {b['part']: b for b in J['bom']}
for r, nm in zip(parts, bom_names, strict=False):
  s = src_by[nm]
  want = '구매' if s['proc'] == '구매' else '자체 가공'
  if not r[4].startswith(want) or (want == '자체 가공' and s['task'] not in r[4]):
    prob.append(f'{nm} 조달/공정번호 불일치: {r[4]}')
if [r[0] for r in parts] != [str(i) for i in range(1, len(parts) + 1)]:
  prob.append('순번이 1부터 차례로 이어지지 않음')
ok(
  f'부품표: 순번(1~{len(J["bom"])})·부품 줄만 있고(구분·분류 태그 없음), 조달 방식·공급 공정번호가 엑셀과 같음',
  not prob,
  '; '.join(prob),
)

# 3. 문서번호 참조
NOPAT = r'(?:수입검사|BOM|사양|계획|순서|검사)-\d+'  # 공정-NN(공정번호)은 별도 확인
plan_t = find_table(WO, '품목')  # 생산계획 표: 품목, 수량, 시작, 종료 (비고 열 없음)
defined = set()
for doc in ALL:
  for k, v in meta(doc).items():
    if k == '문서번호':
      defined |= set(re.findall(NOPAT, v))
refs = set()
for doc in ALL:
  for kind, x in docs[doc]:
    txt = x if kind == 'p' else ' '.join(' '.join(r) for r in x)
    refs |= set(re.findall(NOPAT, txt))
ok('참조한 문서번호가 모두 정의되어 있음', not (refs - defined), '정의 없음: ' + ', '.join(sorted(refs - defined)))
rev = meta(BOM)['버전']
ok(
  f'작업 순서 {len(RT_DOCS)}종과 생산계획서가 같은 부품표 버전을 참조',
  all(rev in meta(RT[k])['근거 부품표'] for k in RT) and rev in meta(WO)['근거 부품표'],
  rev,
)
ok('사양서 버전이 원본 사양서와 같음', meta(SPEC)['버전'] == J['rev'], meta(SPEC)['버전'])

# 4. 작업 일정 ↔ 엑셀 + 날짜 규칙
sch = find_table(WO, '공정번호')
sch_prob, doc_sched = [], {}
for r in sch[1:]:
  doc_sched[r[0]] = dict(
    start=day(r[2]),
    end=day(r[3]),
    dur=int(r[4]),
    preds=[] if r[5] == '—' else [x.strip() for x in r[5].split(',') if x.strip() != '수입검사'],
    iqc='수입검사' in r[5],
    name=r[1],
  )
if set(doc_sched) != set(T):
  sch_prob.append(f'공정번호 불일치: {set(doc_sched) ^ set(T)}')  # 수입검사는 공정번호 없이 수입검사성적서에만 있다
if sch[0] != ['공정번호', '공정', '시작', '종료', '기간 (근무일)', '선행 작업']:
  sch_prob.append(f'작업 일정 머리글 {sch[0]}')
if plan_t[0] != ['품목', '수량', '시작', '종료']:
  sch_prob.append(f'생산계획 머리글 {plan_t[0]} (비고 열이 없어야 함)')
for i, s in doc_sched.items():
  t = T.get(i)
  if not t:
    continue
  if s['dur'] != int(t['dur']) or s['preds'] != t['preds'] or s['name'] != t['name']:
    sch_prob.append(f'{i} 기간/선행/이름이 엑셀과 다름')
  if s['iqc']:
    sch_prob.append(f"{i} 선행 작업에 '수입검사'가 있음 (수입검사는 선행 작업에 적지 않는다)")
  if workdays(s['start'], s['end']) != s['dur']:
    sch_prob.append(f'{i} 시작~종료가 기간 {s["dur"]}근무일과 다름')
  st = day(J['start'])
  want = (
    (st if is_work(st) else next_work(st))
    if not t['pre_all']
    else next_work(max(day(T_ALL[p]['end']) for p in t['pre_all']))
  )  # 시작은 수입검사 종료도 따진다
  if s['start'] != want:
    sch_prob.append(f'{i} 시작 {s["start"]} ≠ 선행 종료 다음 근무일 {want}')
ok(
  (
    f'작업 일정: '
    f'{len(T)}'
    f'개 작업이 엑셀과 같고(포장 라인 공정과 수입검사는 공정번호 없음, 수입검사는 선행 작업에 적지 않음), 선행 작업 '
    f'다음 근무일에 시작하며 기간이 맞음'
  ),
  not sch_prob,
  '; '.join(sch_prob),
)
last = max(s['end'] for s in doc_sched.values())
ok(
  f'마지막 작업({T[FIN]["name"]}, {FIN}) 종료일 = 완성일이고, 표지·완제품 검사성적서의 완성일과 같음',
  doc_sched[FIN]['end'] == last and str(last) in ' '.join(paras('표지')) and str(last) in ' '.join(paras(QC['F'])),
  str(last),
)


# 5. 작업 순서 (1차 모듈·2차 모듈 문서 안에 품목별 표, 렌즈·본체·완제품 공정은 세부 단계)
def route_table(k):
  """품목 k 의 작업 순서 표. 1차·2차 모듈 문서는 '■ ○○ 공정' 소제목 아래 표를 공정 이름으로 찾는다."""
  title, v = RT[k], IT[k]
  if v['stage'] == 'F':
    return find_table(title, '순서')
  cur = None
  for kind, x in docs[title]:
    if kind == 'p':
      cur = re.sub(r'^■\s*', '', x)
    elif cur == v['name'] and x[0][0] == '순서':
      return x
  return None


rt_prob, rt_ids, route = [], [], {}
for k, v in IT.items():
  title = RT[k]
  t = route_table(k)
  route[k] = {}
  if t is None:
    rt_prob.append(f'{title} 안에 {v["name"]} 표가 없음')
    continue
  prev_stage = 0
  last_out = ''
  groups = {}  # 세부 단계 공정: 공정번호 → 그 공정의 행들
  for n, r in enumerate(t[1:], 1):
    if int(r[0]) != n:
      rt_prob.append(f'{title} 순서 {r[0]} (기대 {n})')
    tids = [x.strip() for x in r[1].split(',')]
    ss = [T[x] for x in tids]
    if len(ss) == 1 and tids[0] in STEPS:
      groups.setdefault(tids[0], []).append(r)
      last_out = r[5].split('→')[-1]
      continue
    rt_ids += tids
    if len(ss) == 1:
      x = ss[0]
      if r[2].split('\n')[0] != x['name'] or r[4] != x['line'] or r[3] != x['work']:
        rt_prob.append(f'{x["id"]} 공정/작업 내용/작업장이 엑셀과 다름')
      if r[5] != f'{x["input"]} → {x["output"]}':
        rt_prob.append(f'{x["id"]} 투입→산출이 엑셀과 다름')
    else:
      if any(
        x['work'] not in r[3] or x['input'] not in r[5] or x['output'] not in r[5] or x['line'] != r[4] for x in ss
      ):
        rt_prob.append(f'{r[1]} 묶은 공정이 엑셀과 다름')
      if (
        len({x['stage'] for x in ss}) != 1
        or len({tuple(x['preds']) for x in ss}) != 1
        or len({x['dur'] for x in ss}) != 1
        or len({x['line'] for x in ss}) != 1
      ):
        rt_prob.append(f'{r[1]} 묶은 공정의 단계·선행·기간·라인이 서로 다름')
    stg = int(ss[0]['stage'][0])
    if stg < prev_stage:
      rt_prob.append(f'{title} 단계 순서(부품→1차→2차→완제품)가 거꾸로')
    prev_stage = stg
    for x in tids:
      route[k][x] = dict(order=n, insp=r[6])
    last_out = r[5].split('→')[-1]
  # 세부 단계 공정: 첫 단계 투입·마지막 단계 산출이 엑셀과 같고, 공정 이름·작업장이 같고, 단계
  # 수가 모델 설정과 같고, 확인 내용은 한 곳
  for tid, rs in groups.items():
    x = T[tid]
    ids_rt = [tid]
    rt_ids += ids_rt
    if len(rs) != len(STEPS[tid]) or len(rs) < 3:
      rt_prob.append(f'{tid} 세부 단계 {len(rs)}개 (설정 {len(STEPS[tid])}개, 최소 3개)')
    if rs[0][5].split(' → ')[0] != x['input']:
      rt_prob.append(f"{tid} 첫 단계 투입 '{rs[0][5].split(' → ')[0]}' ≠ 엑셀 '{x['input']}'")
    if rs[-1][5].split(' → ')[-1] != x['output']:
      rt_prob.append(f"{tid} 마지막 단계 산출 '{rs[-1][5].split(' → ')[-1]}' ≠ 엑셀 '{x['output']}'")
    for r in rs:
      if r[2].split('\n')[1:] != [f'({x["name"]})'] or r[4] != x['line']:
        rt_prob.append(f"{tid} 단계 '{r[2].split(chr(10))[0]}' 의 공정 이름/작업장이 엑셀과 다름")
    insp = [r[6] for r in rs if r[6] != '-']
    if len(insp) != 1 or insp[0] != MC['check'].get(tid[-2:]) or rs[-1][6] != insp[0]:
      rt_prob.append(f'{tid} 확인 내용 {insp} ≠ 설정 {MC["check"].get(tid[-2:])} (마지막 단계에 한 번)')
    route[k][tid] = dict(order=int(rs[0][0]), insp=insp[0] if insp else '-')
  if sorted(route[k]) != sorted(v['tids']):
    rt_prob.append(f'{title} 공정번호 {sorted(route[k])} ≠ 기대 {sorted(v["tids"])}')
  if k != 'F' and not all(w in last_out for w in re.split('[·]', v['src'])):
    rt_prob.append(f"{title} 마지막 산출이 '{v['name']}' 이 아님: {last_out}")
  if meta(title)['문서번호'] != RTNO[k]:
    rt_prob.append(f'{title} 문서번호')
expected = set(T)
if sorted(rt_ids) != sorted(expected):
  rt_prob.append(f'작업 누락/중복: {set(rt_ids) ^ expected}')
ok(
  (
    f'작업 순서 '
    f'{len(RT_DOCS)}'
    f'종(1차 모듈 한 문서 + 2차 모듈 '
    f'{"·".join((IT[k]["name"].replace(" 공정", "") for k in M2KEYS))}'
    f' 한 문서 + 완제품 공정)이 '
    f'{len(T)}'
    f'개 작업을 한 번씩 담고, 순서·공정·투입→산출이 엑셀과 같으며, 렌즈·본체·완제품 공정은 세부 단계('
    f'{", ".join((f"{k[-2:]}:{len(r)}" for k, r in STEPS.items()))}'
    f')로 나뉨'
  ),
  not rt_prob,
  '; '.join(rt_prob),
)

# 6. 생산계획 ↔ 일정
by_plan = {v['plan']: v for v in IT.values()}
plan_prob = []
for r in plan_t[1:]:
  v = by_plan[r[0]]
  if num(r[1]) != QTY:
    plan_prob.append(f'{r[0]} 수량 {r[2]}')
  if day(r[2]) != min(doc_sched[i]['start'] for i in v['tids']) or day(r[3]) != max(
    doc_sched[i]['end'] for i in v['tids']
  ):
    plan_prob.append(f'{r[0]} 시작·종료가 작업 일정과 다름')
if {r[0] for r in plan_t[1:]} != set(by_plan):
  plan_prob.append('생산계획 품목이 작업 순서 품목과 다름')
ok(f'생산계획 {len(IT)}개 품목: 수량·기간이 작업 일정과 같음', not plan_prob, '; '.join(plan_prob))

# 7. 작업자 배정표
asg = next(t for t in tables(WO) if t[0][:2] == ['품목', '공정'])
name2key = {v['name']: k for k, v in IT.items()}
asg_prob, seen, people, leaders = [], set(), {}, {}
for r in asg[1:]:
  tid = r[1].split()[0]
  seen.add(tid)
  k = name2key[r[0]]
  s = doc_sched[tid]
  dates = re.findall(r'\d{4}-\d{2}-\d{2}', r[2])
  if day(dates[0]) != s['start'] or day(dates[1]) != s['end']:
    asg_prob.append(f'{tid} 배정 기간 ≠ 작업 일정')
  if tid not in route[k]:
    asg_prob.append(f'{tid} 품목 {r[0]} 이 작업 순서과 다름')
  if r[1].split(' ', 1)[1] != T[tid]['name']:
    asg_prob.append(f'{tid} 공정 이름 불일치')
  assist = [] if r[5] == '—' else [x.strip() for x in r[5].split(',')]
  crew = [r[4]] + assist
  if not (r[3] and r[4]) or len(set(crew)) != len(crew) or r[3] in crew:
    asg_prob.append(f'{tid} 이름 빈칸/중복')
  if int(r[6]) < 2:
    asg_prob.append(f'{tid} 인원 {r[6]}')
  if len(assist) != int(r[6]) - 2:
    asg_prob.append(f'{tid} 보조담당자 {len(assist)}명 ≠ 인원 {r[6]} - 2 (책임자·담당자 제외)')
  if r[3] != LEADER[IT[k]['stage']]:
    asg_prob.append(f'{tid} 공정책임자 {r[3]}')
  leaders.setdefault(r[0], set()).add(r[3])
  for nm in crew:
    for a, b in people.get(nm, []):
      if not (s['end'] < a or s['start'] > b):
        asg_prob.append(f'{nm} 이(가) 같은 기간에 두 공정에 배정됨')
    people.setdefault(nm, []).append((s['start'], s['end']))
  if re.search(r'[A-Z]-\d\d', r[4] + r[5]):
    asg_prob.append(f'{tid} 이름이 아닌 번호 표기')
want_people = sum(int(r[6]) - 1 for r in asg[1:])  # 공정마다 (인원 - 책임자 1명), 같은 사람 겹치지 않음
if len(people) != want_people or len({x for v in leaders.values() for x in v}) != 3:
  asg_prob.append(f'총원 담당·보조 {len(people)}명 (기대 {want_people}명), 책임자 3명')
miss = set(expected) - seen
ok(
  (
    f'작업자 배정표: '
    f'{len(T)}'
    f'개 공정 모두 배정, 기간이 일정과 같고 보조담당자까지 이름이 인원과 맞고(책임자 3명 + 담당·보조 '
    f'{want_people}'
    f'명), 같은 기간 중복 배정 없음'
  ),
  not asg_prob and not miss,
  '; '.join(asg_prob) + (f' 배정 없음 {sorted(miss)}' if miss else ''),
)

# 8. 수입검사
iqc_t = find_table(IQC, '부품')
buys = [b for b in J['bom'] if b['proc'] == '구매']
iqc_map = {r[0]: r for r in iqc_t[1:]}
iq_prob = []
if sorted(iqc_map) != sorted(b['part'] for b in buys):
  iq_prob.append('구매 부품 목록 불일치')
for b in buys:
  r = iqc_map.get(b['part'])
  if r and r[3] != '합격':
    iq_prob.append(f'{b["part"]} 판정')
  if r and not r[2].strip():
    iq_prob.append(f'{b["part"]} 확인 내용이 비어 있음')
  per = next((int(x[3]) for x in bom_t[1:] if x[2].startswith(b['part'] + ' (')), None)
  if r and per is not None and num(r[1].replace(',', '')) != per * J['qty']:
    iq_prob.append(f'{b["part"]} 입고 수량 {r[1]} ≠ 대당 {per} × {J["qty"]}')
if iqc_t[0] != ['부품', '입고 수량', '확인 내용', '판정']:
  iq_prob.append(f'수입검사 표 머리글 {iqc_t[0]}')
if len({r[2] for r in iqc_t[1:]}) != len(iqc_t) - 1:
  iq_prob.append('부품마다 확인 내용이 달라야 하는데 같은 문구가 있음')
ok(
  (
    f'수입검사: 구매 부품 '
    f'{len(buys)}'
    f'개가 엑셀 BOM과 같고 부품마다 확인 내용이 다르며 입고 수량 = 대당 수량 × 생산 수량이고 모두 합격 (자체 가'
    f'공 '
    f'{len(J["bom"]) - len(buys)}'
    f'개는 제외)'
  ),
  not iq_prob and '전부 합격' in ' '.join(' '.join(r) for t in tables(IQC) for r in t),
  '; '.join(iq_prob),
)
m = meta(IQC)
ok(
  '수입검사 검사일이 일정의 구매 부품 입고·수입검사와 같고 공정번호는 붙이지 않음',
  '공정번호' not in m
  and day(m['검사일']) == day(IQC_RAW['start'])
  and re.findall(r'\d{4}-\d{2}-\d{2}', m['검사일'])[1] == IQC_RAW['end'],
  m['검사일'],
)

# 9. 양산 이관
ho = find_table(BOM, '확인 항목')
signs = [c for t in tables(BOM) for r in t for c in r if '서명 완료' in c]
ok(
  '양산 이관 확인: 항목 모두 완료, 3부서 서명, 승인일이 생산 시작일 이전',
  ho is not None
  and all(r[2] == '완료' for r in ho[1:])
  and len(signs) >= 3
  and all(day(s) < day(J['start']) for s in signs),
  f'서명 {len(signs)}',
)

# 10. 검사성적서 (단계별, 품목 소제목)
qc_prob, rec, sections = [], {}, {}
SEC_NAMES = {v['name'] for v in IT.values()}  # 검사성적서 소제목은 공정 이름만
for c, title in QC.items():
  cur_sec = None
  sections[c] = []
  for kind, x in docs[title]:
    if kind == 'p':
      nm = re.sub(r'^■\s*', '', x)
      if nm in SEC_NAMES:
        cur_sec = dict(name=nm, prod=None, ins=[])
        sections[c].append(cur_sec)
    elif cur_sec is not None:
      if x[0][0] == '공정번호':
        cur_sec['prod'] = x[1:]
      elif x[0][0] == '항목':
        cur_sec['ins'] += [r[0] for r in x[1:]]
  want = [v for v in IT.values() if v['stage'] == c]
  if [s['name'] for s in sections[c]] != [v['name'] for v in want]:
    qc_prob.append(f'{title} 품목 소제목 {[s["name"] for s in sections[c]]}')
  for s_, v in zip(sections[c], want, strict=False):
    k = v['key']
    ids = [r[0] for r in s_['prod'] or []]
    if sorted(ids) != sorted(route[k]):
      qc_prob.append(f'{title} {s_["name"]} 생산 기록이 작업 순서의 작업과 다름')
    for r in s_['prod'] or []:
      tid = r[0]
      qin, good, bad = int(r[2]), int(r[3]), int(r[4])
      rec[tid] = (qin, good, bad)
      if T[tid]['name'] != r[1]:
        qc_prob.append(f'{tid} 공정 이름 불일치')
      if qin != good + bad:
        qc_prob.append(f'{tid} 투입 {qin} ≠ 양품 {good}+불량 {bad}')

    # 작업 순서의 확인 내용 ↔ 검사 항목
    def n(t):
      return t.replace(' ', '')

    r_insp = {x['insp'] for x in route[k].values() if x['insp'] != '-'}
    for q in r_insp:
      if not any(n(q) in n(i) or n(i) in n(q) for i in s_['ins']):
        qc_prob.append(f"{s_['name']}: 작업 순서 확인 내용 '{q}' 가 검사성적서에 없음")
    for i in s_['ins']:
      if not any(n(q) in n(i) or n(i) in n(q) for q in r_insp):
        qc_prob.append(f"{s_['name']}: 검사 항목 '{i}' 가 작업 순서 확인 내용에 없음")
  # 검사일 = 단계의 마지막 공정 종료일
  ends = [doc_sched[i]['end'] for v in want for i in v['tids']]
  if day(meta(title)['검사일']) != max(ends):
    qc_prob.append(f'{title} 검사일 {meta(title)["검사일"]} ≠ {max(ends)}')
for tid, (qin, _good, _bad) in rec.items():
  ups = [rec[p][1] if p in rec else QTY for p in T[tid]['preds']]
  want_in = min(ups) if ups else QTY
  if qin != want_in:
    qc_prob.append(f'{tid} 투입 {qin} ≠ 선행 작업 양품의 최소값 {want_in}')
if sorted(rec) != sorted(expected):
  qc_prob.append(f'검사성적서 기록 작업 누락/중복: {set(rec) ^ expected}')
ok(
  (
    '검사성적서 3종: 공정 소제목, 생산 기록(수입검사 외 모든 작업), 투입 = 양품+불량, 투입 = 선행 양품 최소값'
    ', 작업 순서 확인 내용 ↔ 검사 항목, 검사일'
  ),
  not qc_prob,
  '; '.join(qc_prob),
)

# 11. 제품번호 · 완성 수량 (완제품 검사성적서 머리 칸)
fm = meta(QC['F'])
link_text = f'{fm.get("제품번호", "")} {fm.get("완성 수량", "")}'
rng = re.search(re.escape(MODEL) + r'-(\d{3}) ~ ' + re.escape(MODEL) + r'-(\d{3})', link_text)  # 제품번호 = 모델명-순번
cnt = int(rng.group(2)) - int(rng.group(1)) + 1 if rng else -1
ok(
  '제품번호 개수 = 완제품 공정 투입 수, 완성 수량 = 완제품 공정 양품',
  cnt == rec[FIN][0] and f'{rec[FIN][1]}대' in fm.get('완성 수량', ''),
  f'제품번호 {cnt} / 투입 {rec[FIN][0]} / 완성 {rec[FIN][1]}',
)

# 종합표(완제품 검사성적서): 앞 단계 양품 → 결합용 → 완제품 양품, 불합격 합계가 각 단계 생산 기록과 같음
sum_t = next((t for t in tables(QC['F']) if t[0][:3] == ['구분', '공정번호', '양품 / 투입']), None)
sum_prob = []
if sum_t is None:
  sum_prob.append('종합표가 없음')
else:
  srows = {r[0]: r for r in sum_t[1:]}

  def nums(s):
    return [int(x) for x in re.findall(r'\d+', s)]

  feed = [
    (k, IT[k]['tids'][-1]) for k in M2KEYS if any(t in T[FIN]['preds'] for t in IT[k]['tids'])
  ]  # 완제품 공정에 들어가는 2차 모듈
  for k_, _ in feed:
    if IT[k_]['name'] in srows:
      sum_prob.append(f'종합표에 {IT[k_]["name"]} 줄이 없어야 함 (2차 모듈 검사성적서와 중복)')
  for key, tid in [('F', FIN)]:
    r = srows.get(IT[key]['name'])
    if not r:
      sum_prob.append(f'종합표에 {IT[key]["name"]} 줄이 없음')
      continue
    qin, good, bad = rec[tid]
    if bool(bad) != bool(r[4].strip()):
      sum_prob.append(f"{IT[key]['name']} 비고 '{r[4]}' (불합격 {bad}개: 있을 때만 사유를 적음)")
    if r[1] != tid or nums(r[2]) != [good, qin] or nums(r[3]) != ([bad] if bad else []):
      sum_prob.append(
        f'{IT[key]["name"]} 종합표 {r[2]} / 불합격 {r[3]} ≠ 생산 기록 양품 {good} / 투입 {qin}, 불량 {bad}'
      )
  want_join = min(rec[t][1] for _, t in feed)
  if want_join != rec[FIN][0]:
    sum_prob.append(f'완제품 투입 {rec[FIN][0]} ≠ 앞 단계 양품 중 적은 쪽 {want_join}')
  if '완제품 결합용' in srows:
    sum_prob.append('완제품 결합용 줄이 없어야 함')
  if '불합격 합계' in srows:
    sum_prob.append('불합격 합계 줄이 없어야 함')
ok(
  (
    '종합표: 2차 모듈 양품/투입, 완제품 양품(투입 = 앞 단계 양품 중 적은 쪽), 불합격 제품 개수·비고(불량 있을'
    ' 때만)가 각 단계 생산 기록과 같음'
  ),
  not sum_prob,
  '; '.join(sum_prob),
)


# 종합 판정 상자: 수입검사·검사성적서 3종 모두 [종합 판정 | ☑ 합격 ☐ 불합격 | 근거]
vb_prob = []
for doc in [IQC] + list(QC.values()):
  vb = [r for t in tables(doc) for r in t if r[0] == '종합 판정']
  if len(vb) != 1 or '☑ 합격' not in vb[0][1] or '☐ 불합격' not in vb[0][1]:
    vb_prob.append(f'{doc} 종합 판정 상자 {vb}')
if any('판정: 합격' in x for doc in [IQC] + list(QC.values()) for x in paras(doc)):
  vb_prob.append("예전 '판정: 합격' 줄이 남아 있음")
ok(
  '종합 판정: 수입검사·검사성적서 3종에 [종합 판정 | ☑ 합격 ☐ 불합격 | 근거] 상자가 하나씩 있음',
  not vb_prob,
  '; '.join(vb_prob),
)

# 1차·2차 모듈 검사성적서의 단계별 수량 종합표: 공정마다 시작 투입, 완성 양품(마지막 작업 중 적은 쪽), 불합격 합계
st_prob = []
for c in ('M1', 'M2'):
  st_t = next((t for t in tables(QC[c]) if t[0][:3] == ['구분', '공정번호', '양품 / 투입']), None)
  if st_t is None:
    st_prob.append(f'{QC[c]} 종합표가 없음')
    continue
  srows = {r[0]: r for r in st_t[1:]}

  def nums(s):
    return [int(x) for x in re.findall(r'\d+', s)]

  for v in IT.values():
    if v['stage'] != c:
      continue
    r = srows.get(v['name'])
    if not r:
      st_prob.append(f'{QC[c]} 종합표에 {v["name"]} 줄이 없음')
      continue
    tids = v['tids']
    finals = [i for i in tids if not any(i in T[o]['preds'] for o in tids)]
    want = [min(rec[i][1] for i in finals), rec[tids[0]][0]]
    bad = sum(rec[i][2] for i in tids)
    if bool(bad) != bool(r[4].strip()):
      st_prob.append(f"{QC[c]} {v['name']} 비고 '{r[4]}' (불합격 {bad}개: 있을 때만 사유를 적음)")
    if want[0] + bad != want[1]:
      st_prob.append(f'{QC[c]} {v["name"]} 양품 {want[0]} + 불합격 {bad} ≠ 투입 {want[1]} (품목 수량이 맞지 않음)')
    if r[1].split('\n') != finals or nums(r[2]) != want or nums(r[3]) != ([bad] if bad else []):
      st_prob.append(
        f'{QC[c]} {v["name"]} 종합표 {r[1]} {r[2]} {r[3]} ≠ 완성 공정 {finals} 양품/투입 {want} 불합격 {bad}'
      )
  if '불합격 합계' in srows:
    st_prob.append(f'{QC[c]} 불합격 합계 줄이 없어야 함')
ok(
  '1차·2차 모듈 검사성적서의 단계별 수량 종합표: 공정마다 양품/투입·불합격과 합계가 생산 기록과 같음',
  not st_prob,
  '; '.join(st_prob),
)

# 13. 결재란: 문서마다 담당·검토·승인에 이름·직책·날짜, 결재일 = 문서 날짜, 그 문서를 쓰기 전에 결재
aps = [t for t in (x[1] for v in docs.values() for x in v if x[0] == 't') if t and t[0] == ['담당', '검토', '승인']]
ap_prob = []
if len(aps) != len(ORDER) - 1:
  ap_prob.append(f'결재란 {len(aps)}개 (기대 {len(ORDER) - 1})')
first_use = min(
  day(t['start'])
  for t in T.values()
  if any(x.startswith('제외-') and T_ALL[x]['name'].startswith('구매 부품 입고') for x in t['pre_all'])
)  # 구매 부품을 처음 쓰는 날
for doc, t in zip(ORDER[1:], aps, strict=False):
  cells = t[1]
  if any(len([y for y in c.split('\n') if y.strip()]) != 3 for c in cells):
    ap_prob.append(f'{doc} 결재란에 이름·직책·날짜가 다 없음')
    continue
  d_ap = {day(c) for c in cells}
  if len(d_ap) != 1:
    ap_prob.append(f'{doc} 결재일이 서로 다름')
    continue
  d_ap = d_ap.pop()
  m = meta(doc)
  want = day(m['발행일']) if '발행일' in m else max(day(x) for x in re.findall(r'\d{4}-\d{2}-\d{2}', m['검사일']))
  if d_ap != want:
    ap_prob.append(f'{doc} 결재일 {d_ap} ≠ 문서 날짜 {want}')
  if (doc in (SPEC, BOM, WO) or doc in RT_DOCS) and d_ap >= day(J['start']):
    ap_prob.append(f'{doc} 생산 시작 뒤에 결재')
  if doc == IQC and d_ap >= first_use:
    ap_prob.append(f'수입검사 결재 {d_ap}가 구매 부품을 처음 쓰는 {first_use} 이후')
# 단계 검사성적서는 한 장이라 결재일이 단계의 마지막 공정 종료일 하나다. 갈래마다 끝나는 날이
# 달라(T400·F35는 렌즈 쪽이 늦음)
# 다음 단계 공정이 결재 전에 시작할 수 있으므로: 다음 공정은 들어오는 공정이 끝나 검사 판정을 마친 뒤 시작하고,
# 결재 전에 시작하는 공정이 있으면 그 사실을 작성 근거에 적었는지 본다
all_text = ' '.join(x for v in docs.values() for k_, x in v if k_ == 'p')
for c, nxt in (('M1', [i for k in M2KEYS for i in IT[k]['tids']]), ('M2', IT['F']['tids'])):
  t = aps[ORDER.index(QC[c]) - 1] if len(aps) == len(ORDER) - 1 else None
  if not t:
    continue
  d_ap = day(t[1][0])
  for x in nxt:
    if doc_sched[x]['start'] <= max(day(T[p]['end']) for p in T[x]['preds']):
      ap_prob.append(f'{x} 가 들어오는 공정이 끝나기 전에 시작')
  early = [x for x in nxt if doc_sched[x]['start'] <= d_ap]
  if early and not all(f'{x} {T[x]["name"]}' in all_text and '결재' in all_text for x in early):
    ap_prob.append(f'{QC[c]} 결재({d_ap}) 전에 시작하는 {early} 가 작성 근거에 없음')
ok(
  (
    f'결재란: '
    f'{NDOC}'
    f'종 모두 담당·검토·승인에 이름·직책·날짜, 결재일 = 문서 날짜, 다음 공정은 들어오는 공정의 검사 판정 뒤 시작('
    f'결재 전에 시작하면 작성 근거에 적음)'
  ),
  not ap_prob,
  '; '.join(ap_prob),
)

# 12. 날짜 순서
d_ho, d_wo = day(meta(BOM)['발행일']), day(meta(WO)['발행일'])
d_iqc = day(meta(IQC)['검사일'])
ok(
  '날짜 순서: 부품표 발행 ≤ 생산계획서 발행 < 생산 시작 ≤ 수입검사',
  d_ho <= d_wo < day(J['start']) <= d_iqc,
  f'{d_ho} {d_wo} {J["start"]} {d_iqc}',
)

# 14. 문서 사이 연결: 공정번호·검사자·제품번호
owner = {r[1].split()[0]: r[4] for r in asg[1:]}  # 공정번호 → 배정표의 담당자
link_prob = []
# 검사 표(머리글 '항목'): 공정번호는 그 단계의 작업 순서에 있는 공정이고, 검사자는 배정표의 그 공정 담당자
stage_tids = {c: {i for v in IT.values() if v['stage'] == c for i in v['tids']} for c in QC}
for c, title in QC.items():
  for t in tables(title):
    if t[0][:2] != ['항목', '공정번호']:
      continue
    for r in t[1:]:
      tid, who = r[1], r[4]
      if tid not in stage_tids[c]:
        link_prob.append(f'{title} {r[0]}: {tid} 가 이 단계 공정이 아님')
      if owner.get(tid) != who:
        link_prob.append(f'{title} {r[0]}: 검사자 {who} ≠ 배정표 {tid} 담당 {owner.get(tid)}')
# 제품번호별 점검표: 소제목 '점검표 · 제품번호 X'의 제품번호가 머리 칸 제품번호 범위 안, 관련 공정이 실제 공정
sns = [m.group(1) for x in paras(QC['F']) for m in [re.match(r'점검표 · 제품번호 (\S+)', x.replace('■ ', ''))] if m]
checks = [t for t in tables(QC['F']) if t[0][:2] == ['분류', '관련 공정']]
if not sns or len(sns) != len(checks):
  link_prob.append(f'제품번호별 점검표 소제목 {len(sns)}개 / 점검 표 {len(checks)}개')
for sn in sns:
  n = int(sn.rsplit('-', 1)[1]) if sn.startswith(MODEL + '-') else -1
  if not (int(rng.group(1)) <= n <= int(rng.group(2))):
    link_prob.append(f'제품번호 {sn} 이 범위 밖')
for t in checks:
  for r in t[1:]:
    for tid in r[1].split('\n'):
      if tid not in T:
        link_prob.append(f"점검표 '{r[2]}' 관련 공정 {tid} 가 없음")
    if r[4] != 'OK':
      link_prob.append(f"점검표 '{r[2]}' 결과 {r[4]}")
ok(
  (
    '문서 사이 연결: 검사 표의 공정번호·검사자가 작업 순서·배정표와 같고, 제품번호별 점검표의 제품번호·관련 공정이 다'
    '른 문서와 같음'
  ),
  not link_prob,
  '; '.join(link_prob),
)

fail = [r for r in res if not r[0]]
for c, nme, dt in res:
  print(('OK   ' if c else 'FAIL ') + nme + ('' if c else '\n       -> ' + dt))
print(f'\n통과 {len(res) - len(fail)} / 전체 {len(res)}')
sys.exit(bool(fail))
