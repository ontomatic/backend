"""Generate golden answers from model inputs; --check validates without writing.
Existing answers require --force when their values change."""

import datetime
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
CFG = json.loads(Path(HERE, 'cgs_models.json').read_text(encoding='utf-8'))
TODAY = '2026-11-03'


# ===== build_cgs.py 와 같은 규칙으로 모델 json 을 읽는다 =====
def load(path):
  raw = Path(path).read_text(encoding='utf-8')
  R = json.loads(raw)
  code = R['model'].split('-')[1]
  num, kept = {}, 0

  # 포장 라인 공정(부속품 키팅, 포장·출하)과 구매 부품 입고·수입검사(품질부서 일)는 공정번호를 붙이지 않고,
  # 남은 생산 공정을 엑셀 순서대로 이어 매긴다 (렌즈 가공이 공정-01)
  def is_iqc(t):
    return t['name'].startswith('구매 부품 입고')

  for t in R['tasks']:
    n = t['id'].split('-')[1]
    if t['name'] in CFG['exclude'] or is_iqc(t):
      num[n] = f'제외-{n}'
    else:
      kept += 1
      num[n] = f'공정-{kept:02d}'
  J = json.loads(re.sub(rf'\b{code}-(\d\d)\b', lambda m: num[m.group(1)], raw))
  J['iqc_task'] = next(t for t in R['tasks'] if is_iqc(t))  # 수입검사성적서의 검사일
  J['tasks'] = [t for t in J['tasks'] if not t['id'].startswith('제외-')]
  for t in J['tasks']:
    t['preds'] = [x for x in t['preds'] if not x.startswith('제외-')]
  # 공정 이름만 "광학부 조립" → "광학 조립". 투입·산출은 만들어지는 것(광학부 …)이라 일정표 그대로
  for t in J['tasks']:
    t['name'] = re.sub(r'(광학|경통|센서|셔터|화면|전원|외장)부 조립', r'\1 조립', t['name'])
  MC = CFG['models'][J['model']]
  # 회사 자료(엑셀)의 작업 내용이 사양서와 어긋나는 곳은 모델 설정의 task_fix 로 고친다 [설계]
  for t in J['tasks']:
    t.update(MC.get('task_fix', {}).get(t['id'][-2:], {}))
  # 사양서에서 부품 줄을 다른 소제목으로 옮긴다 (T400 패킹 → 외장부) [설계]
  for p_, m1 in MC.get('spec_move', {}).items():
    frm = next(s for s in J['sections'] if any(r[0] == p_ for r in s['rows']))
    to = next(s for s in J['sections'] if s['m1'] == m1)
    rows = [r for r in frm['rows'] if r[0] == p_]
    frm['rows'] = [r for r in frm['rows'] if r[0] != p_]
    at = next((i for i, r in enumerate(to['rows']) if r[0] == '나사'), len(to['rows']))
    to['rows'][at:at] = rows
  return J


HOL = {'2026-12-25', '2027-01-01'}


def work_back(iso, n):
  d = datetime.date.fromisoformat(iso)
  while n > 0:
    d -= datetime.timedelta(days=1)
    if d.weekday() < 5 and d.isoformat() not in HOL:
      n -= 1
  return d.isoformat()


COMPANY = '온토메틱'


def clean(s):
  return str(s).replace('루멘옵틱스', COMPANY)


SUPPLIER = {
  '센서 칩': '㈜한국센서',
  '보호 유리': '㈜한국광학',
  '보호 커버': '㈜한국디스플레이',
  '접점 단자': '㈜한국전자부품',
  '패킹': '㈜한국고무',
  '그립': '㈜한국고무',
  '단자 덮개': '㈜한국고무',
  'O링': '㈜한국고무',
  '나사': '㈜한국패스너',
  '와셔': '㈜한국패스너',
  '스트랩 고리': '㈜한국패스너',
  '제품 라벨': '㈜한국인쇄',
  '로고 플레이트': '㈜한국인쇄',
  '스트랩': '㈜한국섬유',
}
PEOPLE = {
  'CEO': ('경영', '정태호', '대표이사'),
  'RD_HEAD': ('R&D부서', '서현우', '부서장'),
  'RD_LEAD': ('R&D부서', '류지성', '광학팀장'),
  'RD_ENG': ('R&D부서', '문가은', '선임연구원'),
  'PRD_HEAD': ('생산부서', '권상혁', '부서장'),
  'PRD_LEAD': ('생산부서', '최우석', '생산팀장'),
  'PRD_PLAN': ('생산부서', '홍지원', '대리'),
  'PRD_ENG': ('생산부서', '배성민', '선임'),
  'QA_HEAD': ('품질부서', '오세영', '부서장'),
  'QA_LEAD': ('품질부서', '차민서', '품질팀장'),
  'QA_IQC': ('품질부서', '조은서', '주임'),
  'QA_REC': ('품질부서', '한예준', '주임'),
}


def person(k):
  return f'{PEOPLE[k][1]} {PEOPLE[k][2]}'


ORG_ROLE = {
  'CEO': '제품사양서 승인',
  'RD_HEAD': '제품사양서 검토, BOM 승인, 양산 이관 서명',
  'RD_LEAD': 'BOM 검토, 첫 시제품 시험',
  'RD_ENG': '제품사양서·BOM 작성, 제품 설계',
  'PRD_HEAD': '생산계획서·작업 순서 승인, 양산 이관 서명',
  'PRD_LEAD': '생산계획서·작업 순서 검토, 작업자 교육',
  'PRD_PLAN': '생산계획서 작성 (생산관리)',
  'PRD_ENG': '작업 순서 문서 작성 (생산기술)',
  'QA_HEAD': '수입검사·검사성적서 승인, 양산 이관 서명',
  'QA_LEAD': '수입검사·검사성적서 검토',
  'QA_IQC': '수입검사성적서 작성, 구매 부품 검사',
  'QA_REC': '검사성적서 (1차 모듈·2차 모듈·완제품) 작성',
}  # 조직표의 맡은 일 (build_cgs.py 의 PEOPLE 과 같다)
IQC_CHECK = {
  '센서 칩': '수량·로트 표기 대조, 정전기 방지 포장 개봉 상태, 수광면 이물·긁힘, 칩 외형 치수',
  '보호 유리': '코팅면 얼룩·기포·박리, 빛 투과율(분광 측정), 두께·외경, 조명 아래 긁힘',
  '보호 커버': '표면 긁힘·깨짐·기포, 두께·외형 치수, 모서리 가공 상태',
  '접점 단자': '도금 변색·산화, 접점 접촉 저항, 핀 휨·변형',
  '패킹': '찢김·기포·성형 찌꺼기(버), 단면 두께, 눌렀다 놓았을 때 복원',
  '그립': '표면 끈적임·이염, 경도, 접착면 오염',
  '단자 덮개': '찢김·성형 불량, 여닫을 때 복원과 걸림, 외형 치수',
  'O링': '내경·선경, 갈라진 곳(크랙)·성형선, 경도',
  '나사': '나사산 규격(M{0} 게이지 통과), 길이 {1} mm, 머리 파손·녹',
  '와셔': '내경·외경·두께, 가장자리 버, 녹 얼룩',
  '스트랩 고리': '절단·접합부 마감, 잡아당길 때 벌어짐·변형, 표면 녹',
  '제품 라벨': '인쇄 번짐, 모델명·문구 오탈자, 접착력',
  '로고 플레이트': '로고 각인 선명도·색상, 표면 긁힘·산화, 접착면 상태',
  '스트랩': '폭 {0} mm·길이 {1} mm, 재봉 풀림, 색상 균일',
}


def spec_text(s):
  return ', '.join(re.sub(r': ', ' ', re.sub(r'^재질: ', '', x), count=1) for x in s.split(' · '))


def stage_name(s):
  return re.sub(r'^\d+\.\s*', '', s)


# ===== 값의 근거 (README 의 표) =====
SRC = {
  'model': '자료',
  'productName': '자료',
  'specVersion': '자료',
  'plannedQty': '자료',
  'completedQty': '가상',
  'documents[].no': '설계',
  'documents[].title': '설계',
  'documents[].kind': '설계',
  'documents[].version': '설계',
  'documents[].date': '가상',
  'documents[].approval': '가상',
  'documents[].basedOn': '설계',
  'documents[].verdict': '가상',
  'documents[].meta.문서번호': '설계',
  'documents[].meta.버전': '설계',
  'documents[].meta.발행일': '가상',
  'documents[].meta.담당': '가상',
  'documents[].meta.상위 모델': '자료',
  'documents[].meta.근거 부품표': '설계',
  'documents[].meta.검사일': '설계',
  'documents[].meta.검사 담당': '가상',
  'documents[].meta.공정번호': '설계',
  'documents[].meta.입고 수량': '자료',
  'documents[].meta.대상 품목': '설계',
  'documents[].meta.공정책임자': '가상',
  'documents[].meta.제품번호': '설계',
  'documents[].meta.완성 수량': '가상',
  'people[].name': '가상',
  'people[].dept': '가상',
  'people[].title': '가상',
  'people[].role': '가상',
  'parts[].seq': '설계',
  'parts[].code': '설계',
  'parts[].name': '자료',
  'parts[].spec': '자료',
  'parts[].qtyPerUnit': '가상',
  'parts[].sourcing': '자료',
  'parts[].supplier': '가상',
  'parts[].taskId': '설계',
  'parts[].module': '자료',
  'parts[].accessory': '자료',
  'parts[].detail': '자료',
  'parts[].attrs': '자료',
  'modules[].name': '설계',
  'modules[].level': '설계',
  'modules[].qty': '자료',
  'modules[].start': '설계',
  'modules[].end': '설계',
  'modules[].next': '자료',
  'modules[].leader': '가상',
  'modules[].badCause': '가상',
  'tasks[].id': '설계',
  'tasks[].name': '자료',
  'tasks[].stage': '자료',
  'tasks[].start': '설계',
  'tasks[].end': '설계',
  'tasks[].days': '자료',
  'tasks[].preds': '자료',
  'tasks[].module': '설계',
  'tasks[].owner': '가상',
  'tasks[].assistants': '가상',
  'tasks[].crew': '가상',
  'tasks[].line': '자료',
  'tasks[].work': '자료',
  'tasks[].input': '자료',
  'tasks[].output': '자료',
  'tasks[].check': '설계',
  'tasks[].inQty': '가상',
  'tasks[].good': '가상',
  'tasks[].bad': '가상',
  'tasks[].routeDoc': '설계',
  'tasks[].qcDoc': '설계',
  'tasks[].steps': '설계',
  'iqc[].part': '자료',
  'iqc[].qty': '가상',
  'iqc[].check': '가상',
  'iqc[].verdict': '가상',
  'inspections[].doc': '설계',
  'inspections[].item': '가상',
  'inspections[].taskId': '설계',
  'inspections[].standard': '가상',
  'inspections[].value': '가상',
  'inspections[].inspector': '가상',
  'inspections[].verdict': '가상',
  'units[].serial': '설계',
  'units[].checks': '가상',
  'handover[].item': '설계',
  'handover[].owner': '가상',
  'handover[].status': '가상',
}
FIELDS = {
  'documents': ['no', 'title', 'kind', 'dept', 'version', 'date', 'meta', 'approval', 'basedOn', 'verdict'],
  'people': ['name', 'dept', 'title', 'role'],
  'parts': [
    'seq',
    'code',
    'name',
    'spec',
    'qtyPerUnit',
    'sourcing',
    'supplier',
    'taskId',
    'module',
    'accessory',
    'detail',
    'attrs',
  ],
  'modules': ['name', 'level', 'qty', 'start', 'end', 'next', 'leader', 'badCause'],
  'tasks': [
    'id',
    'name',
    'stage',
    'start',
    'end',
    'days',
    'preds',
    'module',
    'owner',
    'assistants',
    'crew',
    'line',
    'work',
    'input',
    'output',
    'check',
    'inQty',
    'good',
    'bad',
    'routeDoc',
    'qcDoc',
    'steps',
  ],
  'iqc': ['part', 'qty', 'check', 'verdict'],
  'inspections': ['doc', 'item', 'taskId', 'standard', 'value', 'inspector', 'verdict'],
  'units': ['serial', 'checks'],
  'handover': ['item', 'owner', 'status'],
}
SCALARS = ['model', 'productName', 'specVersion', 'plannedQty', 'completedQty']
# 배열 항목을 맞춰 볼 때 쓰는 키
MATCH = {
  'documents': ['no'],
  'people': ['name'],
  'parts': ['name'],
  'modules': ['name'],
  'tasks': ['id'],
  'iqc': ['part'],
  'inspections': ['doc', 'taskId', 'item'],
  'units': ['serial'],
  'handover': ['item'],
}


def key_of(arr, it):
  return '|'.join(str(it[k]) for k in MATCH[arr])


class Golden:
  """Extraction 모양의 정답 하나. 배열 항목은 키(MATCH)로 찾아 칸을 채운다."""

  def __init__(self):
    self.x = {a: [] for a in FIELDS}
    self.sc = {}
    self.src_extra = {}

  def scalar(self, k, v):
    if k in self.sc and self.sc[k] != v:
      raise ValueError(f'{k}: {self.sc[k]!r} ≠ {v!r}')
    self.sc[k] = v

  def item(self, arr, **kv):
    key = key_of(arr, kv)
    cur = next((it for it in self.x[arr] if key_of(arr, it) == key), None)
    if cur is None:
      cur = {}
      self.x[arr].append(cur)
    for f, v in kv.items():
      if f not in FIELDS[arr]:
        raise KeyError(f'{arr}.{f}')
      if f in cur and cur[f] != v:
        if isinstance(cur[f], dict) and isinstance(v, dict) and not (set(cur[f]) & set(v)):
          cur[f] = {**cur[f], **v}
          continue
        raise ValueError(f'{arr}[{key}].{f}: {cur[f]!r} ≠ {v!r}')
      cur[f] = v
    return cur

  def merge(self, other):
    for k, v in other.sc.items():
      self.scalar(k, v)
    for arr, items in other.x.items():
      for it in items:
        self.item(arr, **it)
    self.src_extra.update(other.src_extra)

  def expected(self):
    out = {k: self.sc[k] for k in SCALARS if k in self.sc}
    for arr in FIELDS:
      out[arr] = [{f: it[f] for f in FIELDS[arr] if f in it} for it in self.x[arr]]
    return out

  def absent(self):
    """이 문서에 적혀 있지 않아 채점하지 않는 칸"""
    ab = [k for k in SCALARS if k not in self.sc]
    for arr, items in self.x.items():
      if not items:
        continue
      for f in FIELDS[arr]:
        miss = [it for it in items if f not in it]
        if len(miss) == len(items):
          ab.append(f'{arr}[].{f}')
        else:
          ab += [f'{arr}[{key_of(arr, it)}].{f}' for it in miss]
    return ab

  def src(self):
    exp = self.expected()
    used = set(k for k in SCALARS if k in exp)
    for arr in FIELDS:
      for it in exp[arr]:
        for f, v in it.items():
          used.add(f'{arr}[].{f}')
          if f == 'meta':
            for mk in v:
              used.add(f'{arr}[].meta.{mk}')
    out = {k: v for k, v in SRC.items() if k in used}
    miss = sorted(u for u in used if u not in SRC and not u.endswith('[].meta'))
    if miss:
      raise KeyError(f'근거 표시가 없는 칸: {miss}')
    out.update({k: v for k, v in self.src_extra.items() if k.split('[')[0] in exp})
    return out


def build(json_path):
  J = load(json_path)
  MODEL = J['model']
  MC = CFG['models'][MODEL]

  def SERIAL(n):
    return f'{MODEL}-{n:03d}'

  T = J['tasks']
  by_id = {t['id']: t for t in T}
  END = max(t['end'] for t in T)
  HAND = work_back(J['start'], 1)
  SPEC_DATE = work_back(HAND, 2)
  QTY = MC['qty']

  def part(n):
    return next(b for b in J['bom'] if b['part'] == n)

  def spec_detail(n):
    return next(r[1] for s in J['sections'] for r in s['rows'] if r[0] == n)

  LEADER = CFG['leaders']
  STAGE_NAME = {'M1': '1차 모듈', 'M2': '2차 모듈', 'F': '완제품'}

  ITEMS = [dict(x) for x in MC['items']]
  for it in ITEMS:
    it['tasks'] = [by_id[f'공정-{n}'] for n in it['ids']]
    it['start'] = min(t['start'] for t in it['tasks'])
    it['end'] = max(t['end'] for t in it['tasks'])
    it['planName'] = f'{MODEL} 카메라' if it['key'] == 'F' else it['name']
  ITEM = {it['key']: it for it in ITEMS}

  def in_stage(k):
    return [it for it in ITEMS if it['stage'] == k]

  def final_tasks(it):
    return [t for t in it['tasks'] if not any(t['id'] in o['preds'] for o in it['tasks'])]

  for it in ITEMS:
    fin = [t['id'] for t in final_tasks(it)]
    it['feeds'] = (
      None
      if it['key'] == 'F'
      else next(o for o in ITEMS if o is not it and any(p in fin for t in o['tasks'] for p in t['preds']))
    )

  def short(it):
    return re.sub(r' 공정$', '', it['name'])

  # 작업 순서: 1차 모듈 품목은 한 문서, 2차 모듈 품목(렌즈·본체)도 한 문서, 완제품 공정은 한 문서 (모델마다 문서 10종)
  ROUTE_DOCS = [
    dict(key='M1', name='1차 모듈', items=in_stage('M1')),
    dict(key='M2', name='2차 모듈', items=in_stage('M2')),
    dict(key='F', name=ITEM['F']['name'], items=[ITEM['F']]),
  ]
  FLOW = [
    ('SPEC', '사양'),
    ('BOM', 'BOM'),
    ('IQC', '수입검사'),
    ('PLAN', '계획'),
    ('OPS_M1', '순서'),
    ('QC_M1', '검사'),
    ('OPS_M2', '순서'),
    ('QC_M2', '검사'),
    ('OPS_F', '순서'),
    ('QC_F', '검사'),
  ]
  IQC_T = J['iqc_task']
  # 렌즈·본체·완제품 공정은 한 공정번호 안을 단계로 나눠 적었다 (모델 설정의 steps: [단계,
  # 작업 내용, 투입, 산출, 확인 내용])
  STEPS = {
    f'공정-{n}': [[x.replace('{MODEL}', MODEL) for x in r] for r in rows] for n, rows in MC.get('steps', {}).items()
  }
  DOCNO = {k: f'{kind}-{i:02d}' for i, (k, kind) in enumerate(FLOW, 1)}
  for rd in ROUTE_DOCS:
    rd['no'] = DOCNO['OPS_' + rd['key']]

  def stage_end(k):
    return max(it['end'] for it in in_stage(k))

  TITLE = {
    'SPEC': '제품사양서',
    'BOM': 'BOM 및 양산 이관',
    'IQC': '수입검사성적서',
    'PLAN': '생산계획서',
    'QC_M1': '검사성적서 (1차 모듈)',
    'QC_M2': '검사성적서 (2차 모듈)',
    'QC_F': '검사성적서 (완제품)',
    **{'OPS_' + rd['key']: f'작업 순서 ({rd["name"]})' for rd in ROUTE_DOCS},
  }
  KIND = {'SPEC': 'spec', 'BOM': 'bom', 'IQC': 'iqc', 'PLAN': 'plan'}

  def kind_of(k):
    return KIND.get(k) or ('route' if k.startswith('OPS_') else 'qc')

  APPROVAL = {
    'SPEC': (['RD_ENG', 'RD_HEAD', 'CEO'], SPEC_DATE),
    'BOM': (['RD_ENG', 'RD_LEAD', 'RD_HEAD'], HAND),
    'IQC': (['QA_IQC', 'QA_LEAD', 'QA_HEAD'], IQC_T['end']),
    'PLAN': (['PRD_PLAN', 'PRD_LEAD', 'PRD_HEAD'], HAND),
    **{'OPS_' + rd['key']: (['PRD_ENG', 'PRD_LEAD', 'PRD_HEAD'], HAND) for rd in ROUTE_DOCS},
    'QC_M1': (['QA_REC', 'QA_LEAD', 'QA_HEAD'], stage_end('M1')),
    'QC_M2': (['QA_REC', 'QA_LEAD', 'QA_HEAD'], stage_end('M2')),
    'QC_F': (['QA_REC', 'QA_LEAD', 'QA_HEAD'], END),
  }
  CHECK, REC, CREW, OWNER, ASSIST, INS = MC['check'], MC['rec'], MC['crew'], MC['owner'], MC['assist'], MC['ins']

  def n2(tid):
    return tid[-2:]

  # 검사 표 측정값: 그 공정에 불량이 있으면 충족 수와 미달 수를 두 줄로 (build_cgs.py
  # measured, 칸 안 줄바꿈은 추출기에서 \n)
  def measured(n, val, unit):
    _, good, bad = REC[n]
    return f'{good}{unit} {val}\n{bad}{unit} 미달' if bad else val

  def doc_head(g, k, meta, version=None, based=None, verdict=None):
    who, date = APPROVAL[k]
    approval = [
      dict(role=r, name=PEOPLE[w][1], title=PEOPLE[w][2], date=date)
      for r, w in zip([('담당'), ('검토'), ('승인')], who, strict=False)
    ]
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', meta.get('발행일') or meta.get('검사일'))
    g.item(
      'documents',
      no=DOCNO[k],
      title=TITLE[k],
      kind=kind_of(k),
      version=version,
      date=dates[-1],
      meta=meta,
      approval=approval,
      basedOn=based,
      verdict=verdict,
    )
    for a in approval:
      g.item('people', name=a['name'], title=a['title'])

  based = f'{DOCNO["BOM"]} 버전 1.0'
  docs = {}

  # ---------- 제품사양서 ----------
  g = Golden()
  doc_head(
    g,
    'SPEC',
    {'문서번호': DOCNO['SPEC'], '버전': J['rev'], '발행일': SPEC_DATE, '담당': f'광학팀 {person("RD_ENG")}'},
    version=J['rev'],
  )
  g.src_extra['documents[사양-01].version'] = '자료'
  g.src_extra['documents[사양-01].meta.버전'] = '자료'
  g.scalar('model', MODEL)
  g.scalar('productName', J['family'])
  g.scalar('specVersion', J['rev'])
  has_acc = any(s['m1'] == '부속품' for s in J['sections'])  # T400 사양서는 옛 형식이라 '부속품 사양' 소제목이 없다
  for s in J['sections']:
    for p_, detail, attr, value in s['rows']:
      kv = dict(name=p_, attrs={attr: clean(value)})
      if detail != '대표 설계 치수':
        kv['detail'] = clean(detail)
      if has_acc:
        kv['accessory'] = s['m1'] == '부속품'
      g.item('parts', **kv)
  docs['SPEC'] = g

  # ---------- BOM 및 양산 이관 ----------
  g = Golden()
  doc_head(g, 'BOM', {'문서번호': DOCNO['BOM'], '버전': '1.0', '발행일': HAND, '상위 모델': MODEL}, version='1.0')
  g.scalar('model', MODEL)
  for n, b in enumerate(J['bom'], 1):
    buy = b['proc'] == '구매'
    g.item(
      'parts',
      seq=n,
      code=f'부품-{n:02d}',
      name=b['part'],
      spec=spec_text(b['spec']),
      qtyPerUnit=QTY.get(b['part'], 1),
      sourcing='구매' if buy else '자체 가공',
      supplier=SUPPLIER[b['part']] if buy else None,
      taskId=None if buy else b['task'],
    )
  handover = [
    (f'제품 설계 확정 ({DOCNO["SPEC"]} 버전 {J["rev"]}, {DOCNO["BOM"]} 버전 1.0)', 'RD_ENG'),
    (f'작업 순서 초안 {len(ROUTE_DOCS)}종 (1차 모듈, 2차 모듈, {ITEM["F"]["name"]} 각 1)', 'PRD_ENG'),
    ('첫 시제품 시험 5대 합격', 'RD_LEAD'),
    ('작업자 교육 (모듈 조립·검사 공정 전원 수료)', 'PRD_LEAD'),
  ]
  for item, w in handover:
    g.item('handover', item=item, owner=f'{PEOPLE[w][0]} {person(w)}', status='완료')
    g.item('people', name=PEOPLE[w][1], dept=PEOPLE[w][0], title=PEOPLE[w][2])
  for w in ('RD_HEAD', 'PRD_HEAD', 'QA_HEAD'):  # 양산 이관 서명 (열 머리가 부서)
    g.item('people', name=PEOPLE[w][1], dept=PEOPLE[w][0], title=PEOPLE[w][2])
  # 조직표 (문서를 나누면 표지가 없어서 이 문서에 넣었다): 부서·직책·이름·맡은 일
  for k, role in ORG_ROLE.items():
    g.item('people', name=PEOPLE[k][1], dept=PEOPLE[k][0], title=PEOPLE[k][2], role=role)
  for k, nm in (('M1', '1차 모듈'), ('M2', '2차 모듈'), ('F', '완제품')):
    g.item('people', name=LEADER[k], dept='생산부서', title='파트장', role=f'{nm} 공정 책임')
  docs['BOM'] = g

  # ---------- 수입검사성적서 ----------
  g = Golden()
  # 수입검사는 공정번호 없이 검사일만 적는다
  doc_head(
    g,
    'IQC',
    {
      '문서번호': DOCNO['IQC'],
      '버전': '1.0',
      '검사일': f'{IQC_T["start"]} ~ {IQC_T["end"]}',
      '검사 담당': person('QA_IQC'),
      '입고 수량': f'{J["qty"]}대분',
    },
    version='1.0',
    verdict='합격',
  )
  g.scalar('plannedQty', J['qty'])
  screw = re.search(r'M([\d.]+) × ([\d.]+) mm', part('나사')['spec']).groups()
  strap = re.search(r'([\d,]+) × ([\d,]+) mm', part('스트랩')['spec']).groups()
  for b in J['bom']:
    if b['proc'] != '구매':
      continue
    chk = IQC_CHECK[b['part']].format(*(screw if b['part'] == '나사' else strap if b['part'] == '스트랩' else ()))
    g.item('iqc', part=b['part'], qty=QTY.get(b['part'], 1) * J['qty'], check=chk, verdict='합격')
  docs['IQC'] = g

  # ---------- 생산계획서 ----------
  g = Golden()
  doc_head(
    g,
    'PLAN',
    {'문서번호': DOCNO['PLAN'], '버전': '1.0', '발행일': HAND, '근거 부품표': based},
    version='1.0',
    based=DOCNO['BOM'],
  )
  g.scalar('plannedQty', J['qty'])
  # 완제품 줄도 작업자 배정표와 같은 '완제품 공정'. 생산계획 표에 비고 열이 없어 다음 모듈(next)은 적혀 있지 않다
  for it in ITEMS:
    g.item('modules', name=it['name'], qty=J['qty'], start=it['start'], end=it['end'], leader=LEADER[it['stage']])
  for t in T:
    g.item('tasks', id=t['id'], name=t['name'], start=t['start'], end=t['end'], days=int(t['dur']), preds=t['preds'])
  for it in ITEMS:
    g.item('people', name=LEADER[it['stage']])
    for t in it['tasks']:
      n = n2(t['id'])
      g.item('tasks', id=t['id'], module=it['name'], owner=OWNER[n], assistants=ASSIST.get(n, []), crew=CREW[n])
      for nm in [OWNER[n]] + ASSIST.get(n, []):
        g.item('people', name=nm)
  docs['PLAN'] = g

  # ---------- 작업 순서 ----------
  for rd in ROUTE_DOCS:
    g = Golden()
    k = 'OPS_' + rd['key']
    doc_head(
      g,
      k,
      {'문서번호': rd['no'], '버전': '1.0', '발행일': HAND, '근거 부품표': based},
      version='1.0',
      based=DOCNO['BOM'],
    )
    for it in rd['items']:
      # 문서 제목에 단계가 있는 것은 1차·2차 모듈 문서뿐이다 ('작업 순서 (완제품 공정)'은 단계 이름이 아님)
      g.item('modules', name=it['name'], **({'level': STAGE_NAME[rd['key']]} if rd['key'] in ('M1', 'M2') else {}))
      mg = [f'공정-{n}' for n in it.get('merge', [])]  # 한 줄로 묶어 적은 두 공정 (화면·전원 조립)
      for t in it['tasks']:
        kv = dict(id=t['id'], stage=stage_name(t['stage']), line=t['line'], module=it['name'], routeDoc=rd['no'])
        if t['id'] in STEPS:
          # 세부 단계 공정: 공정 칸 둘째 줄이 '(렌즈 조립)'처럼 공정 이름이라 단계(stage)는 적혀 있지 않고,
          # 작업 내용은 단계마다 따로라 공정 하나의 작업 내용(work)도 없다. 투입은 첫
          # 단계, 산출은 마지막 단계 값(= 일정표 값)
          del kv['stage']
          st = STEPS[t['id']]
          kv.update(
            name=t['name'],
            input=st[0][2],
            output=st[-1][3],
            check=CHECK.get(n2(t['id'])),
            steps=[dict(name=s, work=w, input=i, output=o, check=None if c == '-' else c) for s, w, i, o, c in st],
          )
          g.item('tasks', **kv)
          continue
        if t['id'] in mg:
          # 묶은 줄: 공정 이름은 '화면·전원 조립' 하나, 투입→산출은 둘을 합쳐 적어 공정별로 나눌 수 없다 → 채점하지 않음
          first = by_id[mg[0]]
          kv.update(work=t['work'], check=CHECK.get(n2(first['id'])))
        else:
          kv.update(name=t['name'], work=t['work'], input=t['input'], output=t['output'], check=CHECK.get(n2(t['id'])))
        g.item('tasks', **kv)
    docs[k] = g

  # ---------- 검사성적서 ----------
  for k in ('M1', 'M2', 'F'):
    g = Golden()
    its = in_stage(k)
    qc = DOCNO['QC_' + k]
    if k == 'F':
      r_fin = REC[n2(its[0]['tasks'][-1]['id'])]
      meta = {
        '문서번호': qc,
        '검사일': ITEM['F']['end'],
        '대상 품목': ITEM['F']['planName'],
        '공정책임자': LEADER['F'],
        '제품번호': f'{SERIAL(1)} ~ {SERIAL(r_fin[0])}',
        '완성 수량': f'{r_fin[1]}대',
      }
      g.scalar('completedQty', r_fin[1])
    else:
      meta = {'문서번호': qc, '검사일': stage_end(k), '대상 품목': f'{len(its)}개', '공정책임자': LEADER[k]}
    doc_head(g, 'QC_' + k, meta, verdict='합격')
    g.item('people', name=LEADER[k])
    for it in its:
      # 단계별 수량 종합표의 비고: 불량이 나온 공정의 불량 원인을 모아 적고, 불량이 없으면 빈칸 (build_cgs.py BADWHY)
      why = ', '.join(MC['bad_reason'][n2(t['id'])] for t in it['tasks'] if REC[n2(t['id'])][2] > 0)
      g.item('modules', name=it['name'], level=STAGE_NAME[k], leader=LEADER[k], badCause=why or None)
      for t in it['tasks']:
        r = REC[n2(t['id'])]
        g.item('tasks', id=t['id'], name=t['name'], module=it['name'], inQty=r[0], good=r[1], bad=r[2], qcDoc=qc)
      rows = INS.get(it['key'], [])
      if k == 'F':
        rows = [['최종 검사', n2(it['tasks'][-1]['id']), '아래 제품번호별 점검표 전 항목 OK', '기준 충족']]
      for item, n, std, val in rows:
        g.item(
          'inspections',
          doc=qc,
          item=item,
          taskId=f'공정-{n}',
          standard=std,
          value=measured(n, val, '대' if k == 'F' else '개'),
          inspector=OWNER[n],
          verdict='합격',
        )
        g.item('people', name=OWNER[n])
    if k == 'F':
      fin = ITEM['F']['tasks'][-1]
      nser = REC[n2(fin['id'])][0]
      lens = clean(spec_detail('렌즈'))

      def fill(s: str, lens: str = lens) -> str:
        return (
          re.sub(('\\{(나사|와셔)\\}'), lambda m: str(QTY[m.group(1)]), s)
          .replace(('{MODEL}'), MODEL)
          .replace(('{LENS}'), lens)
        )

      if any(n < 1 or n > nser for n in MC['samples']):
        raise ValueError(f'samples 가 제품번호 범위(1~{nser}) 밖')
      for sn in map(
        SERIAL, MC['samples']
      ):  # 점검표 표본: 제품번호 범위 안에서 무작위로 고른 3대 (모델 설정의 samples, 고정)
        g.item(
          'units',
          serial=sn,
          checks=[
            dict(cls=c, taskIds=[f'공정-{n}' for n in ids], item=item, standard=fill(std), result='OK')
            for c, ids, item, std in MC['checklist']
          ],
        )
    docs['QC_' + k] = g

  # ---------- 모델 합본 ----------
  model = Golden()
  for k, _ in FLOW:
    model.merge(docs[k])
  # 사양서에만 있는 '해당 없음' 줄(F35·I100의 센서 칩 등)은 이 제품의 부품이 아니라 합본에서는 뺀다
  bom_names = {b['part'] for b in J['bom']}
  model.x['parts'] = [p for p in model.x['parts'] if p['name'] in bom_names]
  # 부품이 속한 1차 모듈: 엑셀 '제품 구성'의 1차 모듈(m1) → 그 이름을 src 로 가진 품목.
  # '— (직접 구성)'은 부속품이라 모듈 없음.
  # 문서에서는 사양서 소제목·작업 순서의 투입 목록으로 이어 알 수 있다
  for b in J['bom']:
    direct = b['m1'].startswith('—')
    it = (
      None
      if direct
      else next(i for i in ITEMS if i['stage'] == 'M1' and (b['m1'] == i['src'] or b['m1'] in i['src'].split('·')))
    )  # I100 '렌즈·셔터부'는 이름 그대로
    model.item('parts', name=b['part'], module=it['name'] if it else None, accessory=direct)
  files = {k: f'{i:02d}_{TITLE[k]}.docx' for i, (k, _) in enumerate(FLOW, 1)}
  return MODEL, [(files[k], docs[k]) for k, _ in FLOW], model, J


NOTE_DOC = (
  '생성기 입력({json}, cgs_models.json)에서 build_'
  'cgs.js 와 같은 규칙으로 make_golden.py 가 만든 초안 '
  '({today}). 추출기 출력과 독립. 이 문서(표지·부록 없는 파일)'
  '에 적힌 값만 담았고, 적혀 있지 않은 칸은 키를 빼고 absent 에 '
  '적었다(채점하지 않음). 사람 검수 후 status 를 reviewed '
  '로 바꾼다.'
)
NOTE_MODEL = (
  '생성기 입력({json}, cgs_models.json)에서 make_g'
  'olden.py 가 만든 모델 합본 초안 ({today}). 문서 {n}'
  '개의 문서별 정답을 합치고(같은 항목 값이 문서마다 같은지 확인), 부품'
  "의 모듈·부속품 여부(엑셀 '제품 구성' 시트, 문서에서는 사양서 소제목"
  '·작업 순서 투입 목록으로 이어 알 수 있음)를 더했다. 사양서에만 있는'
  " '해당 없음' 부품 줄은 이 제품의 부품이 아니라 뺐다. 표지가 없는 "
  '파일이라 documents[].dept 는 없고, people[].rol'
  'e 은 조직표가 들어 있는 BOM 및 양산 이관 문서의 사람에만 있다.'
)
EXTRA_NOTES = {
  (
    '생산계획서'
  ): "생산계획 표의 완제품 줄은 작업자 배정표와 같은 '완제품 공정'이다(수량은 '1,000대'처럼 쉼표, 정답은 숫자). "
  '생산계획 표에 비고 열이 없어 모듈의 다음 모듈(next)은 어느 문서에도 적혀 있지 않다. '
  '구매 부품 입고·수입검사는 공정번호가 없고 작업 일정에도 없다. '
  '공정책임자·담당자·보조담당자는 이름만 적혀 있어 people 에는 이름만 둔다.',
  (
    '작업 순서 (1차 모듈)'
  ): "화면·전원 조립 줄은 두 공정(공정번호 둘)을 한 줄에 묶어 적었다. 작업 내용은 ' / '로 나뉘어 공정별로 정답을 두고, "
  '공정 이름·투입·산출은 합쳐 적혀 공정별로 나눌 수 없어 채점하지 않는다.',
  ('작업 순서 (2차 모듈)'): (
    '렌즈·본체 공정은 공정번호 하나 안을 단계로 나눠 적었다(여러 줄이 같은'
    ' 공정번호). 단계는 tasks[].steps 에 순서대로 두고, 공정 '
    "이름은 공정 칸 둘째 줄의 '(렌즈 조립)', 투입은 첫 단계·산출은 마"
    '지막 단계 값, 확인 내용은 확인 내용이 적힌 단계의 값이다. 공정 하나'
    '의 작업 내용(work)과 단계(stage)는 적혀 있지 않다.'
  ),
  ('작업 순서 (완제품 공정)'): (
    '완제품 공정은 공정번호 하나 안을 단계로 나눠 적었다. 정답 규칙은 작업 순서 (2차 모듈)과 같다 (steps, 공'
    '정 이름은 둘째 줄, 투입은 첫 단계·산출은 마지막 단계).'
  ),
  ('검사성적서'): (
    '단계별 수량 종합표의 비고는 불량이 나온 공정의 불량 원인이고(modules[].badCause), 불량이 없으면 빈칸(null)이다.'
  ),
}


def model_folder(model):
  """문서 폴더는 '모델명(카메라분류)' (예: LO-D100(디지털카메라))"""
  found = [
    d for d in os.listdir(DATA) if (d == model or d.startswith(model + '(')) and os.path.isdir(os.path.join(DATA, d))
  ]
  if len(found) != 1:
    raise SystemExit(f'{DATA} 안에 {model}(…) 폴더가 하나가 아님: {found}')
  return os.path.join(DATA, found[0])


def write(path, body, force):
  requested = Path(path)
  matches = [
    p
    for p in requested.parent.iterdir()
    if unicodedata.normalize('NFC', p.name) == unicodedata.normalize('NFC', requested.name)
  ]
  if len(matches) > 1:
    raise ValueError(f'유니코드가 같은 정답 파일이 중복됨: {path}')
  path = matches[0] if matches else requested
  if os.path.exists(path):
    old = json.loads(Path(path).read_text(encoding='utf-8'))
    same = all(old.get(k) == body.get(k) for k in ('expected', 'match', 'absent', 'src'))
    if '--check' in sys.argv:
      if not same:
        raise ValueError(f'생성 결과와 정답이 다름: {path}')
      return
    if same:
      return
    if not force:
      raise ValueError(f'기존 정답과 다릅니다. 덮어쓰려면 --force를 지정하세요: {path}')
  elif '--check' in sys.argv:
    raise ValueError(f'정답 파일이 없음: {path}')
  with open(path, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(body, f, ensure_ascii=False, indent=2)
    f.write('\n')


def main():
  args = [a for a in sys.argv[1:] if not a.startswith('--')]
  force = '--force' in sys.argv
  for jp in args or ['d100.json', 't400.json', 'f35.json', 'i100.json', 'd200.json']:
    jpath = jp if os.path.isabs(jp) else os.path.join(HERE, jp)
    MODEL, docs, model, J = build(jpath)
    folder = model_folder(MODEL)
    have = sorted(unicodedata.normalize('NFC', f) for f in os.listdir(folder) if f.endswith('.docx'))
    want = [f for f, _ in docs]
    if have != sorted(want):
      raise SystemExit(f'{folder} 의 docx {have} ≠ 정답 문서 {want}')
    jname = os.path.basename(jpath)
    for fname, g in docs:
      title = fname[3:-5]
      notes = NOTE_DOC.format(json=jname, today=TODAY)
      if title in EXTRA_NOTES and (
        title != '작업 순서 (1차 모듈)' or any(it.get('merge') for it in CFG['models'][MODEL]['items'])
      ):
        notes += ' ' + EXTRA_NOTES[title].format(model=MODEL)
      if title.startswith('검사성적서'):
        notes += ' ' + EXTRA_NOTES['검사성적서']
      write(
        os.path.join(folder, fname[:-5] + '.golden.json'),
        dict(
          file=fname,
          model=MODEL,
          scope='document',
          status='draft',
          reviewed_by=None,
          notes=notes,
          match=MATCH,
          absent=g.absent(),
          src=g.src(),
          expected=g.expected(),
        ),
        force,
      )
    write(
      os.path.join(folder, f'{MODEL}.golden.json'),
      dict(
        file=want,
        model=MODEL,
        scope='model',
        status='draft',
        reviewed_by=None,
        notes=NOTE_MODEL.format(json=jname, today=TODAY, n=len(docs))
        + ' '
        + EXTRA_NOTES['생산계획서'].format(model=MODEL),
        match=MATCH,
        absent=model.absent(),
        src=model.src(),
        expected=model.expected(),
      ),
      force,
    )
    e = model.expected()
    print(
      f'{MODEL}: 문서 {len(docs)}개 + 합본 1개 → {folder}  '
      f'(부품 {len(e[("parts")])}, 공정 {len(e[("tasks")])}, 모듈 {len(e[("modules")])}, 수입검사 {
        len(e[("iqc")])
      }, 검사 {len(e[("inspections")])}, '
      f'점검표 {len(e["units"])}, 사람 {len(e["people"])}, 문서 {len(e["documents"])})'
    )


if __name__ == '__main__':
  main()
