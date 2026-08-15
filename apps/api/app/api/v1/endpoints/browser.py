"""Browser mid-run handoff endpoint.

When the agent hands off a sensitive step to the user (live-view), the card's
Continue/Cancel buttons POST here; the decision is written to Redis, unblocking
the browser tool that is polling for it (the tool may run in a different worker
process — Redis is the bridge).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffDecisionRequest, HandoffDecisionResponse
from app.services.browser.handoff import get_handoff, resolve_handoff
from shared.py.wide_events import log

router = APIRouter(prefix="/browser", tags=["Browser"])


@router.get("/handoffs/{handoff_id}", response_model=HandoffDecisionResponse)
async def get_browser_handoff(
    handoff_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> HandoffDecisionResponse:
    """Current status of a browser handoff — the card polls this so a reload or a
    resolution made elsewhere (chat, another device) is reflected reliably."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(user={"id": user_id}, browser={"handoff_id": handoff_id})
    record = await get_handoff(handoff_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
    return HandoffDecisionResponse(handoff_id=handoff_id, status=record.status)


@router.post("/handoffs/{handoff_id}/decision", response_model=HandoffDecisionResponse)
async def decide_browser_handoff(
    handoff_id: str,
    payload: HandoffDecisionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> HandoffDecisionResponse:
    """Continue (user finished the step in live-view) or cancel a browser handoff."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(
        user={"id": user_id}, browser={"handoff_id": handoff_id, "decision": payload.decision.value}
    )

    try:
        resolved = await resolve_handoff(handoff_id, payload.decision, user_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to resolve this handoff"
        ) from exc

    if resolved is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Handoff not found or expired")

    log.info(
        f"{LogTag.BROWSER} Browser handoff decided", handoff_id=handoff_id, status=resolved.value
    )
    return HandoffDecisionResponse(handoff_id=handoff_id, status=resolved)
