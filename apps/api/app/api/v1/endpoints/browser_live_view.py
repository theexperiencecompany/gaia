"""Root-mounted authenticated browser live view.

Root-mounted (no /api/v1 prefix), so the recap and screenshot links can sit on a
friendly public vhost that reverse-proxies to THIS api service. The browser host
is never exposed directly.

WS /live/{id} proxies frames and input between a viewer (the chat card, or the
web app's full-page live view a bot link opens), dialled on the API's own
origin, and the host's WS /live/{id}; POST /live/{code}/decision answers the
handoff a bot link was sent for. A socket is opened by one of two authorities:
a bot link's short code, or a session id with the ?t= takeover token the web
card fetched. Ownership is re-checked against the Redis registry each time, and
a connection ends with its authority: a code's handoff settling, or a token's
lifetime.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from fastapi.responses import HTMLResponse, Response
from jose import JWTError
from starlette.websockets import WebSocketState
import websockets

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
    takeover_token_ttl_seconds,
    verify_takeover_token,
)
from shared.py.wide_events import log

router = APIRouter(tags=["Browser"])

# WebSocket close code for "session unknown or has no live stream" (app 4xxx range).
_WS_SESSION_GONE = 4404

#: What ends a live-view connection besides either side closing: its authority running out.
_ConnectionEnd = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _Target:
    """The session a viewer may watch and drive, its host stream, and what ends the connection."""

    session_id: str
    live_ws: str | None
    ends: _ConnectionEnd


@dataclass(frozen=True, slots=True)
class _Denied:
    """Why a viewer was turned away."""

    reason: str


async def _authorize(code: str, token: str | None) -> _Target | _Denied:
    """Resolve what opens a live view: a bot link's code, or a session id with a takeover token.

    Either way the session must still be registered to the user it names.
    """
    if token is None:
        record = await resolve_live_code(code)
        if record is None:
            return _Denied("Live view not found or expired")
        session_id, user_id = record.session_id, record.user_id
        ends: _ConnectionEnd = partial(live_code_ended, code)
    else:
        try:
            claims = verify_takeover_token(token)
        except JWTError:
            return _Denied("Invalid or expired link")
        if claims.session_id != code:
            return _Denied("Link does not match this session")
        session_id, user_id = code, claims.user_id
        ends = partial(asyncio.sleep, max(takeover_token_ttl_seconds(claims), 0.0))
    entry = await registry.get_session_entry(session_id)
    if entry is None or entry.owner != user_id:
        return _Denied("Not authorized for this session")
    return _Target(session_id=session_id, live_ws=entry.live_ws, ends=ends)


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
    """Standalone recap slideshow for a finished session: its code is the capability."""
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
    """Proxy the live view: host frames out to the viewer, its mouse/key input back to the host.

    The connection ends with whichever authority opened it.
    """
    log.set(browser={"operation": "live_view_ws"})
    target = await _authorize(code, t)
    if isinstance(target, _Denied):
        log.warning(f"{LogTag.BROWSER} browser live view refused", reason=target.reason)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    log.set(browser={"session_id": target.session_id})
    if not target.live_ws:
        log.warning(f"{LogTag.BROWSER} browser live view has no host stream")
        await websocket.close(code=_WS_SESSION_GONE)
        return

    await websocket.accept()
    log.info(f"{LogTag.BROWSER} browser live view proxy opened")
    await _proxy_live_view(websocket, target.live_ws, target.ends)


async def _proxy_live_view(client_ws: WebSocket, host_ws_url: str, ends: _ConnectionEnd) -> None:
    """Bridge the viewer's WebSocket to the host's live-view WebSocket both ways, until either closes or ends returns."""
    try:
        async with websockets.connect(host_ws_url, max_size=None) as host_ws:
            await pump_until_first_close(
                _pump_host_to_client(host_ws, client_ws),
                _pump_client_to_host(client_ws, host_ws),
                ends(),
                sockets=(client_ws,),
            )
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
