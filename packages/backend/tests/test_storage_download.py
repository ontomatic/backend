def test_originals_download_as_attachments_with_encoded_filenames(api_settings: object) -> None:
  from backend.integrations.storage.s3 import S3Storage

  calls = []

  class Client:
    def generate_presigned_url(self, operation: str, **options: object) -> str:
      calls.append((operation, options))
      return 'https://storage.example/download'

  storage = object.__new__(S3Storage)
  storage._bucket = 'private'
  storage._client = Client()
  storage.get_download_url('original-key', filename='한글"\n.docx')
  operation, options = calls[0]
  assert operation == 'get_object'
  assert options['Params']['ResponseContentType'] == 'application/octet-stream'
  disposition = options['Params']['ResponseContentDisposition']
  assert disposition.startswith('attachment; filename*=UTF-8')
  assert '\n' not in disposition and '%0A' in disposition
