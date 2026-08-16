"""Browser mid-run handoff + live-view token endpoints (authenticated, same-origin).

Handoff: when the agent hands off a sensitive step to the user, the card's
Continue/Cancel buttons POST here; the decision is written to Redis, unblocking
the browser tool that is polling for it (the tool may run in a different worker
process — Redis is the bridge).

Live-view token: the live view itself is served at the root ``/live/{id}`` route
(``endpoints/browser_live_view.py``), fronted by a friendly public vhost the
host-only session cookie is never sent to. The chat card therefore fetches a
short-lived ``?t=`` takeover token here (cookie auth works same-origin to the
API) and opens the cross-origin live-view socket with it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    HandoffDecisionRequest,
    HandoffDecisionResponse,
    LiveViewTokenResponse,
)
from app.services.browser import registry
from app.services.browser.handoff import get_handoff, resolve_handoff
from app.services.browser.takeover_token import (
    create_takeover_token,
    takeover_token_ttl_seconds,
)
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
        resolved = await resolve_handoff(handoff_id, payload.decision, user_id, payload.message)
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


@router.get("/sessions/{session_id}/live-view-token", response_model=LiveViewTokenResponse)
async def get_live_view_token(
    session_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> LiveViewTokenResponse:
    """Mint a short-lived takeover token so the web card can open the cross-origin
    live view (the host-only session cookie is not sent to the live-view vhost)."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(
        user={"id": user_id}, browser={"session_id": session_id, "operation": "live_view_token"}
    )

    owner = await registry.session_owner(session_id)
    if owner is None or owner != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session"
        )

    token = create_takeover_token(session_id, str(user_id))
    log.info(f"{LogTag.BROWSER} browser live view token issued")
    return LiveViewTokenResponse(token=token, expires_in=int(takeover_token_ttl_seconds(token)))
