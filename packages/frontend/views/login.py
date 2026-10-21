import httpx2
import streamlit as st
from core.api.auth import login


def render_login() -> None:
  with st.form('login', clear_on_submit=True):
    emp_id = st.text_input('사번')
    password = st.text_input('비밀번호', type='password')
    submitted = st.form_submit_button('로그인')

  if not submitted:
    return

  if not emp_id.strip() or not password:
    st.warning('사번과 비밀번호를 입력해주세요.')
    return

  try:
    access_token = login(emp_id.strip(), password)
  except httpx2.HTTPStatusError as exc:
    if exc.response.status_code == 401:
      st.error('사번 또는 비밀번호가 올바르지 않습니다.')
    else:
      st.error('로그인 처리 중 오류가 발생했습니다.')
  except httpx2.RequestError:
    st.error('서버에 연결할 수 없습니다.')
    return

  st.session_state['access_token'] = access_token
  st.rerun()
