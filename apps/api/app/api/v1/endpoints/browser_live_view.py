"""Root-mounted authenticated browser live view.

Root-mounted (no ``/api/v1`` prefix), so the recap and screenshot links can sit
on a friendly public vhost that reverse-proxies to THIS api service. The browser
host is never exposed directly.

``WEBSOCKET /live/{id}`` proxies frames + input between a viewer (the chat card,
or the web app's full-page live view a bot link opens), dialled on the API's own
origin, and the host's ``WS /live/{id}``; ``POST /live/{code}/decision`` answers
the handoff a bot link was sent for. The web card authenticates with a
short-lived ``?t=`` takeover token; a same-origin viewer may still use the
session cookie. Ownership is re-checked against the Redis registry on connect;
a token connection is bounded to the token's remaining lifetime, and a code
connection closes the moment its handoff settles.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from fastapi.responses import HTMLResponse, Response
from jose import JWTError
from starlette.websockets import WebSocketState
import websockets

from app.api.v1.dependencies.oauth_dependencies import get_current_user_ws
from app.browser_host.pumps import pump_until_first_close
from app.constants.browser import (
    BROWSER_HANDOFF_GONE_DETAIL,
    BROWSER_LIVE_VIEW_NOT_WAITING_DETAIL,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffDecisionRequest, HandoffDecisionResponse
from app.schemas.errors import HTML_ROUTE_ERROR_RESPONSES
from app.services.browser import registry
from app.services.browser.handoff_buttons import decide_handoff_by_button
from app.services.browser.live_code import live_code_ended, resolve_live_code
from app.services.browser.replay import render_replay_page, resolve_replay_code
from app.services.browser.shot_store import SHOT_SUFFIX, read_step_screenshot
from app.services.browser.takeover_token import (
    TakeoverTokenClaims,
    takeover_token_ttl_seconds,
    verify_takeover_token,
)
from shared.py.wide_events import log

router = APIRouter(tags=["Browser"])

# WebSocket close code for "session unknown or has no live stream" (app 4xxx range).
_WS_SESSION_GONE = 4404

#: What ends a live-view connection besides either side closing: its authority running out.
_ConnectionEnd = Callable[[], Awaitable[None]]


@router.get(f"/shots/{{code}}/{{index}}{SHOT_SUFFIX}", response_class=Response)
async def step_screenshot(code: str, index: int) -> Response:
    """One step frame of a run, for deployments with no object store.

    Same capability model as the recap page it feeds: the code is the secret, so
    a frame cannot be reached by guessing a session id, and it expires with the
    code.
    """
    log.set(browser={"operation": "step_screenshot"})
    frame = await read_step_screenshot(code, index)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found or expired"
        )
    return Response(content=frame, media_type="image/jpeg")


@router.get("/replays/{code}", response_class=HTMLResponse, responses=HTML_ROUTE_ERROR_RESPONSES)
async def replay_page(code: str) -> HTMLResponse:
    """Standalone recap slideshow for a finished session. ``code`` resolves to the
    session + step count in Redis; the step screenshots are public R2 URLs, so no
    per-session auth is needed (the code itself is the unguessable capability)."""
    log.set(browser={"operation": "replay_page"})
    record = await resolve_replay_code(code)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recap not found or expired"
        )
    log.set(browser={"session_id": record.session_id})
    log.info(f"{LogTag.BROWSER} browser replay page served")
    return HTMLResponse(content=render_replay_page(record))


@router.post("/live/{code}/decision")
async def decide_live_view_handoff(
    code: str, payload: HandoffDecisionRequest
) -> HandoffDecisionResponse:
    """Done or Stop from the bot user's live-view page: the code that opened the page is the authority.

    The same decision a chat reply or the web card's buttons make, for the
    handoff this link was sent for.
    """
    log.set(browser={"operation": "live_view_decision", "decision": payload.decision.value})
    record = await resolve_live_code(code)
    if record is None or record.handoff_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=BROWSER_LIVE_VIEW_NOT_WAITING_DETAIL
        )
    log.set(user={"id": record.user_id}, browser={"handoff_id": record.handoff_id})
    resolved = await decide_handoff_by_button(
        record.handoff_id, payload.decision, record.user_id, payload.message
    )
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=BROWSER_HANDOFF_GONE_DETAIL)
    log.set(browser={"handoff_status": resolved.value})
    return HandoffDecisionResponse(handoff_id=record.handoff_id, status=resolved)


@router.websocket("/live/{code}")
async def live_view_ws(
    websocket: WebSocket,
    code: str,
    t: Annotated[str | None, Query()] = None,
) -> None:
    """Proxy the authenticated live view: host frames out to the viewer, the
    viewer's mouse/key input back to the host. ``code`` is a short capability code
    (bot link) or a raw session id + ``?t=`` token / cookie (web card), and the
    connection ends with whichever authorised it."""
    log.set(browser={"operation": "live_view_ws"})

    resolved = await _resolve_target_ws(websocket, code, t)
    if resolved is None:
        return  # already closed the socket with a policy-violation code
    session_id, user_id, ends = resolved
    log.set(browser={"session_id": session_id})

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
    await _proxy_live_view(websocket, entry.live_ws, ends)


async def _resolve_target_ws(
    websocket: WebSocket, code: str, token: str | None
) -> tuple[str, str, _ConnectionEnd | None] | None:
    """``(session_id, user_id, ends)`` for a WS, or ``None`` (socket closed). The
    connection ends with what authorised it: the code's handoff settling or the
    code lapsing, or the token's lifetime; a cookie session has no end of its own."""
    record = await resolve_live_code(code)
    if record is not None:
        return record.session_id, record.user_id, partial(live_code_ended, code)
    resolved = await _authorize_ws(websocket, code, token)
    if resolved is None:
        return None
    user_id, ttl_seconds = resolved
    ends = partial(_expire_after, ttl_seconds) if ttl_seconds is not None else None
    return code, user_id, ends


async def _authorize_ws(
    websocket: WebSocket, session_id: str, token: str | None
) -> tuple[str, float | None] | None:
    """Resolve ``(user_id, ttl_seconds)`` for a live-view WS, or close and return None.

    ``ttl_seconds`` is the token's remaining lifetime for a takeover connection, or
    ``None`` for a cookie session (no token deadline).
    """
    if token:
        try:
            claims: TakeoverTokenClaims = verify_takeover_token(token)
        except JWTError:
            log.warning(f"{LogTag.BROWSER} browser live view rejected invalid takeover token")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        if claims["session_id"] != session_id:
            log.warning(f"{LogTag.BROWSER} browser live view token session mismatch")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        return claims["user_id"], max(takeover_token_ttl_seconds(claims), 0.0)

    user = await get_current_user_ws(websocket)  # closes the socket on auth failure
    return user.user_id, None


async def _proxy_live_view(
    client_ws: WebSocket, host_ws_url: str, ends: _ConnectionEnd | None
) -> None:
    """Bridge the viewer's WebSocket to the host's live-view WebSocket both ways, until either closes or ends returns."""
    try:
        async with websockets.connect(host_ws_url, max_size=None) as host_ws:
            directions: list[Awaitable[None]] = [
                _pump_host_to_client(host_ws, client_ws),
                _pump_client_to_host(client_ws, host_ws),
            ]
            if ends is not None:
                directions.append(ends())
            await pump_until_first_close(*directions, sockets=(client_ws,))
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        log.warning(
            f"{LogTag.BROWSER} browser live view host unreachable", error_type=type(exc).__name__
        )
    finally:
        if client_ws.application_state is not WebSocketState.DISCONNECTED:
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
