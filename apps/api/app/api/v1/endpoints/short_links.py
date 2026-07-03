"""Short-link resolution — GET /l/{slug}.

Resolves a heygaia.link slug for the signed-in viewer and redirects to the
artifact it points at. Viewer-scoped: a slug that is not the viewer's own
resolves to 404, so a forwarded link never exposes someone else's artifact.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.models.short_link_models import ShortLink
from app.services.short_link_service import resolve_short_link
from shared.py.wide_events import log

router = APIRouter()


def _target_path(link: ShortLink) -> str:
    """Frontend path that renders the artifact behind ``link``.

    One arm per target type — a new ShortLinkTarget adds a single line here.
    """
    if link.target_type == "todo_canvas":
        return f"/a/{link.target_id}"
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Unsupported short-link target",
    )


@router.get("/l/{slug}")
async def resolve_short_link_route(
    slug: str, user: Annotated[dict, Depends(get_current_user)]
) -> RedirectResponse:
    """Redirect the signed-in viewer to the artifact behind ``slug``."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, short_link={"operation": "resolve", "slug": slug})
    link = await resolve_short_link(user_id, slug)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found")
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{_target_path(link)}")
