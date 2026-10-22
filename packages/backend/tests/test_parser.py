from io import BytesIO

import pytest
from backend.parsers.documents.csv import parse_csv


@pytest.mark.parametrize(
  ('content', 'expected'),
  [
    pytest.param('name,age\nKim,20', 'name, age\nKim, 20', id='basic'),
    pytest.param('이름,나이\n김철수,20', '이름, 나이\n김철수, 20', id='korean'),
    pytest.param('', '', id='empty-file'),
    pytest.param('name,age', 'name, age', id='header-only'),
    pytest.param('a,,c', 'a, , c', id='empty-cell'),
    pytest.param('name,note\nKim,"hello, world"', 'name, note\nKim, hello, world', id='quoted-comma'),
    pytest.param('name,note\nKim,"say ""hello"""', 'name, note\nKim, say "hello"', id='escaped-quote'),
    pytest.param('name,note\nKim,"line1\nline2"', 'name, note\nKim, line1\nline2', id='multiline-cell'),
    pytest.param('name,age\r\nKim,20\r\n', 'name, age\nKim, 20', id='windows-newlines'),
  ],
)
def test_parse_csv(content: str, expected: str):
  with BytesIO(content.encode('utf-8')) as source:
    result = parse_csv(source)
    assert result.text == expected


def test_parse_csv_rejects_invalid_utf8():
  with BytesIO(b'\xff,name\n1,Kim') as source, pytest.raises(UnicodeDecodeError):
    parse_csv(source)


# def test_parse_csv_keeps_source_open():
#   with BytesIO(b'name,age\nKim,20') as source:
#     parse_csv(source)
#     assert not source.closed
