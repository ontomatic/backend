from io import BytesIO
from pathlib import Path

import pytest
from backend.core.jwt import create_access_token
from backend.models import File
from backend.models.file import FileStatus
from backend.models.workflow import ProductionJob, Specification, WorkDocument
from docx import Document
from httpx2 import Response
from sqlalchemy import func, select


@pytest.fixture
def automatic_upload(workspace: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
  with workspace['factory']() as session:
    spec = Specification(
      code='CAM', name='카메라', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
    )
    session.add(spec)
    session.flush()
    targets = {
      key: {
        'id': key,
        'code': code,
        'name': name,
        'kind': kind,
        'version': 1,
        'round': 2,
        'plan_version': 3,
        'status': 'inspection',
      }
      for key, code, name, kind in (
        ('sensor', 'MAT-SENSOR', '센서 칩 (실리콘)', 'material'),
        ('glass', 'MAT-GLASS', '보호 유리', 'material'),
        ('screw', 'MAT-SCREW', '나사', 'material'),
        ('part', 'PART', '렌즈 가공', 'component'),
        ('module', 'MODULE', '렌즈 모듈', 'assembly'),
        ('product', 'CAM', '카메라', 'product'),
      )
    }
    targets['part']['process_code'] = 'P-01'
    targets['inventory'] = {**targets['part'], 'id': 'inventory', 'inventory_of': 'part'}
    job = ProductionJob(
      name='자동 문서 연결',
      specification_id=spec.id,
      quantity=360,
      targets=targets,
      created_by=workspace['users']['pm'].id,
    )
    file = File(
      uploader_id=workspace['users']['qa'].id,
      bucket='test',
      key='original',
      original_filename='원본.csv',
      content_type='text/csv',
      status=FileStatus.UPLOADED,
    )
    session.add_all([job, file])
    session.commit()
  original = {'data': '품목코드,품목명,측정값\nMAT-SENSOR,센서 칩,8\nMAT-GLASS,보호 유리,9\n'.encode()}

  class Storage:
    def download(self, key: str, stream: object) -> None:
      stream.write(original['data'])

  monkeypatch.setattr('backend.services.work_documents.get_storage', lambda bucket: Storage())
  return {
    **workspace,
    'job': job,
    'file': file,
    'original': original,
    'body': {'file_id': file.id, 'kind': 'auto', 'job_id': job.id},
    'headers': {'Authorization': f'Bearer {create_access_token(workspace["users"]["qa"].id)}'},
  }


def attach(upload: dict, **changes: object) -> Response:
  return upload['client'].post(
    '/api/v1/workspace/documents', json={**upload['body'], **changes}, headers=upload['headers']
  )


def test_upload_identifies_only_document_targets_and_current_scope(automatic_upload: dict) -> None:
  # Given a report containing two of three materials, when uploaded without selections, then only its rows are linked.
  response = attach(automatic_upload)
  assert response.status_code == 201, response.text
  doc = response.json()
  assert doc['kind'] == 'incoming_inspection'
  assert doc['scope']['target_ids'] == ['sensor', 'glass']
  assert (doc['scope']['round'], doc['scope']['plan_version']) == (2, 3)
  assert doc['candidates']['status'] == 'ready'
  assert doc['candidates']['data']['rows'][0]['item_code'] == 'MAT-SENSOR'
  assert attach(automatic_upload).json()['id'] == doc['id']
  with automatic_upload['factory']() as session:
    assert session.scalar(select(func.count()).select_from(WorkDocument)) == 1
    assert session.get(ProductionJob, automatic_upload['job'].id).targets == automatic_upload['job'].targets


@pytest.mark.parametrize(
  'content,kind,targets',
  [
    ('공정번호,투입,양품,불량\nP-01,360,358,2\n', 'inspection_module1', ['part']),
    ('품목명,허용 기준,측정값\n렌즈 모듈,8 mm,8\n', 'inspection_module2', ['module']),
    ('item_code,version,criterion,measured_value\nCAM,1,8 mm,8\n', 'inspection_final', ['product']),
    ('품목명,측정값\n센서 MAT-SENSOR (실리콘),8\n', 'incoming_inspection', ['sensor']),
  ],
)
def test_quality_kind_is_inferred_from_identified_stage(
  automatic_upload: dict, content: str, kind: str, targets: list[str]
) -> None:
  # Given Korean or canonical table identities, when uploading, then the inspection stage follows the actual target.
  automatic_upload['original']['data'] = content.encode()
  response = attach(automatic_upload)
  assert response.status_code == 201, response.text
  assert response.json()['kind'] == kind
  assert response.json()['scope']['target_ids'] == targets


@pytest.mark.parametrize(
  'failure',
  [
    'unknown',
    'ambiguous',
    'version',
    'mixed_scope',
    'mixed_stage',
    'conflicting_identity',
    'fixed',
    'not_report',
    'unreadable',
  ],
)
def test_automatic_upload_rejects_uncertain_or_fixed_evidence(automatic_upload: dict, failure: str) -> None:
  # Given uncertain identities or fixed evidence, when identifying a report, then no incorrect connection is saved.
  with automatic_upload['factory']() as session:
    job = session.get(ProductionJob, automatic_upload['job'].id)
    targets = {key: dict(target) for key, target in job.targets.items()}
    if failure == 'unknown':
      automatic_upload['original']['data'] = b'item_code,measured_value\nUNKNOWN,8\n'
    elif failure == 'ambiguous':
      targets['other'] = {**targets['sensor'], 'id': 'other', 'code': 'OTHER'}
      automatic_upload['original']['data'] = '품목명,측정값\n센서 칩 (실리콘),8\n'.encode()
    elif failure == 'version':
      targets['other'] = {**targets['sensor'], 'id': 'other', 'version': 2}
    elif failure == 'mixed_scope':
      targets['glass']['round'] = 3
    elif failure == 'mixed_stage':
      automatic_upload['original']['data'] = b'item_code,measured_value\nMAT-SENSOR,8\nPART,9\n'
    elif failure == 'conflicting_identity':
      automatic_upload['original']['data'] = b'item_code,process_code,measured_value\nPART,P-02,8\n'
    elif failure == 'fixed':
      targets['sensor']['status'] = 'passed'
    elif failure == 'not_report':
      automatic_upload['original']['data'] = b'item_code,quantity\nMAT-SENSOR,360\n'
    else:
      automatic_upload['original']['data'] = b'\xff\xfe'
    job.targets = targets
    session.commit()
  response = attach(automatic_upload)
  assert response.status_code == (409 if failure == 'fixed' else 422), response.text
  with automatic_upload['factory']() as session:
    assert session.scalar(select(func.count()).select_from(WorkDocument)) == 0


def test_explicit_item_version_resolves_ambiguity_and_client_scope_is_not_guessed(automatic_upload: dict) -> None:
  # Given two item versions, when the report identifies v2, then only that version and its current scope are used.
  with automatic_upload['factory']() as session:
    job = session.get(ProductionJob, automatic_upload['job'].id)
    job.targets = {**job.targets, 'v2': {**job.targets['sensor'], 'id': 'v2', 'version': 2, 'round': 4}}
    session.commit()
  automatic_upload['original']['data'] = b'item_code,version,measured_value\nMAT-SENSOR,2,8\n'
  response = attach(automatic_upload, target_ids=['glass'], round=99, plan_version=99)
  assert response.status_code == 201, response.text
  assert response.json()['scope']['target_ids'] == ['v2']
  assert response.json()['scope']['round'] == 4
  assert response.json()['scope']['plan_version'] == 3


@pytest.mark.parametrize('product_code,summary', [('CAM', '카메라'), ('Lo-D200', 'LO-D200 카메라')])
def test_production_plan_identifies_summary_target_without_checkboxes(
  automatic_upload: dict, product_code: str, summary: str
) -> None:
  # Given a plan before process registration, when uploaded without target IDs, then its product summary is linked.
  with automatic_upload['factory']() as session:
    session.get(File, automatic_upload['file'].id).uploader_id = automatic_upload['users']['pm'].id
    job = session.get(ProductionJob, automatic_upload['job'].id)
    job.targets = {**job.targets, 'product': {**job.targets['product'], 'code': product_code}}
    session.commit()
  automatic_upload['original']['data'] = f'품목,수량,시작,종료\n{summary},360,2026-11-02,2026-11-03\n'.encode()
  automatic_upload['headers'] = {'Authorization': f'Bearer {create_access_token(automatic_upload["users"]["pm"].id)}'}
  response = attach(automatic_upload, kind='production_plan', plan_version=1)
  assert response.status_code == 201, response.text
  assert response.json()['scope']['target_ids'] == ['product']
  assert response.json()['scope']['plan_version'] == 1


@pytest.mark.parametrize('other_code', ['LO-D200', 'Lo-D200'])
def test_plan_summary_rejects_ambiguous_codes_and_versions(automatic_upload: dict, other_code: str) -> None:
  # Given indistinguishable textual codes, when linking a summary, then no target is guessed.
  with automatic_upload['factory']() as session:
    session.get(File, automatic_upload['file'].id).uploader_id = automatic_upload['users']['pm'].id
    job = session.get(ProductionJob, automatic_upload['job'].id)
    product = {**job.targets['product'], 'code': 'Lo-D200'}
    other = {**product, 'id': 'other', 'code': other_code, 'version': 2 if other_code == 'Lo-D200' else 1}
    job.targets = {**job.targets, 'product': product, 'other': other}
    session.commit()
  automatic_upload['original']['data'] = '품목,수량,시작,종료\nLO-D200 카메라,360,2026-11-02,2026-11-03\n'.encode()
  automatic_upload['headers'] = {'Authorization': f'Bearer {create_access_token(automatic_upload["users"]["pm"].id)}'}
  response = attach(automatic_upload, kind='production_plan', plan_version=1)
  assert response.status_code == 422, response.text
  with automatic_upload['factory']() as session:
    assert session.scalar(select(func.count()).select_from(WorkDocument)) == 0


@pytest.mark.parametrize('marker', ['수입검사-03', '검사-06', '제목 불일치'])
def test_docx_document_kind_and_locations(automatic_upload: dict, marker: str) -> None:
  # Given a DOCX report, when identifying its scope, then its own reference must agree and locations are preserved.
  doc = Document()
  if marker == '제목 불일치':
    doc.add_heading('검사성적서 (1차 모듈)', 1)
  table = doc.add_table(rows=1, cols=2)
  table.cell(0, 0).text, table.cell(0, 1).text = '문서번호', f'CAM-{marker}'
  table = doc.add_table(rows=2, cols=2)
  for row, values in zip(table.rows, [('품목코드', '측정값'), ('MAT-SENSOR', '8')], strict=True):
    for cell, value in zip(row.cells, values, strict=True):
      cell.text = value
  stream = BytesIO()
  doc.save(stream)
  automatic_upload['original']['data'] = stream.getvalue()
  with automatic_upload['factory']() as session:
    session.get(File, automatic_upload['file'].id).original_filename = '원본.docx'
    session.commit()
  response = attach(automatic_upload)
  if marker != '수입검사-03':
    assert response.status_code == 422, response.text
    return
  assert response.status_code == 201, response.text
  assert response.json()['scope']['target_ids'] == ['sensor']
  row = response.json()['candidates']['data']['rows'][0]
  assert row['block_index'] == 2
  assert row['row'] == '2'
  assert row['document_number'] == 'CAM-수입검사-03'


@pytest.mark.parametrize('registered_related_processes', [True, False])
def test_final_report_ignores_stage_summaries_and_related_process_checklists(
  automatic_upload: dict, registered_related_processes: bool
) -> None:
  # Given the actual final report with prior-stage summaries and three sample checklists.
  fixture = Path(__file__).parent / 'fixtures' / 'final_inspection_lo_d100.docx'
  automatic_upload['original']['data'] = fixture.read_bytes()
  with automatic_upload['factory']() as session:
    session.get(File, automatic_upload['file'].id).original_filename = fixture.name
    job = session.get(ProductionJob, automatic_upload['job'].id)
    targets = {'product': {**job.targets['product'], 'code': 'LO-D100', 'process_code': 'D100-16'}}
    if registered_related_processes:
      targets.update(
        {
          f'process:D100-{index:02}': {
            **job.targets['module' if index in (9, 15) else 'part'],
            'id': f'process:D100-{index:02}',
            'code': f'D100-{index:02}',
            'process_code': f'D100-{index:02}',
            'status': 'passed',
            'round': 1,
            'plan_version': 2,
          }
          for index in range(1, 16)
        }
      )
    job.targets = targets
    session.commit()

  # When the unchanged file is uploaded without choosing its kind or targets.
  response = attach(automatic_upload)

  # Then only the current final product is linked while all original evidence remains available.
  assert response.status_code == 201, response.text
  doc = response.json()
  assert doc['kind'] == 'inspection_final'
  assert doc['scope']['target_ids'] == ['product']
  assert (doc['scope']['round'], doc['scope']['plan_version']) == (2, 3)
  assert len(doc['blocks']) == 21
  rows = doc['candidates']['data']['rows']
  final = next(row for row in rows if row['block_index'] == 6)
  assert (final['process_codes'], final['good_quantity'], final['defect_quantity']) == ('D100-16', '116', '1')
  assert final['document_number'] == 'D100-검사-11'
  assert sum(row['block_index'] in (14, 17, 20) for row in rows) == 27
  assert attach(automatic_upload).json()['id'] == doc['id']
  with automatic_upload['factory']() as session:
    assert session.get(ProductionJob, job.id).targets == targets


@pytest.mark.parametrize('role', ['rd', 'qa', 'pm'])
def test_automatic_upload_urls_remain_quality_owned(
  automatic_upload: dict, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
  # Given automatic quality identification, when requesting storage access, then other departments remain blocked.
  class Storage:
    def get_upload_url(self, key: str, *, content_type: str) -> str:
      return 'https://storage.example/upload'

  monkeypatch.setattr('backend.services.upload.get_storage', lambda bucket: Storage())
  response = automatic_upload['client'].post(
    '/api/v1/uploads',
    json={'kind': 'auto', 'files': [{'filename': '원본.csv', 'content_type': 'text/csv'}]},
    headers={'Authorization': f'Bearer {create_access_token(automatic_upload["users"][role].id)}'},
  )
  assert response.status_code == (200 if role == 'qa' else 403), response.text
