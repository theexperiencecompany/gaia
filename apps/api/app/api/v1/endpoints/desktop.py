"""Desktop tool bridge endpoints.

The Electron app POSTs results of desktop-executed tool actions here; the
endpoint validates ownership against the pending-request key and relays the
payload to the awaiting agent tool over Redis.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.schemas.desktop_schemas import DesktopToolResultRequest, DesktopToolResultResponse
from app.services.desktop.bridge import relay_desktop_result
from shared.py.wide_events import log

router = APIRouter(prefix="/desktop", tags=["desktop"])


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
