"""Inventory a PDF ZIP without extracting files or inferring technical facts."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


def inventory(path: Path, max_total: int = 2000000000, max_entry: int = 100000000) -> dict[str, Any]:
  result = {
    'input_name': path.name,
    'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'files': [],
    'pdf_count': 0,
    'nested_zip_count': 0,
  }
  with zipfile.ZipFile(path) as archive:
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > max_total:
      raise ValueError('ZIP uncompressed size exceeds inventory limit')
    for i in infos:
      normalized = i.filename.replace('\\', '/')
      parts = PurePosixPath(normalized)
      if parts.is_absolute() or '..' in parts.parts or (len(normalized) > 1 and normalized[1] == ':'):
        raise ValueError('Unsafe ZIP member path')
      if i.file_size > max_entry:
        raise ValueError('ZIP member exceeds inventory size limit')
      data = archive.read(i)
      ext = parts.suffix.lower()
      row = {
        'filename': i.filename,
        'size_bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'file_type': ext.lstrip('.'),
      }
      if ext == '.pdf':
        if not data.startswith(b'%PDF-'):
          raise ValueError('PDF extension has no PDF header')
        result['pdf_count'] += 1
        row['source_id'] = f'S{result["pdf_count"]:02d}'
        row['classification'] = None
        row['evidence'] = []
      if ext == '.zip':
        result['nested_zip_count'] += 1
      result['files'].append(row)
  result['note'] = (
    'Inventory only; inspect PDF content separately. Nested ZIPs are counted but not recursively inventoried.'
  )
  return result


if __name__ == '__main__':
  p = argparse.ArgumentParser()
  p.add_argument('zip_path', type=Path)
  p.add_argument('--output', type=Path)
  a = p.parse_args()
  r = inventory(a.zip_path)
  s = json.dumps(r, ensure_ascii=False, indent=2)
  if a.output:
    a.output.write_text(s, encoding='utf-8')
  else:
    print(s)
