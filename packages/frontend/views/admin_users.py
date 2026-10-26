import httpx2
import streamlit as st
from core.api.admin import create_user, get_departments, get_users, update_user


def _show_error(exc: Exception, action: str) -> None:
  if isinstance(exc, httpx2.HTTPStatusError):
    status = exc.response.status_code
    messages = {
      401: '로그인이 만료되었습니다. 다시 로그인해주세요.',
      403: '사용자 관리 권한이 없습니다.',
      404: '대상을 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 선택해주세요.',
      409: '이미 사용 중인 사번입니다. 다른 사번을 입력해주세요.',
      422: '입력값을 확인해주세요. 이름·부서·비밀번호 조건을 확인하세요.',
    }
    st.error(messages.get(status, f'{action} 중 오류가 발생했습니다. (HTTP {status})'))
  elif isinstance(exc, httpx2.RequestError):
    st.error(f'{action} 중 서버에 연결할 수 없습니다. 연결을 확인해주세요.')
  else:
    st.error(f'{action} 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.')


def render_admin_users() -> None:
  st.header('사용자 관리')
  confirmation = st.session_state.pop('admin_user_confirmation', None)
  if confirmation:
    st.success(confirmation)
  try:
    departments = get_departments()
  except (httpx2.HTTPError, ValueError) as exc:
    _show_error(exc, '부서 목록 조회')
    return

  if not departments:
    st.warning('활성 부서가 없습니다. 사용자를 생성하거나 수정하려면 먼저 활성 부서를 등록해야 합니다.')

  department_names = {item['id']: item['name'] for item in departments}
  with st.expander('사용자 검색 및 필터', expanded=True):
    with st.form('user_filters'):
      query = st.text_input('사번 또는 이름 검색', max_chars=100)
      department_values = [None, *department_names]
      selected_department = st.selectbox(
        '부서', department_values, format_func=lambda value: '전체 부서' if value is None else department_names[value]
      )
      active_filter = st.selectbox('상태', ['전체', '활성', '비활성'])
      submitted = st.form_submit_button('검색')
    if submitted:
      st.session_state['admin_user_query'] = query.strip()
      st.session_state['admin_user_department'] = selected_department
      st.session_state['admin_user_active'] = {'전체': None, '활성': True, '비활성': False}[active_filter]
      st.session_state['admin_user_page'] = 1

  query = st.session_state.get('admin_user_query', '')
  department_id = st.session_state.get('admin_user_department')
  is_active = st.session_state.get('admin_user_active')
  page = st.session_state.get('admin_user_page', 1)
  try:
    result = get_users(q=query or None, department_id=department_id, is_active=is_active, page=page)
  except (httpx2.HTTPError, ValueError) as exc:
    _show_error(exc, '사용자 목록 조회')
    return

  items = result.get('items', [])
  total = result.get('total', 0)
  page_size = result.get('page_size', 20)
  page_count = max(1, (total + page_size - 1) // page_size)
  st.caption(f'총 {total}명 · {page}/{page_count}페이지')
  if items:
    st.dataframe(
      [
        {
          '사번': user['emp_id'],
          '이름': user['name'],
          '부서': (user.get('department') or {}).get('name', '미배정'),
          '상태': '활성' if user['is_active'] else '비활성',
        }
        for user in items
      ],
      hide_index=True,
      width='stretch',
    )
  else:
    st.info('조건에 맞는 사용자가 없습니다.')

  previous, next_page = st.columns(2)
  with previous:
    if st.button('← 이전', disabled=page <= 1, key='users_previous'):
      st.session_state['admin_user_page'] = page - 1
      st.rerun()
  with next_page:
    if st.button('다음 →', disabled=page >= page_count, key='users_next'):
      st.session_state['admin_user_page'] = page + 1
      st.rerun()

  st.divider()
  st.subheader('사용자 추가')
  if departments:
    with st.form('create_user', clear_on_submit=True):
      emp_id = st.text_input('사번', max_chars=30)
      name = st.text_input('이름', max_chars=100)
      new_department = st.selectbox('부서', list(department_names), format_func=department_names.get)
      password = st.text_input('초기 비밀번호 (12~30자)', type='password', max_chars=30)
      create_submitted = st.form_submit_button('사용자 생성')
    if create_submitted:
      if not emp_id.strip() or not name.strip() or not 12 <= len(password) <= 30:
        st.warning('사번과 이름을 입력하고, 비밀번호는 12~30자로 설정해주세요.')
      else:
        try:
          create_user(emp_id.strip(), name.strip(), new_department, password)
          st.session_state['admin_user_confirmation'] = '사용자를 생성했습니다.'
          st.rerun()
        except (httpx2.HTTPError, ValueError) as exc:
          _show_error(exc, '사용자 생성')

  st.divider()
  st.subheader('사용자 정보 수정')
  if items and departments:
    choices = {user['id']: user for user in items}
    chosen_id = st.selectbox(
      '수정할 사용자 선택',
      list(choices),
      format_func=lambda user_id: f'{choices[user_id]["name"]} · {choices[user_id]["emp_id"]}',
      key='admin_edit_target',
    )
    chosen = choices[chosen_id]
    st.info(f'수정 대상: {chosen["name"]} · 사번 {chosen["emp_id"]}')
    department_id = (chosen.get('department') or {}).get('id')
    defaults = list(department_names)
    department_missing = department_id not in department_names
    if department_missing:
      st.warning('현재 부서는 활성 부서 목록에 없습니다. 저장하려면 새 부서를 직접 선택해주세요.')
    department_options = ([None] if department_missing else []) + defaults
    default_index = 0 if department_missing else department_options.index(department_id)
    target_key = f'admin_edit_{chosen_id}'
    with st.form(f'update_user_{chosen_id}'):
      updated_name = st.text_input('이름', value=chosen['name'], max_chars=100, key=f'{target_key}_name')
      updated_department = st.selectbox(
        '부서',
        department_options,
        index=default_index,
        format_func=lambda value: '현재 부서 선택 필요' if value is None else department_names[value],
        key=f'{target_key}_department',
      )
      confirmed = st.checkbox(
        f'{chosen["name"]} (사번 {chosen["emp_id"]})의 정보 수정임을 확인했습니다.',
        key=f'{target_key}_confirmed',
      )
      update_submitted = st.form_submit_button('변경 사항 저장')
    if update_submitted:
      if not confirmed:
        st.warning('수정 대상 사용자를 확인한 뒤 체크해주세요.')
      elif not updated_name.strip():
        st.warning('이름을 입력해주세요.')
      elif updated_department is None:
        st.warning('저장할 부서를 명시적으로 선택해주세요.')
      else:
        try:
          update_user(chosen_id, updated_name.strip(), updated_department)
          st.session_state['admin_user_confirmation'] = (
            f'{chosen["name"]} (사번 {chosen["emp_id"]}) 사용자를 수정했습니다.'
          )
          st.rerun()
        except (httpx2.HTTPError, ValueError) as exc:
          _show_error(exc, '사용자 수정')
