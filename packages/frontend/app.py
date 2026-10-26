import httpx2
import streamlit as st
from core.api.auth import get_current_user
from core.api.client import call
from views.admin_users import render_admin_users
from views.login import render_login
from views.upload import render_upload

st.set_page_config(page_title='Ontomatic', page_icon='📚', layout='wide')


def _set_admin_page(page: str) -> None:
  st.session_state['admin_page'] = page


st.title('Ontomatic')
st.write('Explore and organize your knowledge.')

if st.button('Health check'):
  try:
    result = call('get', '/health-check')
    st.success(f'Backend status: {result["status"]}')
  except Exception as exc:
    st.error(f'Health check failed: {exc}')

if not st.session_state.get('access_token'):
  render_login()
  st.stop()

if st.sidebar.button('로그아웃'):
  st.session_state.clear()
  st.rerun()

try:
  current_user = get_current_user()
except httpx2.HTTPStatusError as exc:
  if exc.response.status_code == 401:
    st.session_state.clear()
    st.info('세션이 만료되었습니다. 다시 로그인해주세요.')
    st.rerun()
  st.error('사용자 정보를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.')
  st.stop()
except httpx2.RequestError:
  st.error('서버에 연결할 수 없습니다. 연결을 확인해주세요.')
  st.stop()

is_admin = current_user.get('role') == 'system_admin'
if is_admin:
  st.session_state.setdefault('admin_page', '문서 업로드')
  st.sidebar.markdown('#### 작업 메뉴')
  st.sidebar.caption('원하는 화면을 선택하세요')
  for label in ('문서 업로드', '사용자 관리'):
    st.sidebar.button(
      label,
      key=f'nav_{label}',
      type='primary' if st.session_state['admin_page'] == label else 'secondary',
      use_container_width=True,
      help=f'{label} 화면 열기',
      on_click=_set_admin_page,
      args=(label,),
    )
  page = st.session_state['admin_page']
  if page == '사용자 관리':
    render_admin_users()
  else:
    render_upload()
else:
  render_upload()
