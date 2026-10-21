from backend.api.guard import CurrentUserId
from backend.schemas.upload import UploadFilesIn, UploadFilesOut
from backend.services.upload import get_upload_urls
from fastapi import APIRouter

router = APIRouter(prefix='/upload', tags=['upload'])


@router.post('', response_model=UploadFilesOut)
def issue_upload_urls(user_id: CurrentUserId, body: UploadFilesIn) -> UploadFilesOut:
  urls = get_upload_urls(user_id, body.files)
  return UploadFilesOut(urls=urls)
