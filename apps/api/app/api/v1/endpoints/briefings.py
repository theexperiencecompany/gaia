"""Briefing read endpoints: the archive, the Postmarks stamp collection, and one brief."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import BriefingListResponse, BriefingView, PostmarksResponse
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.briefing.postmarks import collected_postmarks
from app.services.briefing.view import briefing_view
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingOpened, BriefingPostmarksViewed
from shared.py.wide_events import log

router = APIRouter(prefix="/briefings", tags=["Briefings"])


@router.get("")
async def list_briefings(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    limit: int = Query(default=30, ge=1, le=100),
) -> BriefingListResponse:
    """Archive of the user's briefings (daily + weekly), newest first."""
    user_id = user.user_id
    log.set(user={"id": user_id}, briefing={"operation": "list", "limit": limit})
    briefings = await briefing_repository.list_recent(user_id, limit=limit)
    return BriefingListResponse(briefings=[briefing_view(b) for b in briefings])


@router.get("/postmarks")
async def get_postmarks(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PostmarksResponse:
    """The Air Mail city stamps the user has collected, each linked to its brief."""
    user_id = user.user_id
    log.set(user={"id": user_id}, briefing={"operation": "postmarks"})
    postmarks = await collected_postmarks(user_id)
    collected = len(postmarks.postmarks)
    log.set_ns("briefing", postmarks_collected=collected)
    capture(UserId(user_id), BriefingPostmarksViewed(collected=collected, total=postmarks.total))
    return postmarks


@router.get("/{briefing_id}")
async def get_briefing(
    briefing_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BriefingView:
    """Return one of the user's briefs; the first open marks it and emits briefing:opened."""
    user_id = user.user_id
    log.set(user={"id": user_id}, briefing={"operation": "get", "id": briefing_id})
    briefing = await briefing_repository.get(briefing_id, user_id=user_id)
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    if briefing.opened_at is None:
        opened = await briefing_repository.mark_opened(user_id, briefing.id)
        if opened is not None:
            capture(UserId(user_id), BriefingOpened(kind=briefing.kind))
            briefing = opened
    return briefing_view(briefing)
