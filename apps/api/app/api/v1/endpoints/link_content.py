"""The content origin: a shared file's bytes, served only to requests that arrived on its own host.

GAIA Cloud's usercontent Worker (on *.heygaia.link) and a self-host's Caddy
site block forward here. A request is served only when the host it arrived on
is its snapshot's content-origin host, so the same path reached on the API or
app host (which carry the session cookie) serves nothing. The Worker cannot
keep the browser's Host, so it names it in X-Gaia-Content-Host beside
LINK_CONTENT_EDGE_TOKEN, a secret only it holds; any other caller cannot.
"""

from datetime import UTC, datetime
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config.settings import settings
from app.constants.http import CONTENT_EDGE_HEADER, CONTENT_HOST_HEADER
from app.constants.short_links import THUMBNAIL_PATH
from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import LinkAccess, ShortLink
from app.services.links.access import dead_state
from app.services.links.content import (
    active_link_content,
    content_origin_host,
    read_snapshot,
    read_thumbnail,
    servable,
    token_valid,
)
from app.services.links.serving import snapshot_response, thumbnail_response
from app.services.links.urls import build_url
from app.utils.errors import AppError
from app.utils.loggable_path import LINK_CONTENT_ROUTE_PREFIX
from shared.py.wide_events import log

router = APIRouter(prefix=LINK_CONTENT_ROUTE_PREFIX, tags=["Link Content"], include_in_schema=False)

_PREVIEWABLE = frozenset({LinkAccess.PUBLIC, LinkAccess.UNLISTED})


def _not_found() -> AppError:
    return AppError(message="Not found", status_code=404, code="link_content_not_found")


def _from_content_edge(request: Request) -> bool:
    expected = settings.LINK_CONTENT_EDGE_TOKEN
    presented = request.headers.get(CONTENT_EDGE_HEADER)
    return (
        expected is not None
        and presented is not None
        and secrets.compare_digest(presented.encode(), expected.encode())
    )


def _arrived_on_origin(request: Request, content_id: str) -> bool:
    forwarded = request.headers.get(CONTENT_HOST_HEADER) if _from_content_edge(request) else None
    host = forwarded or request.headers.get("host")
    return host is not None and host.lower() == content_origin_host(content_id)


async def _live_link(request: Request, content_id: str) -> ShortLink:
    if not active_link_content() or not _arrived_on_origin(request, content_id):
        raise _not_found()
    link = await short_link_repository.get_live_by_content_id(content_id)
    if link is None or dead_state(link, datetime.now(UTC)) is not None:
        raise _not_found()
    return link


@router.get("/{content_id}", response_class=Response)
async def serve_link_content_route(
    request: Request,
    content_id: str,
    t: Annotated[str, Query()] = "",  # pragma: no mutate — any non-token default redirects
    sec_fetch_dest: Annotated[str | None, Header()] = None,
) -> Response:
    """Serve a snapshot's bytes with its render mode's headers; a missing or stale token goes back to the link."""
    log.set(short_link={"operation": "serve", "fetch_dest": sec_fetch_dest})
    link = await _live_link(request, content_id)
    snapshot = link.snapshot
    if snapshot is None or not servable(snapshot, link.access):
        raise _not_found()
    link_url = build_url(link.slug)
    now = datetime.now(UTC)  # pragma: no mutate — token_valid reads only the instant
    if not token_valid(link, content_id, t, now):
        log.set(short_link={"signed_url": "stale"})
        return RedirectResponse(link_url, status_code=status.HTTP_302_FOUND)
    log.set(short_link={"render": snapshot.render.value})
    body = await read_snapshot(link.user_id, content_id)
    return snapshot_response(body, snapshot, sec_fetch_dest, link_url)


@router.get(f"/{{content_id}}/{THUMBNAIL_PATH}", response_class=Response)
async def serve_link_thumbnail_route(request: Request, content_id: str) -> Response:
    """Serve a public or unlisted snapshot's preview image, tokenless so chat apps can fetch it."""
    log.set(short_link={"operation": "thumbnail"})
    link = await _live_link(request, content_id)
    snapshot = link.snapshot
    if (
        snapshot is None
        or not snapshot.has_thumbnail
        or link.access not in _PREVIEWABLE
        or not servable(snapshot, link.access)
    ):
        raise _not_found()
    return thumbnail_response(await read_thumbnail(link.user_id, content_id))
