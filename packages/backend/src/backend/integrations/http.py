import json
from urllib.request import Request, urlopen


def post_json(url: str, body: dict, *, authorization: str | None = None) -> dict:
  headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
  if authorization:
    headers['Authorization'] = authorization

  request = Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
  with urlopen(request, timeout=60) as response:
    return json.load(response)
