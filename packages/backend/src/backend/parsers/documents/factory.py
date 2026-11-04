from backend.core.config import get_settings
from backend.parsers.documents.csv import parse_csv
from backend.parsers.documents.docx import parse_docx
from backend.parsers.documents.interface import DocumentParser
from backend.parsers.documents.pdf import parse_pdf
from backend.parsers.documents.upstage import UpstageParser
from backend.parsers.documents.xlsx import parse_xlsx

LOCAL_PARSERS: dict[str, DocumentParser] = {
  'pdf': parse_pdf,
  'docx': parse_docx,
  'xlsx': parse_xlsx,
  'csv': parse_csv,
}


def create_parser(file_format: str) -> DocumentParser:
  ext = file_format.lower().lstrip('.')
  try:
    local_parser = LOCAL_PARSERS[ext]
  except KeyError:
    raise ValueError(f'Unsupported file format: {file_format}') from None

  settings = get_settings()
  if settings.parser_provider == 'local':
    return local_parser
  if settings.parser_provider == 'upstage':
    if ext == 'csv':
      return local_parser
    if not settings.upstage_api_key:
      raise ValueError('Upstage API key is required.')
    return UpstageParser(ext, settings.upstage_api_key.get_secret_value(), settings.upstage_base_url)
  raise ValueError(f'Unsupported parser provider: {settings.parser_provider}')
