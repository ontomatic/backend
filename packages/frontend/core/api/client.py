from typing import Literal

import httpx2
import streamlit as st


@st.cache_resource
def get_client() -> httpx2.Client:
  return httpx2.Client(base_url='http://localhost:8000')


Method = Literal['get', 'post', 'put', 'patch', 'delete']


def call(method: Method, path: str, *, body: dict | None = None, headers: dict | None = None):
  response = get_client().request(method, path, json=body, headers=headers)
  response.raise_for_status()
  return response.json()
