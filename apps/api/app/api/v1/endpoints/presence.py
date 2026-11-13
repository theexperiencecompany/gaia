"""Presence endpoints: a GAIA app tells the API that the user is looking at it."""

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.requests import Request

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.api.v1.middleware.client_type import request_client_source
from app.models.chat_models import ConversationSource
from app.schemas.errors import error_responses
from app.services.delivery.presence import FOCUS_SURFACES, clear_focus, mark_focused
from app.utils.errors import AppError
from shared.py.wide_events import log

router = APIRouter(prefix="/presence")

CurrentUserId = Annotated[str, Depends(get_user_id)]


def _reporting_surface(request: Request) -> ConversationSource:
    """Return the app that sent request, refusing one that does not report focus."""
    surface = request_client_source(request)
    if surface not in FOCUS_SURFACES:
        raise AppError(
            message=f"The {surface.value} app does not report focus.",
            status_code=400,
            code="presence_surface_unsupported",
        )
    return surface


@router.put(
    "/focus",
    status_code=204,
    responses=error_responses({400: "The calling app does not report focus"}),
)
async def hold_focus(request: Request, user_id: CurrentUserId) -> None:
    """Keep the user marked as looking at this app; the client calls it on every heartbeat while visible, focused and in use."""
    log.set(user={"id": user_id}, operation="hold_focus")
    await mark_focused(user_id, _reporting_surface(request))


@router.delete(
    "/focus",
    status_code=204,
    responses=error_responses({400: "The calling app does not report focus"}),
)
async def release_focus(request: Request, user_id: CurrentUserId) -> None:
    """Record that the user stopped looking at this app: it was hidden or lost focus."""
    log.set(user={"id": user_id}, operation="release_focus")
    await clear_focus(user_id, _reporting_surface(request))
