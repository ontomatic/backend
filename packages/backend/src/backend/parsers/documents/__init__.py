from backend.parsers.documents.csv import parse_csv
from backend.parsers.documents.docx import parse_docx
from backend.parsers.documents.interface import DocumentParser
from backend.parsers.documents.pdf import parse_pdf
from backend.parsers.documents.xlsx import parse_xlsx

PARSERS: dict[str, DocumentParser] = {
  'pdf': parse_pdf,
  'docx': parse_docx,
  'xlsx': parse_xlsx,
  'csv': parse_csv,
}


def get_parser(file_format: str) -> DocumentParser:
  try:
    print(file_format)
    ext = file_format.lower().lstrip('.')
    return PARSERS[ext]
  except KeyError:
    raise ValueError(f'Unsupported file format: {file_format}') from None
