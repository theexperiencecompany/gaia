"""Short links — public resolution of heygaia.link/<slug>, owner mint + revoke.

The slug is the capability: high-entropy and globally unique, it grants
read-only access to one artifact's public view with no session, because links
must open from Telegram/WhatsApp/email where the viewer is never signed in.
Unknown, revoked and deleted-target slugs are indistinguishable (404), so
probing leaks nothing; the rate limit makes enumeration of a 62¹¹ namespace
hopeless.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.models.short_link_models import (
    PublicShortLinkView,
    ShortLinkCreateRequest,
    ShortLinkResponse,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import error_responses
from app.services.short_link_projections import project_target
from app.services.short_link_service import (
    get_or_create_short_link,
    get_public_file,
    get_public_view,
    revoke_short_link,
)
from app.services.storage import JuiceFSUnavailable
from app.utils.sandboxed_file_response import sandboxed_file_response
from shared.py.wide_events import log

router = APIRouter(prefix="/l", tags=["Short Links"])

# A capability URL can be revoked at any moment, so no browser or intermediary
# may keep serving content the owner has already taken back.
_NO_STORE = "no-store"
_NOT_FOUND = "Short link not found"
_STORAGE_OFFLINE = "Workspace storage offline"


@router.post("")
async def create_short_link_route(
    body: ShortLinkCreateRequest, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> ShortLinkResponse:
    """Mint (or return) the heygaia.link for an artifact the caller owns."""
    user_id = user.user_id
    log.set(
        user={"id": user_id},
        short_link={"operation": "create", "target_type": body.target_type.value},
    )
    # The projection is the ownership check: a target this user does not own
    # projects to nothing, so a link to someone else's work is never minted.
    try:
        view = await project_target(body.target_type, user_id, body.target_id)
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail=_STORAGE_OFFLINE) from e
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    url = await get_or_create_short_link(user_id, body.target_type, body.target_id)
    return ShortLinkResponse(url=url)


@router.get("/{slug}", response_model=PublicShortLinkView)
@limiter.limit("60/minute")
@limiter.limit("600/hour")
async def resolve_short_link_route(
    request: Request, response: Response, slug: str
) -> PublicShortLinkView:
    """Resolve a capability slug to its target's public view. No auth."""
    log.set(short_link={"operation": "resolve", "slug": slug})
    response.headers["Cache-Control"] = _NO_STORE  # pragma: no mutate — case-insensitive name
    try:
        view = await get_public_view(slug)
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail=_STORAGE_OFFLINE) from e
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    log.set(short_link={"target_type": view.target_type.value})
    return view


@router.get(
    "/{slug}/file",
    response_class=FileResponse,
    responses=error_responses({404: _NOT_FOUND, 503: _STORAGE_OFFLINE}),
)
@limiter.limit("60/minute")
@limiter.limit("600/hour")
async def get_short_link_file_route(request: Request, slug: str) -> FileResponse:
    """Stream the file behind a session-artifact slug (images, PDFs, downloads).
    No auth; sandboxed exactly like the owner's own session-file route."""
    log.set(short_link={"operation": "file", "slug": slug})
    try:
        host_path = await get_public_file(slug)
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail=_STORAGE_OFFLINE) from e
    if host_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return sandboxed_file_response(host_path, cache_control=_NO_STORE)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_short_link_route(
    slug: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> Response:
    """Revoke a short link you own; the URL goes dead immediately."""
    user_id = user.user_id
    log.set(user={"id": user_id}, short_link={"operation": "revoke", "slug": slug})
    if not await revoke_short_link(user_id, slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
