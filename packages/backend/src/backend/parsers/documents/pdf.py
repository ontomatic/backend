from io import BytesIO

from backend.parsers.documents.interface import ParsedDocument


def parse_pdf(source: BytesIO) -> ParsedDocument:
  import pdfplumber

  with pdfplumber.open(source) as pdf:
    print(pdf.stream)

    raise NotImplementedError()
