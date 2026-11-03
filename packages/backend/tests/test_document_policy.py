import pytest
from backend.core.jwt import create_access_token
from backend.models import File
from backend.models.file import FileStatus
from backend.models.workflow import ProductionJob, Specification, WorkDocument, WorkflowEvent
from sqlalchemy import func, select

DOCUMENTS = [
  ('product_detail', 'rd', None),
  ('bom_transfer', 'rd', None),
  ('incoming_inspection', 'qa', 'material'),
  ('production_plan', 'pm', None),
  ('work_instruction_module1', 'pm', 'component'),
  ('inspection_module1', 'qa', 'component'),
  ('work_instruction_lens', 'pm', 'assembly'),
  ('work_instruction_body', 'pm', 'assembly'),
  ('inspection_module2', 'qa', 'assembly'),
  ('work_instruction_final', 'pm', 'product'),
  ('inspection_final', 'qa', 'product'),
]


@pytest.mark.parametrize('kind,owner,target_kind', DOCUMENTS)
@pytest.mark.parametrize('role', ['rd', 'qa', 'pm'])
def test_upload_urls_only_allow_the_owning_department(
  workspace: dict, monkeypatch: pytest.MonkeyPatch, kind: str, owner: str, target_kind: str | None, role: str
) -> None:
  # Given a declared document kind, when issuing URLs, then only its owning department can upload it.
  calls = []

  class Storage:
    def get_upload_url(self, key: str, *, content_type: str) -> str:
      calls.append(key)
      return 'https://storage.example/upload'

  monkeypatch.setattr('backend.services.upload.get_storage', lambda bucket: Storage())
  response = workspace['client'].post(
    '/api/v1/uploads',
    json={'kind': kind, 'files': [{'filename': '원본.DOCX', 'content_type': 'application/octet-stream'}]},
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"][role].id)}'},
  )
  assert response.status_code == (200 if role == owner else 403), response.text
  assert len(calls) == (1 if role == owner else 0)
  with workspace['factory']() as session:
    assert session.scalar(select(func.count()).select_from(File)) == len(calls)


@pytest.mark.parametrize(
  'kind', [None, 'drawing', 'photo', 'conformity', 'grade', 'test_report', 'assignment', 'other']
)
def test_upload_rejects_missing_or_unlisted_document_kinds(workspace: dict, kind: str | None) -> None:
  # Given an obsolete or missing kind, when requesting upload URLs, then the API rejects it before storage access.
  body = {'files': [{'filename': '원본.csv', 'content_type': 'text/csv'}]}
  if kind is not None:
    body['kind'] = kind
  response = workspace['client'].post(
    '/api/v1/uploads',
    json=body,
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["rd"].id)}'},
  )
  assert response.status_code == 422, response.text


@pytest.mark.parametrize('filename', ['사진.png', '문서.exe', '문서.docx.exe'])
def test_upload_rejects_unsupported_formats(workspace: dict, filename: str) -> None:
  # Given an unsupported file extension, when requesting a URL, then no file record is created.
  response = workspace['client'].post(
    '/api/v1/uploads',
    json={'kind': 'product_detail', 'files': [{'filename': filename, 'content_type': 'application/octet-stream'}]},
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"]["rd"].id)}'},
  )
  assert response.status_code == 422, response.text
  with workspace['factory']() as session:
    assert session.scalar(select(func.count()).select_from(File)) == 0


@pytest.mark.parametrize('kind,owner,expected_target', DOCUMENTS)
@pytest.mark.parametrize('target_kind', ['material', 'component', 'assembly', 'product'])
def test_document_connections_enforce_department_and_process_stage(
  workspace: dict, kind: str, owner: str, expected_target: str | None, target_kind: str
) -> None:
  # Given an owned original, when connecting it, then only the document's process stage is accepted.
  with workspace['factory']() as session:
    spec = Specification(
      code='CAM', name='카메라', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
    )
    session.add(spec)
    session.flush()
    job = ProductionJob(
      name='공정 확인',
      specification_id=spec.id,
      quantity=1,
      targets={'target': {'kind': target_kind, 'round': 1, 'plan_version': 0, 'status': 'waiting'}},
      created_by=workspace['users']['pm'].id,
    )
    file = File(
      uploader_id=workspace['users'][owner].id,
      bucket='test',
      key='original.csv',
      original_filename='원본.csv',
      content_type='text/csv',
      status=FileStatus.UPLOADED,
    )
    session.add_all([job, file])
    session.commit()
    body = {'file_id': file.id, 'kind': kind}
    if owner == 'rd':
      body['specification_id'] = spec.id
    else:
      body.update(job_id=job.id, target_ids=['target'], plan_version=1 if owner == 'pm' else 0)
  response = workspace['client'].post(
    '/api/v1/workspace/documents',
    json=body,
    headers={'Authorization': f'Bearer {create_access_token(workspace["users"][owner].id)}'},
  )
  allowed = owner == 'rd' or target_kind == expected_target or (kind == 'production_plan' and target_kind != 'material')
  assert response.status_code == (201 if allowed else 422), response.text


@pytest.mark.parametrize(
  'kind,owner', [('product_detail', 'rd'), ('incoming_inspection', 'qa'), ('production_plan', 'pm')]
)
def test_reconnecting_an_original_after_another_document_does_not_duplicate_it(
  workspace: dict, kind: str, owner: str
) -> None:
  # Given two originals connected to the same specification or production scope.
  with workspace['factory']() as session:
    spec = Specification(
      code='CAM', name='카메라', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
    )
    session.add(spec)
    session.flush()
    job = ProductionJob(
      name='중복 연결 확인',
      specification_id=spec.id,
      quantity=1,
      targets={
        key: {'kind': 'material' if owner == 'qa' else 'component', 'round': 1, 'plan_version': 0, 'status': 'waiting'}
        for key in ('a', 'b')
      },
      created_by=workspace['users']['pm'].id,
    )
    files = [
      File(
        uploader_id=workspace['users'][owner].id,
        bucket='test',
        key=f'original-{index}',
        original_filename=f'원본-{index}.csv',
        content_type='text/csv',
        status=FileStatus.UPLOADED,
      )
      for index in range(2)
    ]
    session.add_all([job, *files])
    session.commit()
    scope = (
      {'specification_id': spec.id}
      if owner == 'rd'
      else {'job_id': job.id, 'target_ids': ['a', 'b'], 'round': 1, 'plan_version': 1 if owner == 'pm' else 0}
    )
  headers = {'Authorization': f'Bearer {create_access_token(workspace["users"][owner].id)}'}
  connected = []
  for file in files:
    response = workspace['client'].post(
      '/api/v1/workspace/documents', json={'file_id': file.id, 'kind': kind, **scope}, headers=headers
    )
    assert response.status_code == 201, response.text
    connected.append(response.json())
  candidates = {'status': 'ready', 'data': {'rows': [{'value': '확인 중인 원문'}]}}
  with workspace['factory']() as session:
    session.get(WorkDocument, connected[0]['id']).candidates = candidates
    session.commit()

  # When the first request is repeated, even with a different target order.
  if owner != 'rd':
    scope['target_ids'] = ['b', 'a']
  response = workspace['client'].post(
    '/api/v1/workspace/documents', json={'file_id': files[0].id, 'kind': kind, **scope}, headers=headers
  )

  # Then the existing document, extracted candidates, and attachment history are preserved.
  assert response.status_code == 201, response.text
  assert response.json()['id'] == connected[0]['id']
  assert response.json()['candidates'] == candidates
  created_at = response.json()['created_at']
  with workspace['factory']() as session:
    assert session.scalar(select(func.count()).select_from(WorkDocument)) == 2
    assert session.scalar(select(func.count()).select_from(WorkflowEvent)) == 2

  if owner != 'rd':
    # Changing the targets updates the connection without replacing its original or extracted evidence.
    for target_ids in (['a'], ['b'], ['a', 'b']):
      scope['target_ids'] = target_ids
      response = workspace['client'].post(
        '/api/v1/workspace/documents', json={'file_id': files[0].id, 'kind': kind, **scope}, headers=headers
      )
      assert response.status_code == 201, response.text
      assert response.json()['id'] == connected[0]['id']
      assert response.json()['scope']['target_ids'] == target_ids
      assert response.json()['candidates'] == candidates
      assert response.json()['blocks'] == connected[0]['blocks']
      assert response.json()['created_at'] == created_at
    with workspace['factory']() as session:
      assert session.scalar(select(func.count()).select_from(WorkDocument)) == 2
      assert session.scalar(select(func.count()).select_from(File)) == 2
      assert session.get(WorkDocument, connected[1]['id']).scope == connected[1]['scope']
      events = list(session.scalars(select(WorkflowEvent).where(WorkflowEvent.action == 'document_scope_updated')))
      assert len(events) == 3
      assert all(event.data['document_id'] == connected[0]['id'] for event in events)
      assert {
        (tuple(event.data['previous_scope']['target_ids']), tuple(event.data['scope']['target_ids']))
        for event in events
      } == {(('a', 'b'), ('a',)), (('a',), ('b',)), (('b',), ('a', 'b'))}

  # A new specification, quality round, or production plan still creates a distinct connection.
  with workspace['factory']() as session:
    if owner == 'rd':
      other = Specification(
        code='CAM-2', name='다른 카메라', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
      )
      session.add(other)
      session.flush()
      scope = {'specification_id': other.id}
    elif owner == 'qa':
      current = session.get(ProductionJob, job.id)
      current.targets = {key: {**target, 'round': 2} for key, target in current.targets.items()}
      scope['round'] = 2
    else:
      session.get(ProductionJob, job.id).plan_version = 1
      scope['plan_version'] = 2
    session.commit()
  response = workspace['client'].post(
    '/api/v1/workspace/documents', json={'file_id': files[0].id, 'kind': kind, **scope}, headers=headers
  )
  assert response.status_code == 201, response.text
  assert response.json()['id'] != connected[0]['id']

  if owner != 'rd':
    previous = response.json()
    with workspace['factory']() as session:
      other = Specification(
        code='CAM-2', name='다른 사양', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
      )
      session.add(other)
      session.flush()
      session.get(ProductionJob, job.id).specification_id = other.id
      session.commit()
    response = workspace['client'].post(
      '/api/v1/workspace/documents', json={'file_id': files[0].id, 'kind': kind, **scope}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()['id'] != previous['id']
    assert response.json()['scope']['specification_id'] == other.id
    with workspace['factory']() as session:
      assert session.get(WorkDocument, previous['id']).scope == previous['scope']


@pytest.mark.parametrize(
  'target_change',
  [{'status': 'passed'}, {'status': 'held', 'inspection_id': 'inspection'}, {'round': 2}, {'plan_version': 1}],
)
def test_reconnecting_cannot_remove_targets_with_fixed_or_previous_evidence(
  workspace: dict, target_change: dict
) -> None:
  # Given an original linked to a target whose evidence has since been fixed or moved to another round/plan.
  with workspace['factory']() as session:
    spec = Specification(
      code='CAM', name='카메라', product_type='digital', graph={}, created_by=workspace['users']['rd'].id
    )
    session.add(spec)
    session.flush()
    job = ProductionJob(
      name='근거 보존 확인',
      specification_id=spec.id,
      quantity=1,
      targets={key: {'kind': 'material', 'round': 1, 'plan_version': 0, 'status': 'waiting'} for key in ('a', 'b')},
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
  headers = {'Authorization': f'Bearer {create_access_token(workspace["users"]["qa"].id)}'}
  body = {'file_id': file.id, 'kind': 'incoming_inspection', 'job_id': job.id, 'target_ids': ['a']}
  response = workspace['client'].post('/api/v1/workspace/documents', json=body, headers=headers)
  assert response.status_code == 201, response.text
  original = response.json()
  with workspace['factory']() as session:
    current = session.get(ProductionJob, job.id)
    current.targets = {**current.targets, 'a': {**current.targets['a'], **target_change}}
    session.commit()

  # When moving the connection to another target, then the fixed scope and history stay intact.
  response = workspace['client'].post(
    '/api/v1/workspace/documents', json={**body, 'target_ids': ['b']}, headers=headers
  )
  assert response.status_code == 409, response.text
  with workspace['factory']() as session:
    assert session.get(WorkDocument, original['id']).scope == original['scope']
    assert session.scalar(select(func.count()).select_from(WorkDocument)) == 1
    assert session.scalar(select(func.count()).select_from(WorkflowEvent)) == 1
