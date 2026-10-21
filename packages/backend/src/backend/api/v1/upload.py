from backend.api.guard import CurrentUserId
from backend.schemas.upload import UploadFileOut, UploadFilesIn
from backend.services.upload import get_upload_urls
from fastapi import APIRouter

router = APIRouter(prefix='/upload', tags=['upload'])


@router.post('', response_model=list[UploadFileOut])
def issue_upload_urls(user_id: CurrentUserId, body: UploadFilesIn) -> list[UploadFileOut]:
  return get_upload_urls(user_id, body.files)
