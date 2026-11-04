import re
from collections import Counter
from datetime import date, timedelta

RULE_NAMES = {
  'R01': '문서번호',
  'R02': '결재란',
  'R03': '결재일',
  'R04': '결재자 조직',
  'R05': '날짜 형식',
  'R06': 'BOM 형식',
  'R07': '자체 가공 공정',
  'R08': '수입검사 대상',
  'R09': '입고 수량',
  'R10': '선행 관계',
  'R11': '공정 기간',
  'R12': '생산 수량',
  'R13': '검사 공정·검사자',
  'R14': '작업 인원',
  'R15': '검사 판정',
  'R16': '부품 모듈',
  'R17': '모듈 단계',
}
HOLIDAYS = {'2026-12-25', '2027-01-01'}


def valid_date(value: str | None) -> bool:
  try:
    return bool(value and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) and date.fromisoformat(value))
  except ValueError:
    return False


def validate(data: dict) -> list[dict]:
  """Check R01–R17 using extracted document evidence, independently of golden answers."""
  issues = []

  def add(rule: str, message: str) -> None:
    issues.append(dict(rule=rule, level='error', message=message))

  tasks = {t['id']: t for t in data['tasks']}
  people = {p['name']: p for p in data['people']}
  modules = {m['name']: m for m in data['modules']}
  numbers = Counter(d['no'] for d in data['documents'])
  for doc in data['documents']:
    identifier = doc['no']
    if not re.fullmatch(r'[A-Za-z가-힣]+-\d{2}', identifier) or numbers[identifier] != 1:
      add('R01', f'{doc["title"]}: 문서번호 형식 또는 중복: {identifier}')
    if len(doc['approval']) != 3 or any(not a['name'] or not a['title'] or not a['date'] for a in doc['approval']):
      add('R02', f'{identifier}: 담당·검토·승인 결재란에 이름·직책·날짜가 필요함')
    for approval in doc['approval']:
      if approval['date'] and approval['date'] != doc['date']:
        add('R03', f'{identifier}: {approval["role"]} 결재일이 문서 날짜와 다름')
      if any(p['role'] for p in data['people']) and not people.get(approval['name'], {}).get('dept'):
        add('R04', f'{identifier}: 조직에서 확인할 수 없는 결재자: {approval["name"]}')
    for field in ('발행일', '검사일'):
      if field in doc['meta']:
        values = re.split(r'\s*~\s*', doc['meta'][field])
        if not values or not all(valid_date(v) for v in values):
          add('R05', f'{identifier}: 잘못된 {field}: {doc["meta"][field]}')
    if doc['kind'] in ('iqc', 'qc') and doc['verdict'] != '합격':
      add('R15', f'{identifier}: 종합 합격 판정이 없음')

  codes = Counter(p['code'] for p in data['parts'])
  purchased = {p['name']: p for p in data['parts'] if p['sourcing'] == '구매'}
  iqc = Counter(row['part'] for row in data['iqc'])
  for part in data['parts']:
    code = part['code']
    if (
      code != f'부품-{part["seq"]:02d}'
      or codes[code] != 1
      or part['qtyPerUnit'] is None
      or part['qtyPerUnit'] <= 0
      or part['sourcing'] not in ('구매', '자체 가공')
    ):
      add('R06', f'{part["name"]}: 품목코드·대당 수량·조달 구분이 잘못됨')
    if part['sourcing'] == '자체 가공' and part['taskId'] not in tasks:
      add('R07', f'{part["name"]}: 자체 가공 공정이 없음: {part["taskId"]}')
    if part['name'] in purchased and iqc[part['name']] != 1:
      add('R08', f'{part["name"]}: 구매 부품 수입검사 누락 또는 중복')
    if not part['accessory'] and part['module'] not in modules:
      add('R16', f'{part["name"]}: 속하는 모듈을 확인할 수 없음')
  for row in data['iqc']:
    part = purchased.get(row['part'])
    if part is None:
      add('R08', f'{row["part"]}: BOM의 구매 부품이 아닌 수입검사 대상')
    elif (
      part['qtyPerUnit'] is not None
      and data['plannedQty'] is not None
      and row['qty'] != part['qtyPerUnit'] * data['plannedQty']
    ):
      add('R09', f'{row["part"]}: 입고 수량이 대당 수량 × 생산 수량과 다름')
    if row['verdict'] != '합격':
      add('R15', f'{row["part"]}: 수입검사 판정이 합격이 아님')

  for task in data['tasks']:
    identifier = task['id']
    valid_days = valid_date(task['start']) and valid_date(task['end'])
    if not valid_days:
      add('R05', f'{identifier}: 시작일 또는 종료일 형식이 잘못됨')
    for pred in task['preds']:
      previous = tasks.get(pred)
      if previous is None:
        add('R10', f'{identifier}: 존재하지 않는 선행 공정: {pred}')
      elif valid_date(task['start']) and valid_date(previous['end']) and previous['end'] >= task['start']:
        add('R10', f'{identifier}: 선행 공정 {pred} 종료 뒤에 시작해야 함')
    if valid_days:
      start, end = date.fromisoformat(task['start']), date.fromisoformat(task['end'])
      days = sum(
        (start + timedelta(days=i)).weekday() < 5 and (start + timedelta(days=i)).isoformat() not in HOLIDAYS
        for i in range((end - start).days + 1)
      )
      if end < start or days != task['days']:
        add('R11', f'{identifier}: 기간이 시작일·종료일의 근무일 수와 다름')
    quantities = [task['inQty'], task['good'], task['bad']]
    if any(v is None or v < 0 for v in quantities) or task['inQty'] != task['good'] + task['bad']:
      add('R12', f'{identifier}: 투입 = 양품 + 불량이 성립하지 않음')
    previous_good = [tasks[p]['good'] for p in task['preds'] if p in tasks]
    if all(v is not None for v in previous_good):
      expected = min(previous_good, default=data['plannedQty'])
      if expected is not None and task['inQty'] != expected:
        add('R12', f'{identifier}: 투입 수량이 선행 공정 양품 수량과 다름')
    names = [task['owner'], *task['assistants']]
    if not task['owner'] or task['crew'] != 2 + len(task['assistants']) or len(set(names)) != len(names):
      add('R14', f'{identifier}: 책임자·담당자·보조담당자와 인원 수가 다름')

  visiting, visited = set(), set()

  def visit(identifier: str) -> None:
    if identifier in visiting:
      add('R10', f'{identifier}: 선행 공정 관계에 순환이 있음')
      return
    if identifier in visited:
      return
    visiting.add(identifier)
    for pred in tasks[identifier]['preds']:
      if pred in tasks:
        visit(pred)
    visiting.remove(identifier)
    visited.add(identifier)

  for identifier in tasks:
    visit(identifier)
  for inspection in data['inspections']:
    task = tasks.get(inspection['taskId'])
    if task is None or task['owner'] != inspection['inspector']:
      add('R13', f'{inspection["doc"]} {inspection["item"]}: 검사 공정 또는 검사자가 배정과 다름')
    if inspection['verdict'] != '합격':
      add('R15', f'{inspection["doc"]} {inspection["item"]}: 검사 판정이 합격이 아님')
  for module in data['modules']:
    if module['level'] not in ('1차 모듈', '2차 모듈', '완제품'):
      add('R17', f'{module["name"]}: 모듈 단계를 확인할 수 없음')
  return issues
