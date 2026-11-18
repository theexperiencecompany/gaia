"""Briefing endpoints: the archive, the Postmarks stamp collection, one brief, and the brief settings."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.briefing import (
    EDITION_IMAGE_MAX_AGE_SECONDS,
    STAMP_ART_CONTENT_TYPE,
    STAMP_ART_MAX_AGE_SECONDS,
    EditionVariant,
)
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.models.brief_settings_models import (
    BriefDeliveryWorkflowsConflict,
    BriefingEditions,
    BriefingEditionsUpdate,
    BriefingScheduleState,
    BriefingScheduleUpdate,
)
from app.models.brief_view_models import BriefingListResponse, BriefingView, PostmarksResponse
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.briefing.edition_choices import briefing_editions, set_edition_choices
from app.services.briefing.edition_image import EDITION_CONTENT_TYPES, signed_edition
from app.services.briefing.editions.stamps import stamp_art
from app.services.briefing.postmarks import collected_postmarks
from app.services.briefing.schedule import briefing_schedule_state, set_briefing_schedule
from app.services.briefing.view import briefing_card, briefing_view
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingOpened, BriefingPostmarksViewed
from shared.py.wide_events import log

router = APIRouter(prefix="/briefings", tags=["Briefings"])


@router.get("")
async def list_briefings(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: Annotated[
        str | None, Query(description="The previous page's next_cursor; omit for the first page.")
    ] = None,
) -> BriefingListResponse:
    """One page of the user's briefings archive (daily + weekly) as their cards, newest first."""
    user_id = user.user_id
    log.set(user={"id": user_id}, briefing={"operation": "list", "limit": limit})
    anchor = None
    if before is not None:
        anchor = await briefing_repository.get_card(before, user_id=user_id)
        if anchor is None:
            raise HTTPException(status_code=404, detail="Briefing not found")
    # One past the page says whether another follows.
    found = await briefing_repository.list_cards(user_id, limit=limit + 1, before=anchor)
    page = found[:limit]
    return BriefingListResponse(
        briefings=[await briefing_card(b) for b in page],
        next_cursor=page[-1].id if len(found) > limit else None,
    )


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


# evlog-map-disable-next-line audit -- read-only preference lookup, no state change to audit
@router.get("/schedule")
async def read_briefing_schedule(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BriefingScheduleState:
    """How often the user's briefs come, the daily brief's hour on their clock, and whether they run."""
    log.set(user={"id": user.user_id}, operation="read_briefing_schedule")
    return await briefing_schedule_state(user.user_id)


@router.put(
    "/schedule",
    responses={
        409: {
            "model": BriefDeliveryWorkflowsConflict,
            "description": "Briefs cannot turn off while workflows deliver to the brief",
        }
    },
)
async def update_briefing_schedule(
    body: BriefingScheduleUpdate,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BriefingScheduleState:
    """Replace the user's briefing schedule, moving their briefs onto it; echoes back how it now runs."""
    log.set(user={"id": user.user_id}, operation="update_briefing_schedule")
    await set_briefing_schedule(
        user.user_id,
        body.frequency,
        "settings",
        hour=body.hour,
        workflow_deliveries=body.workflow_deliveries,
    )
    return await briefing_schedule_state(user.user_id)


# evlog-map-disable-next-line audit -- read-only preference lookup, no state change to audit
@router.get("/editions")
async def read_briefing_editions(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BriefingEditions:
    """Every daily edition family a brief can draw, and whether the user keeps it on or favours it."""
    log.set(user={"id": user.user_id}, operation="read_briefing_editions")
    return briefing_editions((await briefing_state_repository.state_for(user.user_id)).editions)


@router.put("/editions")
async def update_briefing_editions(
    body: BriefingEditionsUpdate,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BriefingEditions:
    """Replace which daily edition families are off or favourited; at least one must stay on."""
    log.set(user={"id": user.user_id}, operation="update_briefing_editions")
    return await set_edition_choices(user.user_id, body.choices)


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
    return await briefing_view(briefing)


@router.get(
    "/editions/{key}/{variant}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in EDITION_CONTENT_TYPES.values()}}},
)
async def get_edition_image(
    key: str,
    variant: EditionVariant,
    t: Annotated[str, Query(description="The signature the brief's edition URL carries.")],
) -> Response:
    """Serve a brief's edition image to whoever holds its signed URL; anything else is a 404."""
    log.set(briefing={"operation": "edition_image", "variant": variant.value})
    image = await signed_edition(key, variant, t, datetime.now(UTC))
    if image is None:
        raise HTTPException(status_code=404, detail="Edition not found")
    return Response(
        image,
        media_type=EDITION_CONTENT_TYPES[variant],
        headers={"Cache-Control": f"private, max-age={EDITION_IMAGE_MAX_AGE_SECONDS}"},
    )


@router.get(
    "/stamps/{slug}.webp",
    response_class=FileResponse,
    responses={200: {"content": {STAMP_ART_CONTENT_TYPE: {}}}},
)
async def get_stamp_art(slug: str) -> FileResponse:
    """Serve a catalogued city's stamp art, the same file for everyone; any other slug is a 404."""
    log.set(briefing={"operation": "stamp_art", "city_slug": slug})
    try:
        art = stamp_art(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Stamp not found") from None
    return FileResponse(
        art,
        media_type=STAMP_ART_CONTENT_TYPE,
        headers={"Cache-Control": f"public, max-age={STAMP_ART_MAX_AGE_SECONDS}"},
    )
