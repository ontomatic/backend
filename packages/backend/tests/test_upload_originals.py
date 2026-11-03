import pytest
from backend.integrations.storage.interface import ObjectInfo
from backend.models import File
from backend.models.file import FileStatus
from backend.services.upload import complete_file_upload
from sqlalchemy.orm import Session


def test_completed_original_cannot_be_replaced_with_the_old_upload_url(
  workspace: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
  # Given a completed upload, when the old staging key is overwritten, then the fixed original stays unchanged.
  objects = {'uploads/staging': b'original'}

  class Storage:
    def get_object_info(self, key: str) -> ObjectInfo:
      return ObjectInfo(size=len(objects[key]), content_type='text/csv', etag='original-etag')

    def copy(self, source_key: str, destination_key: str, *, source_etag: str | None = None) -> None:
      assert source_etag == 'original-etag'
      objects[destination_key] = objects[source_key]

    def delete(self, key: str) -> None:
      del objects[key]

  monkeypatch.setattr('backend.services.upload.get_storage', lambda bucket: Storage())
  with workspace['factory']() as session:
    file = File(
      uploader_id=workspace['users']['rd'].id,
      bucket='test',
      key='uploads/staging',
      original_filename='detail.csv',
      content_type='text/csv',
    )
    session.add(file)
    session.commit()
    file_id = file.id
  complete_file_upload(workspace['users']['rd'].id, file_id)
  objects['uploads/staging'] = b'replaced after completion'
  complete_file_upload(workspace['users']['rd'].id, file_id)
  with workspace['factory']() as session:
    original = session.get(File, file_id)
    assert original.status == FileStatus.UPLOADED
    assert original.key.startswith('originals/')
    assert objects[original.key] == b'original'


def test_failed_copy_keeps_the_upload_pending_and_staging_intact(
  workspace: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
  class Storage:
    def get_object_info(self, key: str) -> ObjectInfo:
      return ObjectInfo(size=8, content_type='text/csv', etag='original-etag')

    def copy(self, *args: object, **kwargs: object) -> None:
      raise RuntimeError('Source changed during completion')

  monkeypatch.setattr('backend.services.upload.get_storage', lambda bucket: Storage())
  with workspace['factory']() as session:
    file = File(
      uploader_id=workspace['users']['rd'].id,
      bucket='test',
      key='uploads/pending',
      original_filename='detail.csv',
      content_type='text/csv',
    )
    session.add(file)
    session.commit()
    file_id = file.id
  with pytest.raises(RuntimeError):
    complete_file_upload(workspace['users']['rd'].id, file_id)
  with workspace['factory']() as session:
    file = session.get(File, file_id)
    assert file.status == FileStatus.PENDING
    assert file.key == 'uploads/pending'
