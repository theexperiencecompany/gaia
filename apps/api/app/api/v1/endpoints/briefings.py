"""Briefing read endpoints — the dashboard renders these payloads.

Shapes are fixed (the frontend is coded against them): ``/briefings/latest``
returns the newest daily briefing (marking it opened), ``/briefings`` returns the
archive. All rendering is client-side; these only serve stored payloads.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.briefing import BRIEFING_KIND_DAILY
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingListResponse,
    BriefingModel,
    ChannelPriorityResponse,
    ChannelPriorityUpdate,
)
from app.services.briefing import delivery_channels
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

    latest = await briefing_repository.get_latest(user_id, kind=BRIEFING_KIND_DAILY)
    if latest is None:
        return None

    if latest.opened_at is None:
        opened = await briefing_repository.mark_opened(user_id, latest.id)
        if opened is not None:
            track(
                user_id, "briefing_opened", {"briefing_id": latest.id, "kind": BRIEFING_KIND_DAILY}
            )
            latest = opened

    return latest


@router.get("/preferences")
async def get_briefing_preferences(
    user: Annotated[dict, Depends(get_current_user)],
) -> ChannelPriorityResponse:
    """The user's ordered chat-channel priority for briefing delivery."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, briefing={"operation": "get_preferences"})
    priority = await delivery_channels.get_channel_priority(user_id)
    return ChannelPriorityResponse(chat_channel_priority=priority)


@router.patch("/preferences")
async def update_briefing_preferences(
    payload: ChannelPriorityUpdate,
    user: Annotated[dict, Depends(get_current_user)],
) -> ChannelPriorityResponse:
    """Persist the user's chat-channel priority; the brief lands on the first
    linked and enabled platform in this order."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, briefing={"operation": "update_preferences"})
    await delivery_channels.set_channel_priority(user_id, payload.chat_channel_priority)
    log.set(briefing={"channel_priority": payload.chat_channel_priority})
    return ChannelPriorityResponse(chat_channel_priority=payload.chat_channel_priority)


@router.get("")
async def list_briefings(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=30, ge=1, le=100),
) -> BriefingListResponse:
    """Archive of the user's briefings (daily + weekly), newest first."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, briefing={"operation": "list", "limit": limit})
    briefings = await briefing_repository.list_recent(user_id, limit=limit)
    return BriefingListResponse(briefings=briefings)
