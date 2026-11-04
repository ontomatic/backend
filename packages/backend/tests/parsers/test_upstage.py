import json
from email import policy
from email.parser import BytesParser
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from backend.core.config import Settings
from backend.models import File
from backend.models.file import FileStatus
from backend.models.workflow import WorkDocument
from backend.parsers.documents import factory, upstage
from backend.parsers.documents.interface import SourceLocation, TableBlock, TextBlock
from backend.services import document as document_service
from backend.services import work_documents
from pydantic import SecretStr, ValidationError


def mock_response(monkeypatch: pytest.MonkeyPatch, payload: object) -> list:
  requests = []

  def urlopen(request: object, *, timeout: int) -> BytesIO:
    requests.append((request, timeout))
    return BytesIO(json.dumps(payload).encode())

  monkeypatch.setattr(upstage, 'urlopen', urlopen)
  return requests


@pytest.mark.parametrize('file_format', ['pdf', 'docx', 'xlsx'])
@pytest.mark.parametrize('base_url', ['https://upstage.test/v1', 'https://upstage.test/v1/'])
def test_upstage_upload_preserves_binary_and_converts_blocks(
  api_settings: Settings, monkeypatch: pytest.MonkeyPatch, file_format: str, base_url: str
) -> None:
  # Given text, a merged HTML table and a figure in an Upstage response.
  settings = api_settings.model_copy(
    update={'parser_provider': 'upstage', 'upstage_api_key': SecretStr('test-key'), 'upstage_base_url': base_url}
  )
  monkeypatch.setattr(factory, 'get_settings', lambda: settings)
  requests = mock_response(
    monkeypatch,
    {
      'elements': [
        {'category': 'heading1', 'page': 2, 'content': {'text': '사양서', 'html': '<h1>사양서</h1>'}},
        {
          'category': 'table',
          'page': 2,
          'content': {
            'text': 'table text',
            'html': '<table><tr><th rowspan="2">부품</th><th colspan="2">속성</th></tr>'
            '<tr><td>이름</td><td>값</td></tr><tr><td>렌즈</td><td>재질</td>'
            '<td><p>A &amp; B</p><p>유리<br>코팅</p></td></tr></table>',
          },
        },
        {'category': 'figure', 'page': 2, 'content': {'text': '', 'html': '<figure></figure>'}},
      ]
    },
  )
  binary = b'\x00\xff\r\nbinary\ncontent'
  stream = BytesIO(binary)

  # When parsing a binary stream with the remote adapter.
  result = factory.create_parser(file_format)(stream)

  # Then existing block types, ordering and source locations are preserved.
  assert result.format == file_format
  assert result.blocks == [
    TextBlock(text='사양서', location=SourceLocation(page_number=2, block_index=1)),
    TableBlock(
      rows=[['부품', '속성', '속성'], ['부품', '이름', '값'], ['렌즈', '재질', 'A & B\n유리\n코팅']],
      location=SourceLocation(page_number=2, block_index=2),
    ),
  ]
  assert not stream.closed
  request, timeout = requests[0]
  assert request.full_url == 'https://upstage.test/v1/document-digitization'
  assert request.get_method() == 'POST'
  assert request.get_header('Authorization') == 'Bearer test-key'
  assert timeout > 0
  mime = b'Content-Type: ' + request.get_header('Content-type').encode() + b'\r\n\r\n' + request.data
  parts = {
    part.get_param('name', header='content-disposition'): part
    for part in BytesParser(policy=policy.default).parsebytes(mime).iter_parts()
  }
  assert parts['document'].get_filename() == f'document.{file_format}'
  assert parts['document'].get_payload(decode=True) == binary
  assert parts['model'].get_payload(decode=True) == b'document-parse'
  assert json.loads(parts['output_formats'].get_payload(decode=True)) == ['text', 'html']


@pytest.mark.parametrize(
  'error', [HTTPError('https://api.upstage.ai', 401, 'Unauthorized', {}, None), URLError('timeout')]
)
def test_upstage_propagates_request_errors(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
  # Given an unsuccessful remote request, when parsing, then the failure is propagated to the caller.
  def fail(*args: object, **kwargs: object) -> None:
    raise error

  monkeypatch.setattr(upstage, 'urlopen', fail)
  with pytest.raises(type(error)):
    upstage.UpstageParser('pdf', 'test-key', 'https://upstage.test/v1')(BytesIO(b'pdf'))


@pytest.mark.parametrize('payload', [{}, {'elements': None}, {'elements': [{'category': 'paragraph'}]}])
def test_upstage_rejects_invalid_response(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
  # Given a malformed response, when parsing, then it cannot become a successful empty document.
  mock_response(monkeypatch, payload)
  with pytest.raises(ValidationError):
    upstage.UpstageParser('pdf', 'test-key', 'https://upstage.test/v1')(BytesIO(b'pdf'))


@pytest.mark.parametrize('html', ['', '<table></table>', '<table><tr><td colspan="0">a</td></tr></table>'])
def test_upstage_rejects_invalid_table(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
  # Given missing or invalid table HTML, when parsing, then structured content cannot silently disappear.
  mock_response(monkeypatch, {'elements': [{'category': 'table', 'page': 1, 'content': {'text': '', 'html': html}}]})
  with pytest.raises(ValueError):
    upstage.UpstageParser('pdf', 'test-key', 'https://upstage.test/v1')(BytesIO(b'pdf'))


def test_upstage_pads_missing_cells_and_handles_empty_cells(monkeypatch: pytest.MonkeyPatch) -> None:
  # Given a ragged table, when normalizing it, then empty and missing cells retain their column positions.
  mock_response(
    monkeypatch,
    {
      'elements': [
        {
          'category': 'table',
          'page': 1,
          'content': {'text': '', 'html': '<table><tr><td></td><td>b</td></tr><tr><td>c</td></tr></table>'},
        }
      ]
    },
  )
  assert upstage.UpstageParser('pdf', 'test-key', 'https://upstage.test/v1')(BytesIO(b'pdf')).blocks[0].rows == [
    ['', 'b'],
    ['c', None],
  ]


@pytest.mark.parametrize('service', ['document', 'work_document'])
@pytest.mark.parametrize('valid_response', [True, False])
def test_document_services_use_selected_provider_and_keep_error_handling(
  workspace: dict, api_settings: Settings, monkeypatch: pytest.MonkeyPatch, service: str, valid_response: bool
) -> None:
  # Given an uploaded PDF with Upstage selected and a successful or malformed remote response.
  monkeypatch.setattr(api_settings, 'parser_provider', 'upstage')
  monkeypatch.setattr(api_settings, 'upstage_api_key', SecretStr('test-key'))
  payload = {'elements': [{'category': 'paragraph', 'page': 1, 'content': {'text': '원문', 'html': '<p>원문</p>'}}]}
  requests = mock_response(monkeypatch, payload if valid_response else {})
  monkeypatch.setattr(document_service, 'get_session', workspace['factory'])
  monkeypatch.setattr(document_service, 'get_storage', work_documents.get_storage)
  user = workspace['users']['rd']
  with workspace['factory']() as session:
    file = File(
      uploader_id=user.id,
      bucket='test',
      key='original.pdf',
      original_filename='원본.pdf',
      content_type='application/pdf',
      status=FileStatus.UPLOADED,
    )
    session.add(file)
    session.commit()

    # When either document service parses the original.
    if service == 'document':
      if valid_response:
        assert document_service.parse_document(user.id, file.id).blocks[0].text == '원문'
      else:
        with pytest.raises(ValueError):
          document_service.parse_document(user.id, file.id)
    else:
      document = WorkDocument(file_id=file.id)
      work_documents.parse_work_document(session, document)

      # Then the workflow stores converted blocks on success and records failures as errors.
      assert document.status == ('parsed' if valid_response else 'error')
      if valid_response:
        assert document.blocks[0]['text'] == '원문'
        assert document.blocks[0]['location']['page_number'] == 1
        assert document.error is None
      else:
        assert document.error
  assert len(requests) == 1
