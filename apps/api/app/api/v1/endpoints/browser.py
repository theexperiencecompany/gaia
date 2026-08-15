"""Browser mid-run handoff + authenticated live-view endpoints.

Handoff: when the agent hands off a sensitive step to the user, the card's
Continue/Cancel buttons POST here; the decision is written to Redis, unblocking
the browser tool that is polling for it (the tool may run in a different worker
process — Redis is the bridge).

Live view: the browser host is never exposed directly. ``/sessions/{id}/live-view``
authenticates a web session (cookie) or a short-lived ``?t=`` takeover token,
authorizes it against the session's registered owner, then proxies frames and
input between the viewer and the host's ``WS /live/{id}``. The chat card connects
to the WebSocket with a canvas; a bot user with no web session opens the GET page.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import HTMLResponse
from jose import JWTError
import websockets

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_current_user_ws
from app.browser_host.pumps import pump_until_first_close
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffDecisionRequest, HandoffDecisionResponse
from app.services.browser import registry
from app.services.browser.handoff import get_handoff, resolve_handoff
from app.services.browser.live_view import render_live_view_page
from app.services.browser.takeover_token import (
    takeover_token_ttl_seconds,
    verify_takeover_token,
)
from shared.py.wide_events import log

router = APIRouter(prefix="/browser", tags=["Browser"])

# WebSocket close code for "session unknown or has no live stream" (app 4xxx range).
_WS_SESSION_GONE = 4404


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


# ---------------------------------------------------------------------------
# Live view — served through OUR API, never the browser host directly
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/live-view")
async def browser_live_view_page(
    session_id: str,
    request: Request,
    t: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Standalone live-view page for a viewer with no web app — a bot user opening
    the ``?t=`` link. The chat card connects to the WebSocket below directly."""
    log.set(browser={"session_id": session_id, "operation": "live_view_page"})
    user_id = await _authorize_page(request, session_id, t)
    owner = await registry.session_owner(session_id)
    if owner is None or owner != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session"
        )
    log.info(f"{LogTag.BROWSER} browser live view page served")
    return HTMLResponse(content=render_live_view_page(session_id))


@router.websocket("/sessions/{session_id}/live-view")
async def browser_live_view_ws(
    websocket: WebSocket,
    session_id: str,
    t: Annotated[str | None, Query()] = None,
) -> None:
    """Proxy the authenticated live view: host frames out to the viewer, the
    viewer's mouse/key input back to the host. Auth (cookie session or ``?t=``
    takeover token) and ownership are checked on connect; a token connection is
    bounded to the token's remaining lifetime."""
    log.set(browser={"session_id": session_id, "operation": "live_view_ws"})

    resolved = await _authorize_ws(websocket, session_id, t)
    if resolved is None:
        return  # _authorize_ws already closed the socket with a policy-violation code
    user_id, ttl_seconds = resolved

    entry = await registry.get_session_entry(session_id)
    if entry is None or entry.owner != user_id:
        log.warning(f"{LogTag.BROWSER} browser live view ownership denied", session_id=session_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not entry.live_ws:
        log.warning(f"{LogTag.BROWSER} browser live view has no host stream", session_id=session_id)
        await websocket.close(code=_WS_SESSION_GONE)
        return

    await websocket.accept()
    log.info(f"{LogTag.BROWSER} browser live view proxy opened")
    await _proxy_live_view(websocket, entry.live_ws, ttl_seconds)


async def _authorize_page(request: Request, session_id: str, token: str | None) -> str:
    """Resolve the user id for a GET live-view page: takeover token or web session."""
    if token:
        claims = _verify_scoped_token(token, session_id)
        return claims["user_id"]
    user = await get_current_user(request)
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    return str(user_id)


async def _authorize_ws(
    websocket: WebSocket, session_id: str, token: str | None
) -> tuple[str, float | None] | None:
    """Resolve ``(user_id, ttl_seconds)`` for a live-view WS, or close and return None.

    ``ttl_seconds`` is the token's remaining lifetime for a takeover connection, or
    ``None`` for a cookie session (no token deadline).
    """
    if token:
        try:
            claims = verify_takeover_token(token)
        except JWTError:
            log.warning(f"{LogTag.BROWSER} browser live view rejected invalid takeover token")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        if claims["session_id"] != session_id:
            log.warning(f"{LogTag.BROWSER} browser live view token session mismatch")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        return claims["user_id"], max(takeover_token_ttl_seconds(token), 0.0)

    user = await get_current_user_ws(websocket)  # closes the socket on auth failure
    user_id = user.get("user_id")
    if not user_id:
        return None
    return str(user_id), None


def _verify_scoped_token(token: str, session_id: str) -> dict[str, str]:
    """Verify a takeover token and assert it is scoped to ``session_id`` (HTTP path)."""
    try:
        claims = verify_takeover_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired link"
        ) from exc
    if claims["session_id"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Link does not match this session"
        )
    return claims


async def _proxy_live_view(
    client_ws: WebSocket, host_ws_url: str, ttl_seconds: float | None
) -> None:
    """Bridge the viewer's WebSocket to the host's live-view WebSocket both ways."""
    try:
        async with websockets.connect(host_ws_url, max_size=None) as host_ws:
            directions = [
                _pump_host_to_client(host_ws, client_ws),
                _pump_client_to_host(client_ws, host_ws),
            ]
            if ttl_seconds is not None:
                directions.append(_expire_after(ttl_seconds))
            await pump_until_first_close(*directions)
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        log.warning(
            f"{LogTag.BROWSER} browser live view host unreachable", error_type=type(exc).__name__
        )
    finally:
        with contextlib.suppress(Exception):
            await client_ws.close()
    log.info(f"{LogTag.BROWSER} browser live view proxy closed")


async def _pump_host_to_client(host_ws: websockets.ClientConnection, client_ws: WebSocket) -> None:
    async for message in host_ws:
        if isinstance(message, bytes):
            await client_ws.send_bytes(message)
        else:
            await client_ws.send_text(message)


async def _pump_client_to_host(client_ws: WebSocket, host_ws: websockets.ClientConnection) -> None:
    while True:
        message = await client_ws.receive_text()
        await host_ws.send(message)


async def _expire_after(seconds: float) -> None:
    """End the proxy once the takeover token's lifetime elapses (WS then closes)."""
    await asyncio.sleep(max(seconds, 0.0))
