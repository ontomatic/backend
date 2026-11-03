import re

KINDS = {
  '제품사양서': 'spec',
  'BOM': 'bom',
  '수입검사': 'iqc',
  '생산계획': 'plan',
  '작업 순서': 'route',
  '검사성적서': 'qc',
}
DEPARTMENTS = {
  'spec': 'R&D부서',
  'bom': 'R&D부서',
  'iqc': '품질부서',
  'qc': '품질부서',
  'plan': '생산부서',
  'route': '생산부서',
  'other': None,
}
ARRAYS = ('documents', 'people', 'parts', 'modules', 'tasks', 'iqc', 'inspections', 'units', 'handover')


def number(value: str | None) -> int | float | None:
  match = re.search(r'-?[\d,]+(?:\.\d+)?', value or '')
  if not match:
    return None
  result = float(match[0].replace(',', ''))
  return int(result) if result.is_integer() else result


def dates(value: str | None) -> list[str]:
  return re.findall(r'\d{4}-\d{2}-\d{2}', value or '')


def task_ids(value: str | None) -> list[str]:
  return re.findall(r'공정-\d{2}', value or '')


def lines(value: str) -> list[str]:
  return [line.strip() for line in value.split('\n') if line.strip()]


def new_part(name: str) -> dict:
  return dict(
    seq=0,
    code='',
    name=name,
    spec='',
    qtyPerUnit=None,
    sourcing='',
    supplier=None,
    taskId=None,
    module=None,
    accessory=False,
    detail=None,
    attrs={},
    usedIn=[],
  )


def extract(blocks: list[dict]) -> dict:
  end = next((i for i, b in enumerate(blocks) if b['t'] == 'p' and b['text'].startswith('부록')), len(blocks))
  body = blocks[:end]
  result = dict.fromkeys(('model', 'productName', 'specVersion', 'plannedQty', 'completedQty'))
  result.update({name: [] for name in ARRAYS})

  def person(name: str, **values: str | None) -> None:
    name = name.strip()
    if not name or name == '—':
      return
    current = next((p for p in result['people'] if p['name'] == name), None)
    if current is None:
      current = dict(name=name, dept=None, title=None, role=None)
      result['people'].append(current)
    for key, value in values.items():
      if current[key] is None:
        current[key] = value

  def task(identifier: str) -> dict:
    current = next((t for t in result['tasks'] if t['id'] == identifier), None)
    if current is None:
      current = dict.fromkeys(
        (
          'stage',
          'start',
          'end',
          'days',
          'module',
          'owner',
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
        )
      )
      current.update(id=identifier, name='', preds=[], assistants=[], steps=[])
      result['tasks'].append(current)
    return current

  def module(name: str) -> dict:
    current = next((m for m in result['modules'] if m['name'] == name), None)
    if current is None:
      current = dict.fromkeys(('level', 'qty', 'start', 'end', 'next', 'leader', 'badCause'))
      current['name'] = name
      result['modules'].append(current)
    return current

  for block in body:
    for row in block.get('rows', []):
      if row and row[0].startswith('모델명'):
        result['model'] = row[1].split('/')[0].strip()
        break
      if len(row) > 3 and row[2] == '상위 모델':
        result['model'] = row[3]
        break
    if result['model']:
      break

  doc = None
  heading = ''
  approval = []
  dept_of_doc = {}
  spec_rows = []
  for block in body:
    if block['t'] == 'h':
      if block['level'] == 1:
        title = block['text']
        kind = next((kind for prefix, kind in KINDS.items() if title.startswith(prefix)), 'other')
        department = next((v for k, v in dept_of_doc.items() if k.startswith(title) or title.startswith(k)), None)
        doc = dict(
          no='',
          title=title,
          kind=kind,
          dept=department or DEPARTMENTS[kind],
          version=None,
          date=None,
          meta={},
          approval=approval,
          basedOn=None,
          verdict=None,
        )
        result['documents'].append(doc)
        approval = []
        heading = ''
      else:
        heading = block['text']
      continue
    if block['t'] != 'table' or not block['rows']:
      continue
    rows = block['rows']
    head, data = rows[0], rows[1:]

    def is_table(*columns: str, header: list[str] = head) -> bool:
      return header[: len(columns)] == list(columns)

    if is_table('담당', '검토', '승인'):
      approval = []
      for i, role in enumerate(('담당', '검토', '승인')):
        values = (lines(data[0][i]) if data and len(data[0]) > i else []) + ['', '', '']
        approval.append(dict(role=role, name=values[0], title=values[1], date=values[2]))
      continue
    if is_table('부서', '직책', '이름'):
      for row in data:
        names, roles = lines(row[2]), lines(row[3])
        if len(names) == 1 and re.fullmatch(r'\d+명', names[0]):
          continue
        for i, name in enumerate(names):
          person(
            name,
            dept=row[0],
            title=re.sub(r'\s*\(.*\)$', '', row[1]),
            role=roles[i] if i < len(roles) else roles[0] if roles else None,
          )
    if doc is None:
      if is_table('순서', '담당', '문서'):
        dept_of_doc.update({row[2]: row[1] for row in data})
      continue
    if is_table('문서번호'):
      doc['meta'].update({row[i]: row[i + 1] for row in rows for i in range(0, len(row) - 1, 2) if row[i]})
      meta = doc['meta']
      doc['no'] = meta.get('문서번호', '')
      doc['version'] = meta.get('버전')
      found_dates = dates(meta.get('발행일', meta.get('검사일')))
      doc['date'] = found_dates[-1] if found_dates else None
      doc['basedOn'] = meta['근거 부품표'].split()[0] if meta.get('근거 부품표') else None
      if doc['kind'] == 'spec':
        result['specVersion'] = doc['version']
      if meta.get('상위 모델'):
        result['model'] = meta['상위 모델']
      if meta.get('완성 수량'):
        result['completedQty'] = number(meta['완성 수량'])
      if doc['kind'] == 'iqc' and meta.get('입고 수량') and result['plannedQty'] is None:
        result['plannedQty'] = number(meta['입고 수량'])
      continue
    if is_table('종합 판정'):
      doc['verdict'] = '합격' if '☑ 합격' in head[1] else '불합격' if '☑ 불합격' in head[1] else None
      continue
    kind = doc['kind']
    if kind == 'spec':
      if is_table('항목', '값'):
        for key, value in data:
          if key.startswith('모델명'):
            values = [v.strip() for v in value.split('/')]
            result['model'] = result['model'] or values[0]
            result['productName'] = values[1] if len(values) > 1 else None
      if is_table('부품', '구성 상세', '속성', '속성값'):
        spec_rows.extend(dict(section=heading, part=p, detail=d, attr=a, value=v) for p, d, a, v in data)
    elif kind == 'bom':
      if is_table('순번', '품목코드'):
        for row in data:
          match = re.fullmatch(r'(.*?)\s*\((.*)\)', row[2])
          part = new_part(match[1].strip() if match else row[2].strip())
          sourcing = row[4]
          source = (
            '구매' if sourcing.startswith('구매') else '자체 가공' if sourcing.startswith('자체 가공') else sourcing
          )
          suppliers = sourcing.split('·')
          part.update(
            seq=number(row[0]) or 0,
            code=row[1],
            spec=match[2].strip() if match else '',
            qtyPerUnit=number(row[3]),
            sourcing=source,
            supplier=suppliers[1].strip() if source == '구매' and len(suppliers) > 1 else None,
            taskId=next(iter(task_ids(sourcing)), None),
          )
          result['parts'].append(part)
      if is_table('확인 항목', '담당', '상태'):
        result['handover'] = [dict(item=item, owner=owner, status=status) for item, owner, status in data]
        for _, owner, _ in data:
          match = re.fullmatch(r'(\S+부서)\s+(\S+)\s+(.+)', owner)
          if match:
            person(match[2], dept=match[1], title=match[3])
      if head and all(c.endswith('부서') for c in head) and data and any('서명' in c for c in data[0]):
        for department, cell in zip(head, data[0], strict=True):
          name, *title = lines(cell)[0].split()
          person(name, dept=department, title=' '.join(title) or None)
    elif kind == 'iqc' and is_table('부품', '입고 수량'):
      result['iqc'] = [dict(part=p, qty=number(q), check=c, verdict=v) for p, q, c, v in data]
    elif kind == 'plan':
      if is_table('품목', '수량', '시작'):
        for row in data:
          name = '완제품 공정' if re.fullmatch(r'LO-\S+ 카메라', row[0]) else row[0]
          current = module(name)
          current.update(qty=number(row[1]), start=next(iter(dates(row[2])), None), end=next(iter(dates(row[3])), None))
          next_module = re.match(r'→\s*(.+)', row[4] if len(row) > 4 else '')
          current['next'] = next_module[1].strip() if next_module else None
          if name == '완제품 공정' and result['plannedQty'] is None:
            result['plannedQty'] = current['qty']
      if is_table('공정번호', '공정', '시작'):
        for row in data:
          task(row[0]).update(
            name=row[1],
            start=next(iter(dates(row[2])), None),
            end=next(iter(dates(row[3])), None),
            days=number(row[4]),
            preds=task_ids(row[5]),
          )
      if is_table('품목', '공정', '기간'):
        for row in data:
          identifier = next(iter(task_ids(row[1])), None)
          if identifier is None:
            continue
          current = task(identifier)
          current.update(
            module=row[0],
            owner=row[4] if row[4] and row[4] != '—' else None,
            assistants=[s.strip() for s in row[5].split(',') if s.strip()] if row[5] != '—' else [],
            crew=number(row[6]),
          )
          module(row[0])['leader'] = row[3] or None
          person(row[3], dept='생산부서', title='파트장')
          for name in [current['owner'], *current['assistants']]:
            if name:
              person(name, dept='생산부서', title='작업자')
    elif kind == 'route':
      if is_table('순서', '공정번호'):
        if heading:
          current = module(heading)
          level = re.search(r'\((1차 모듈|2차 모듈|완제품)\)', doc['title'])
          current['level'] = current['level'] or (level[1] if level else None)
        rows_of = {}
        for row in data:
          identifiers = task_ids(row[1])
          if len(identifiers) == 1:
            rows_of.setdefault(identifiers[0], []).append(row)
        for identifier, group in rows_of.items():
          if len(group) < 2:
            continue
          current = task(identifier)
          steps = []
          for row in group:
            inputs, *outputs = [v.strip() for v in row[5].split('→')]
            steps.append(
              dict(
                name=next(iter(lines(row[2])), ''),
                work=row[3] or None,
                input=inputs or None,
                output=(outputs[0] or None) if outputs else None,
                check=row[6] if row[6] and row[6] != '-' else None,
              )
            )
          names = lines(group[0][2])
          if not current['name'] and len(names) > 1:
            current['name'] = names[1].removeprefix('(').removesuffix(')')
          current.update(
            steps=steps,
            line=group[0][4],
            input=steps[0]['input'],
            output=steps[-1]['output'],
            check=next((s['check'] for s in steps if s['check']), None),
            routeDoc=doc['no'],
          )
          current['module'] = current['module'] or heading or None
        for row in data:
          identifiers = task_ids(row[1])
          for i, identifier in enumerate(identifiers):
            if len(rows_of.get(identifier, [])) > 1:
              continue
            current = task(identifier)
            names = lines(row[2])
            if not current['name'] and len(identifiers) == 1 and names:
              current['name'] = names[0]
            if len(names) > 1:
              current['stage'] = re.sub(r'[()]', '', names[1])
            works = row[3].split(' / ')
            inputs, *outputs = [s.strip() for s in row[5].split('→')]
            current.update(
              work=works[i] if len(works) == len(identifiers) else row[3],
              line=row[4],
              input=inputs,
              output=outputs[0] if outputs else None,
              check=row[6] if row[6] and row[6] != '-' else None,
              routeDoc=doc['no'],
            )
            current['module'] = current['module'] or heading or None
    elif kind == 'qc':
      level = re.search(r'\((.+)\)', doc['title'])
      if is_table('공정번호', '공정', '투입'):
        if heading:
          current = module(heading)
          if level:
            current['level'] = level[1]
          if doc['meta'].get('공정책임자'):
            current['leader'] = doc['meta']['공정책임자']
            person(current['leader'])
        for row in data:
          current = task(row[0])
          current['name'] = current['name'] or row[1]
          current['module'] = current['module'] or heading or None
          current.update(inQty=number(row[2]), good=number(row[3]), bad=number(row[4]), qcDoc=doc['no'])
      if is_table('항목', '공정번호', '허용 기준'):
        for row in data:
          result['inspections'].append(
            dict(
              doc=doc['no'],
              item=row[0],
              taskId=next(iter(task_ids(row[1])), row[1]),
              standard=row[2],
              value=row[3],
              inspector=row[4],
              verdict=row[5],
            )
          )
          person(row[4])
      if is_table('구분', '공정번호', '양품 / 투입'):
        for row in data:
          if row[0]:
            module(row[0])['badCause'] = row[head.index('비고')].strip() or None if '비고' in head else None
      if is_table('분류', '관련 공정'):
        serial = re.search(r'제품번호\s+(\S+)', heading)
        result['units'].append(
          dict(
            serial=serial[1] if serial else heading,
            checks=[dict(cls=r[0], taskIds=task_ids(r[1]), item=r[2], standard=r[3], result=r[4]) for r in data],
          )
        )

  def split(value: str | None) -> list[str]:
    return [s.strip() for s in re.split(r'\s*[,+]\s*', value or '') if s.strip()]

  for current in sorted(result['tasks'], key=lambda t: t['id']):
    for name in split(current['input']):
      assembled = any(
        t['id'] in current['preds'] and t['stage'] != '부품 준비' and name in split(t['output'])
        for t in result['tasks']
      )
      part = next((p for p in result['parts'] if not assembled and p['name'] == name), None)
      if part and current['id'] not in part['usedIn']:
        part['usedIn'].append(current['id'])
        part['module'] = part['module'] or current['module']
  standalone = not result['parts']
  for row in spec_rows:
    part = next((p for p in result['parts'] if p['name'] == row['part']), None)
    if part is None and standalone:
      part = new_part(row['part'])
      result['parts'].append(part)
    if part is None:
      continue
    base = re.search(r'\d+\.\s*(\S+)\s*사양', row['section'])
    if '부속품' in row['section']:
      part['accessory'] = True
    elif not part['usedIn'] and part['module'] is None:
      part['module'] = next((m['name'] for m in result['modules'] if base and base[1] in m['name']), None)
    if row['detail'] != '대표 설계 치수':
      part['detail'] = part['detail'] or row['detail']
    part['attrs'][row['attr']] = row['value']
  if not any('부속품' in r['section'] for r in spec_rows) and any(t['input'] for t in result['tasks']):
    for part in result['parts']:
      if not part['usedIn'] and not part['module']:
        part['accessory'] = True
  knows_org = any(p['dept'] for p in result['people'])
  for doc in result['documents']:
    for signature in doc['approval']:
      person(
        signature['name'],
        title=signature['title'],
        dept='경영' if signature['title'] == '대표이사' else None if knows_org else doc['dept'],
      )
  return result
