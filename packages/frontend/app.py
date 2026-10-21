import streamlit as st
from core.api.client import call
from views.login import render_login

st.set_page_config(page_title='Ontomatic', page_icon='📚', layout='wide')

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
