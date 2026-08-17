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

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserLoginResponse,
    BrowserTaskResponse,
    HandoffDecisionRequest,
    HandoffDecisionResponse,
    LiveViewTokenResponse,
)
from app.services.browser import registry
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.handoff import get_handoff, resolve_handoff
from app.services.browser.profiles import forget_saved_login, list_saved_logins
from app.services.browser.takeover_token import (
    create_takeover_token,
    takeover_token_ttl_seconds,
)
from app.services.browser.tasks import delete_browser_task, list_browser_tasks
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
    except BrowserHandoffNotOwned as exc:
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


@router.get("/tasks", response_model=list[BrowserTaskResponse])
async def list_browser_tasks_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[BrowserTaskResponse]:
    """The user's browser task history (settings), newest first, with recap URLs."""
    log.set(user={"id": user_id}, browser={"operation": "list_tasks"})
    tasks = await list_browser_tasks(user_id, limit=limit)
    log.set(browser={"result_count": len(tasks)})
    return tasks


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_browser_task_endpoint(
    task_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Remove one task from the user's browser history."""
    log.set(user={"id": user_id}, browser={"operation": "delete_task", "task_id": task_id})
    await delete_browser_task(user_id, task_id)


@router.get("/logins", response_model=list[BrowserLoginResponse])
async def list_browser_logins_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
) -> list[BrowserLoginResponse]:
    """Domains the user has a saved browser login for (never the encrypted state)."""
    log.set(user={"id": user_id}, browser={"operation": "list_logins"})
    return await list_saved_logins(user_id)


@router.delete("/logins/{domain}", status_code=204)
async def forget_browser_login_endpoint(
    domain: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Forget the saved login for one domain."""
    log.set(user={"id": user_id}, browser={"operation": "forget_login", "domain": domain})
    await forget_saved_login(user_id, domain)


@router.delete("/logins", status_code=204)
async def clear_browser_logins_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Forget every saved browser login for the user."""
    log.set(user={"id": user_id}, browser={"operation": "clear_logins"})
    await forget_saved_login(user_id, None)
