"""Desktop tool bridge endpoints.

The Electron app POSTs results of desktop-executed tool actions here; the
endpoint validates ownership against the pending-request key and relays the
payload to the awaiting agent tool over Redis.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.cache import DESKTOP_REQUEST_PREFIX
from app.db.redis import redis_cache
from app.schemas.desktop_schemas import DesktopToolResultRequest, DesktopToolResultResponse
from app.services.desktop.bridge import publish_desktop_result
from shared.py.wide_events import log

router = APIRouter()


@router.post("/desktop/tool-result", response_model=DesktopToolResultResponse)
async def desktop_tool_result(
    payload: DesktopToolResultRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> DesktopToolResultResponse:
    """Accept a desktop tool result and relay it to the awaiting agent tool."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")

    log.set(
        user={"id": user_id},
        desktop_tool={"request_id": payload.request_id, "ok": payload.ok},
    )

    request_key = f"{DESKTOP_REQUEST_PREFIX}{payload.request_id}"
    pending = await redis_cache.get(request_key)
    if not pending:
        # Expired or already answered — reject so late/duplicate deliveries
        # can't double-resolve a request.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Desktop tool request expired or already resolved",
        )
    if pending.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Desktop tool request belongs to another user",
        )

    await redis_cache.delete(request_key)
    await publish_desktop_result(
        payload.request_id,
        ok=payload.ok,
        data=payload.data,
        error=payload.error,
    )
    return DesktopToolResultResponse(success=True)
