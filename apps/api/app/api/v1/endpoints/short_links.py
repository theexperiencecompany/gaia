"""Short links — public resolution of heygaia.link/<slug>, owner share + stop sharing.

The slug is the capability: high-entropy and globally unique, it grants
read-only access to one artifact's public view with no session, because links
must open from Telegram/WhatsApp/email where the viewer is never signed in.
Unknown, revoked and deleted-target slugs are indistinguishable (404), so
probing leaks nothing, and the 62¹¹ namespace makes enumeration hopeless. A slug is never logged: every route here records the route template as
the request path and a keyed hash of the slug as ``short_link.slug_hash``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.short_link_models import (
    PublicShortLinkView,
    ShortLinkResponse,
    ShortLinkTargetRequest,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import error_responses
from app.services.short_link_projections import project_target
from app.services.short_link_service import (
    get_public_file,
    get_public_view,
    share_short_link,
    stop_sharing,
)
from app.services.storage import JuiceFSUnavailable
from app.utils.log_identifiers import hash_short_link_slug
from app.utils.loggable_path import SHORT_LINK_ROUTE_PREFIX, SHORT_LINK_UNSHARE_PATH
from app.utils.sandboxed_file_response import sandboxed_file_response
from shared.py.wide_events import log

router = APIRouter(prefix=SHORT_LINK_ROUTE_PREFIX, tags=["Short Links"])

# A capability URL can be revoked at any moment, so no browser or intermediary
# may keep serving content the owner has already taken back.
_NO_STORE = "no-store"
_NOT_FOUND = "Short link not found"
_STORAGE_OFFLINE = "Workspace storage offline"


@router.post("")
async def create_short_link_route(
    body: ShortLinkTargetRequest, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> ShortLinkResponse:
    """Share an artifact the caller owns: return its heygaia.link, minting one.

    Turns sharing back on for a target its owner had stopped sharing.
    """
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
    url = await share_short_link(user_id, body.target_type, body.target_id)
    return ShortLinkResponse(url=url)


@router.get("/{slug}", response_model=PublicShortLinkView)
async def resolve_short_link_route(response: Response, slug: str) -> PublicShortLinkView:
    """Resolve a capability slug to its target's public view. No auth."""
    log.set(short_link={"operation": "resolve", "slug_hash": hash_short_link_slug(slug)})
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
async def get_short_link_file_route(slug: str) -> FileResponse:
    """Stream the file behind a session-artifact slug (images, PDFs, downloads).
    No auth; sandboxed exactly like the owner's own session-file route."""
    log.set(short_link={"operation": "file", "slug_hash": hash_short_link_slug(slug)})
    try:
        host_path = await get_public_file(slug)
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail=_STORAGE_OFFLINE) from e
    if host_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return sandboxed_file_response(host_path, cache_control=_NO_STORE)


@router.post(SHORT_LINK_UNSHARE_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def stop_sharing_route(
    body: ShortLinkTargetRequest, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> Response:
    """Stop sharing one of your artifacts: its link goes dead immediately, and GAIA
    attaches no new one until you share it again. Idempotent."""
    user_id = user.user_id
    log.set(
        user={"id": user_id},
        short_link={"operation": "stop_sharing", "target_type": body.target_type.value},
    )
    revoked = await stop_sharing(user_id, body.target_type, body.target_id)
    log.set(short_link={"revoked": revoked})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
