"""Community/public integration routes."""

from typing import Optional

from app.config.loggers import auth_logger as logger
from app.schemas.integrations.responses import CommunityListResponse
from app.services.integrations.community_service import (
    list_community_integrations as list_community,
)
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("", response_model=CommunityListResponse)
async def list_community_integrations(
    sort: str = "popular",
    category: str = "all",
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
) -> CommunityListResponse:
    try:
        return await list_community(sort, category, limit, offset, search)
    except Exception as e:
        logger.error(f"Error fetching community integrations: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch community integrations"
        )
