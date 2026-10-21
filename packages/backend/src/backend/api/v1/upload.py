from backend.api.guard import CurrentUserId
from backend.schemas.upload import UploadFileOut, UploadFilesIn
from backend.services.upload import complete_file_upload, get_upload_urls
from fastapi import APIRouter

router = APIRouter(prefix='/uploads', tags=['upload'])


@router.post('', response_model=list[UploadFileOut])
def issue_upload_urls(user_id: CurrentUserId, body: UploadFilesIn) -> list[UploadFileOut]:
  return get_upload_urls(user_id, body.files)


@router.post('/{file_id}/complete', status_code=204)
def complete_upload(user_id: CurrentUserId, file_id: int) -> None:
  complete_file_upload(user_id, file_id)
