"""The Updates feed: what GAIA told the user and what it only recorded."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.models.updates_models import UnseenUpdates, UpdateFilter, UpdatesResponse
from app.services.outbox.updates import count_unseen_updates, read_updates
from shared.py.wide_events import log

router = APIRouter(prefix="/updates")

_PAGE_SIZE_MAX = 100


@router.get("")
async def get_updates(
    user_id: Annotated[str, Depends(get_user_id)],
    update_filter: Annotated[UpdateFilter, Query(alias="filter")] = UpdateFilter.ALL,
    before: Annotated[
        datetime | None, Query(description="Read the page after this cursor.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=_PAGE_SIZE_MAX)] = 30,
) -> UpdatesResponse:
    """Return a page of the user's updates, newest first."""
    log.set(user={"id": user_id}, operation="read_updates")
    return await read_updates(user_id, update_filter, before=before, limit=limit)


@router.get("/unseen")
async def get_unseen_updates(
    user_id: Annotated[str, Depends(get_user_id)],
    since: Annotated[datetime, Query(description="When the user last opened the feed.")],
) -> UnseenUpdates:
    """Return how many updates GAIA told the user since they last opened the feed."""
    log.set(user={"id": user_id}, operation="count_unseen_updates")
    return await count_unseen_updates(user_id, since)
