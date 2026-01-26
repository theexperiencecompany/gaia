"""Integration API routes."""

from fastapi import APIRouter

from app.api.v1.endpoints.integrations.community import router as community_router
from app.api.v1.endpoints.integrations.config import router as config_router
from app.api.v1.endpoints.integrations.custom import router as custom_router
from app.api.v1.endpoints.integrations.marketplace import router as marketplace_router
from app.api.v1.endpoints.integrations.public import router as public_router
from app.api.v1.endpoints.integrations.user import router as user_router

router = APIRouter()

router.include_router(config_router)
router.include_router(marketplace_router, prefix="/marketplace")
router.include_router(community_router, prefix="/community")
router.include_router(public_router)
router.include_router(user_router, prefix="/users/me/integrations")
router.include_router(custom_router, prefix="/custom")
