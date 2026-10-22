import io
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

from backend.core.config import get_settings
from backend.core.logger import get_logger
from backend.db.session import get_session
from backend.integrations.storage.s3 import get_storage
from backend.models.file import FileStatus
from backend.parsers.documents import get_parser
from backend.parsers.documents.interface import ParsedDocument
from backend.repositories.files import get_file_by_file_id

logger = get_logger(__file__)


def parse_document(user_id: int, file_id: int) -> ParsedDocument:
  with get_session() as session:
    file = get_file_by_file_id(session, file_id=file_id)
    if file is None or file.uploader_id != user_id:
      raise FileNotFoundError()

    if file.status != FileStatus.UPLOADED:
      raise ValueError('File upload is not completed!')

    try:
      parser = get_parser(Path(file.original_filename).suffix)

      with io.BytesIO() as source:
        storage = get_storage(file.bucket)
        storage.download(file.key, source)
        source.seek(0)

        return parser(source)
    except Exception as exc:
      logger.exception('Failed to parse file: %s', str(exc))
      raise ValueError() from exc
