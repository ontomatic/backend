from backend.api.v1.admin import router as AdminRouter
from backend.api.v1.auth import router as AuthRouter
from backend.api.v1.chat import router as ChatRouter
from backend.api.v1.upload import router as UploadRouter
from fastapi import APIRouter

router = APIRouter(prefix='/api/v1')

router.include_router(AdminRouter)
router.include_router(AuthRouter)
router.include_router(ChatRouter)
router.include_router(UploadRouter)
