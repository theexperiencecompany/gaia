"""Short-link resolution — GET /l/{slug} (public) + owner revocation.

The slug is the capability: high-entropy and globally unique, it grants
read-only access to one artifact's deliverable with no session, because
briefing links must open from Telegram/WhatsApp where the viewer is never
signed in. Unknown, revoked, and expired slugs are indistinguishable (404), so
probing leaks nothing; the rate limit makes enumeration of a 36⁸ namespace
hopeless.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.services.short_link_service import get_public_artifact, revoke_short_link
from shared.py.wide_events import log

router = APIRouter()


@router.get("/l/{slug}")
@limiter.limit("60/minute")
@limiter.limit("600/hour")
async def resolve_short_link_route(request: Request, slug: str) -> JSONResponse:
    """Resolve a capability slug to its read-only artifact content. No auth."""
    log.set(short_link={"operation": "resolve", "slug": slug})
    artifact = await get_public_artifact(slug)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found")
    return JSONResponse(content=artifact)


@router.delete("/l/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_short_link_route(
    slug: str, user: Annotated[dict, Depends(get_current_user)]
) -> Response:
    """Revoke a short link you own; the URL goes dead immediately."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, short_link={"operation": "revoke", "slug": slug})
    if not await revoke_short_link(user_id, slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
