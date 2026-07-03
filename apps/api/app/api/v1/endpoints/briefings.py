"""Briefing read endpoints — the dashboard renders these payloads.

Shapes are fixed (the frontend is coded against them): ``/briefings/latest``
returns the newest daily briefing (marking it opened), ``/briefings`` returns the
archive. All rendering is client-side; these only serve stored payloads.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.briefing import BRIEFING_KIND_DAILY
from app.models.briefing_models import BriefingListResponse, BriefingModel
from app.services.briefing import repository
from app.utils.analytics import track
from shared.py.wide_events import log

router = APIRouter(prefix="/briefings", tags=["Briefings"])


@router.get("/latest")
async def get_latest_briefing(
    user: Annotated[dict, Depends(get_current_user)],
) -> BriefingModel | None:
    """Latest daily briefing; marks it opened (once) and emits ``briefing_opened``."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, briefing={"operation": "latest"})

    latest = await repository.get_latest_briefing(user_id, BRIEFING_KIND_DAILY)
    if latest is None:
        return None

    if latest.opened_at is None:
        opened = await repository.mark_opened(user_id, latest.id)
        if opened is not None:
            track(
                user_id, "briefing_opened", {"briefing_id": latest.id, "kind": BRIEFING_KIND_DAILY}
            )
            latest = opened

    return latest


@router.get("")
async def list_briefings(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=30, ge=1, le=100),
) -> BriefingListResponse:
    """Archive of the user's briefings (daily + weekly), newest first."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, briefing={"operation": "list", "limit": limit})
    briefings = await repository.list_briefings(user_id, limit)
    return BriefingListResponse(briefings=briefings)
