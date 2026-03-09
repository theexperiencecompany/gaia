"""Community/public integration routes."""

from typing import Optional

from shared.py.wide_events import log
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
        log.set(operation="list_community_integrations", category=category)
        result = await list_community(sort, category, limit, offset, search)
        log.set(result_count=len(result.integrations) if hasattr(result, "integrations") else 0)
        log.set(outcome="success")
        return result
    except Exception as e:
        log.error(f"Error fetching community integrations: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch community integrations"
        )
