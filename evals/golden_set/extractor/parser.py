from io import BytesIO
from pathlib import Path

from backend.parsers.documents.docx import parse_docx as parse_backend_docx
from backend.parsers.documents.interface import TableBlock, TextBlock


def parse_docx(file: Path) -> list[dict]:
  """Adapt the backend's local DOCX parser to the golden extractor's block format."""
  with BytesIO(file.read_bytes()) as source:
    parsed = parse_backend_docx(source)
  blocks = []
  for block in parsed.blocks:
    if isinstance(block, TextBlock):
      text = block.text.strip()
      if block.heading_level is not None:
        blocks.append({'t': 'h', 'level': block.heading_level, 'text': text})
      else:
        blocks.append({'t': 'p', 'text': text})
    elif isinstance(block, TableBlock):
      rows = [[(value or '').strip() for value in row] for row in block.rows]
      blocks.append({'t': 'table', 'rows': rows})
  return blocks
