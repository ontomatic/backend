from typing import Literal

import httpx2
import streamlit as st
from core.config import API_URL


@st.cache_resource
def get_client() -> httpx2.Client:
  return httpx2.Client(base_url=API_URL)


Method = Literal['get', 'post', 'put', 'patch', 'delete']


def call(
  method: Method,
  path: str,
  *,
  body: dict | None = None,
  headers: dict | None = None,
  params: dict | None = None,
):
  headers = headers or {}

  access_token = st.session_state.get('access_token')
  if access_token:
    headers['Authorization'] = f'Bearer {access_token}'

  response = get_client().request(method, path, json=body, headers=headers, params=params)
  if response.status_code == 401:
    st.session_state.pop('access_token', None)

  response.raise_for_status()

  if response.status_code == 204:
    return None

  return response.json()
