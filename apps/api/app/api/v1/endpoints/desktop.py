"""Desktop app endpoints.

Two concerns share the ``/desktop`` prefix:

- the tool bridge (authed): the Electron app POSTs results of desktop-executed
  tool actions here, and the endpoint relays them to the awaiting agent tool;
- release distribution (public): the marketing download page resolves the latest
  desktop binary so its buttons link straight to the right platform/arch asset.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.schemas.desktop_schemas import (
    DesktopReleaseResponse,
    DesktopToolResultRequest,
    DesktopToolResultResponse,
)
from app.services.desktop.bridge import relay_desktop_result
from app.services.desktop.releases import get_latest_desktop_release
from shared.py.wide_events import log

router = APIRouter(prefix="/desktop", tags=["desktop"])


@router.get("/releases/latest")
async def latest_desktop_release() -> DesktopReleaseResponse:
    """Return the newest published desktop release and its per-platform binaries.

    Public (no auth) — the download page links straight to the correct
    platform/arch asset instead of falling back to the GitHub releases list.
    """
    log.set(desktop_release={"operation": "resolve_latest"})
    release = await get_latest_desktop_release()
    log.set(desktop_release={"tag": release.tag, "asset_count": len(release.assets)})
    return release


@router.post("/tool-result")
async def desktop_tool_result(
    payload: DesktopToolResultRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> DesktopToolResultResponse:
    """Accept a desktop tool result and relay it to the awaiting agent tool.

    ``relay_desktop_result`` raises :class:`DesktopRequestNotFound` (410) or
    :class:`DesktopRequestForbidden` (403) — both ``AppError`` subclasses that the
    global handler maps to the right status — so late/duplicate or cross-user
    deliveries can't double-resolve a request.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")

    log.set(
        user={"id": user_id},
        desktop_tool={"request_id": payload.request_id, "ok": payload.ok},
    )

    await relay_desktop_result(
        request_id=payload.request_id,
        user_id=user_id,
        ok=payload.ok,
        data=payload.data,
        error=payload.error,
    )

    log.set(desktop_tool={"relayed": True})
    return DesktopToolResultResponse(success=True)
