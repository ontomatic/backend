"""Generate side-by-side HTML comparisons of source documents and golden answers."""

import argparse
import glob
import html
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', 'data'))
OUT = os.path.join(DATA, '..', 'reports', 'review')
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SAMPLE = {'제품사양서', '생산계획서', '작업 순서 (1차 모듈)', '작업 순서 (2차 모듈)', '검사성적서 (완제품)'}
e = html.escape


def ptext(p):
  return ''.join(t.text or '' for t in p.iter(W + 't'))


def docx_html(path):
  root = ET.fromstring(zipfile.ZipFile(path).read('word/document.xml'))
  out = []
  for el in root.find(W + 'body'):
    if el.tag == W + 'p':
      t = ptext(el).strip()
      if not t:
        continue
      st = el.find(f'{W}pPr/{W}pStyle')
      s = st.get(W + 'val') if st is not None else ''
      tag = {'Heading1': 'h3', 'Heading2': 'h4'}.get(s, 'p')
      out.append(f'<{tag}>{e(t)}</{tag}>')
    elif el.tag == W + 'tbl':
      rows = []
      for _i, tr in enumerate(el.findall(W + 'tr')):
        cells = ['<br>'.join(e(ptext(p)) for p in tc.findall(W + 'p')) for tc in tr.findall(W + 'tc')]
        rows.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')
      out.append('<table>' + ''.join(rows) + '</table>')
  return '\n'.join(out)


def fmt(v):
  """골든 값 하나를 읽기 쉬운 글로"""
  if v is None:
    return '<i>없음(null)</i>'
  if isinstance(v, bool):
    return '예' if v else '아니오'
  if isinstance(v, list):
    if not v:
      return '<i>[ ]</i>'
    return '<br>'.join(fmt(x) for x in v)
  if isinstance(v, dict):
    return '<br>'.join(f'<b>{e(str(k))}</b>: {fmt(x)}' for k, x in v.items())
  return e(str(v))


def tag(src, arr, key, f, meta=None):
  keys = [f'{arr}[{key}].{f}', f'{arr}[].{f}', f]
  if meta:
    keys = [f'{arr}[{key}].meta.{meta}', f'{arr}[].meta.{meta}'] + keys
  t = next((src[k] for k in keys if k in src), '?')
  return f'<span class="t {t}">{t}</span>'


def golden_html(g):
  exp, src = g['expected'], g['src']
  out = []
  sc = [(k, exp[k]) for k in ('model', 'productName', 'specVersion', 'plannedQty', 'completedQty') if k in exp]
  if sc:
    out.append(
      '<h4>문서 전체 값</h4><table>'
      + ''.join(f'<tr><td>{k}</td><td>{fmt(v)} {tag(src, "", "", k)}</td></tr>' for k, v in sc)
      + '</table>'
    )
  for arr, keys in g['match'].items():
    items = exp.get(arr, [])
    if not items:
      continue
    fields = [f for f in dict.fromkeys(f for it in items for f in it)]

    def key_of(it: dict, keys: list[str] = keys) -> str:
      return '|'.join(str(it[k]) for k in keys)

    head = ''.join(f'<th>{f}</th>' for f in fields)
    body = []
    for it in items:
      k = key_of(it)
      tds = []
      for f in fields:
        if f not in it:
          tds.append("<td class='na'>—</td>")
          continue
        if f == 'meta':
          tds.append(
            '<td>'
            + '<br>'.join(f'<b>{e(mk)}</b>: {e(str(mv))} {tag(src, arr, k, f, mk)}' for mk, mv in it[f].items())
            + '</td>'
          )
        else:
          tds.append(f'<td>{fmt(it[f])} {tag(src, arr, k, f)}</td>')
      body.append('<tr>' + ''.join(tds) + '</tr>')
    out.append(f"<h4>{arr} ({len(items)})</h4><div class='sc'><table><tr>{head}</tr>{''.join(body)}</table></div>")
  ab = g.get('absent', [])
  if ab:
    # 같은 종류가 많으면 줄여 보인다
    out.append(
      f'<details><summary>채점하지 않는 칸 (absent '
      f'{len(ab)}'
      f")</summary><p class='ab'>"
      f'{e(", ".join(ab[:120]))}'
      f'{(" …" if len(ab) > 120 else "")}'
      f'</p></details>'
    )
  return '\n'.join(out)


CSS = (
  '\n:root{--bg:#fff;--fg:#1d2330;--mut:#667085;--line:#d0d5dd;--card'
  ':#f8f9fb;--a:#1f3864;--ja:#1b7f4b;--ga:#a15c07;--se:#5b3fa3}\n@med'
  'ia (prefers-color-scheme:dark){:root{--bg:#14171d;--fg:#e6e9ef;--'
  'mut:#98a2b3;--line:#363c48;--card:#1c2028;--a:#8fb0f0;--ja:#5fd49'
  'a;--ga:#f0b35a;--se:#b9a2f5}}\nbody{margin:0;background:var(--bg);'
  'color:var(--fg);font:14px/1.5 "Malgun Gothic",system-ui,sans-seri'
  'f}\nmain{max-width:1500px;margin:0 auto;padding:20px 16px 80px}\nh1'
  '{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 1'
  '6px}\ndetails.doc{border:1px solid var(--line);border-radius:8px;m'
  'argin:12px 0;background:var(--card)}\ndetails.doc>summary{cursor:p'
  'ointer;padding:10px 14px;font-weight:700;color:var(--a)}\ndetails.'
  'doc>summary .smp{font-weight:400;font-size:12px;color:var(--mut);'
  'margin-left:8px}\n.cols{display:grid;grid-template-columns:1fr 1fr'
  ';gap:16px;padding:0 14px 14px}\n@media (max-width:900px){.cols{gri'
  'd-template-columns:1fr}}\n.col{min-width:0}.col>h2{font-size:13px;'
  'margin:6px 0;color:var(--mut);text-transform:none}\ntable{border-c'
  'ollapse:collapse;width:100%;margin:6px 0;font-size:12.5px}\ntd,th{'
  'border:1px solid var(--line);padding:4px 7px;vertical-align:top;t'
  'ext-align:left}\nth{background:var(--card);font-weight:600}td.na{c'
  'olor:var(--mut);text-align:center}\n.sc{overflow-x:auto}h3{font-si'
  'ze:15px;margin:10px 0 4px}h4{font-size:13px;margin:12px 0 2px;col'
  'or:var(--a)}\n.t{font-size:10.5px;font-weight:700;border-radius:4p'
  'x;padding:0 4px;border:1px solid;white-space:nowrap}\n.t.자료{color:'
  'var(--ja)}.t.가상{color:var(--ga)}.t.설계{color:var(--se)}.t.\\?{color'
  ':#c00}\n.ab{font-size:12px;color:var(--mut)}.note{font-size:12px;c'
  'olor:var(--mut);border-left:3px solid var(--line);padding-left:8p'
  'x}\n'
)


def main():
  parser = argparse.ArgumentParser(description='사람 검수용 대조표 생성')
  parser.add_argument('--output', default=OUT)
  output = parser.parse_args().output
  os.makedirs(output, exist_ok=True)
  for folder in sorted(glob.glob(os.path.join(DATA, 'LO-*'))):
    model = os.path.basename(folder).split('(', 1)[0]
    parts = []
    gs = sorted(glob.glob(os.path.join(folder, '[0-9]*.golden.json')))
    for gp in gs:
      g = json.loads(Path(gp).read_text(encoding='utf-8'))
      title = re.sub(r'^\d+_|\.docx$', '', g['file'])
      smp = title in SAMPLE
      parts.append(
        f'<details class="doc"{" open" if smp else ""}><summary>{e(g["file"])}'
        f'<span class="smp">{"표본 · " if smp else ""}상태 {g["status"]}</span></summary>'
        f'<p class="note" style="margin:0 14px">{e(g["notes"])}</p>'
        f'<div class="cols"><div class="col"><h2>원문 (docx)</h2>{
          docx_html(
            os.path.join(
              folder,
              next(
                f
                for f in os.listdir(folder)
                if unicodedata.normalize(("NFC"), f) == unicodedata.normalize(("NFC"), g[("file")])
              ),
            )
          )
        }</div>'
        f'<div class="col"><h2>골든 (expected)</h2>{golden_html(g)}</div></div></details>'
      )
    page = (
      f'<!doctype html><html lang="ko"><head><me'
      f'ta charset="utf-8"><meta name="viewport"'
      f' content="width=device-width,initial-sca'
      f'le=1"><title>대조표 '
      f'{model}'
      f'</title><style>'
      f'{CSS}'
      f'</style></head><body><main><h1>골든 대조표 · '
      f'{model}'
      f'</h1><p class="sub">왼쪽 원문과 오른쪽 골든이 같은지 보'
      f'세요. 표본 5종은 펼쳐 두었습니다. 근거 표시: <span class='
      f'"t 자료">자료</span> 회사 자료 · <span class="t '
      f'가상">가상</span> 우리가 채운 값 · <span class="t '
      f'설계">설계</span> 생성기 규칙 · <span class="t ?"'
      f'>?</span> 표시 없음</p>'
      f'{"".join(parts)}'
      f'</main></body></html>'
    )
    path = os.path.join(output, f'대조표_{model}.html')
    Path(path).write_text(page, encoding='utf-8', newline='\n')
    print(model, len(gs), '문서 →', path, f'{os.path.getsize(path) // 1024}KB')


if __name__ == '__main__':
  main()
