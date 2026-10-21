import httpx2
import streamlit as st
from core.api.upload import complete_upload, get_presigned_urls, upload_file


def render_upload() -> None:
  files = st.file_uploader('문서 선택', type=['pdf', 'docx', 'xlsx'], accept_multiple_files=True)

  if st.button('업로드', disabled=not files):
    results, progress = [], st.progress(0.0)
    tickets = get_presigned_urls(files)
    for idx, (file, ticket) in enumerate(zip(files, tickets, strict=True)):
      progress.progress(idx / len(files), text=f'{idx}/{len(files)}개 처리')

      try:
        upload_file(ticket['upload_url'], file)
      except httpx2.HTTPError:
        results.append(
          {'filename': file.name, 'file_id': ticket['file_id'], 'status': False, 'message': 'Failed to upload'}
        )
        continue

      try:
        complete_upload(ticket['file_id'])
      except httpx2.HTTPError:
        results.append(
          {'filename': file.name, 'file_id': ticket['file_id'], 'status': False, 'message': 'Failed to Complete'}
        )
        continue
      results.append({'filename': file.name, 'file_id': ticket['file_id'], 'status': True})
    st.session_state['upload_results'] = results
    progress.progress(1.0, '처리 완료')

  results = st.session_state.get('upload_results')
  if results:
    success_count = sum(row['status'] for row in results)
    st.write(f'총 {len(results)}개 중 {success_count}개 완료')
    st.dataframe(results, hide_index=True, width='stretch')
