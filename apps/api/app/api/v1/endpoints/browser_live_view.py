"""Root-mounted authenticated browser live view.

Served at ``/live/{session_id}`` (no ``/api/v1`` prefix) so it fronts a friendly
public vhost — e.g. ``https://browser.heygaia.io/live/{id}`` — that reverse-proxies
to THIS api service. The browser host is never exposed directly.

``GET`` serves a self-contained HTML canvas viewer (for a bot user opening the
tokened link); ``WEBSOCKET`` proxies frames + input between the viewer and the
host's ``WS /live/{id}``. Because the ``wos_session`` cookie is host-only, a
cross-origin viewer (the chat card on the friendly vhost) authenticates with a
short-lived ``?t=`` takeover token; a same-origin viewer may still use the
session cookie. Ownership is re-checked against the Redis registry on connect,
and a token connection is bounded to the token's remaining lifetime.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import HTMLResponse
from jose import JWTError
import websockets

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_current_user_ws
from app.browser_host.pumps import pump_until_first_close
from app.constants.log_tags import LogTag
from app.services.browser import registry
from app.services.browser.live_code import resolve_live_code
from app.services.browser.live_view import render_live_view_page
from app.services.browser.replay import render_replay_page, resolve_replay_code
from app.services.browser.takeover_token import (
    TakeoverTokenClaims,
    takeover_token_ttl_seconds,
    verify_takeover_token,
)
from shared.py.wide_events import log

router = APIRouter(tags=["Browser"])

# WebSocket close code for "session unknown or has no live stream" (app 4xxx range).
_WS_SESSION_GONE = 4404


@router.get("/replays/{code}")
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


@router.get("/live/{code}")
async def live_view_page(
    code: str,
    request: Request,
    t: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Standalone live-view page. ``code`` is a short capability code (the bot link)
    that resolves to a session + owner in Redis; failing that it is treated as a raw
    session id authorized by the ``?t=`` takeover token or a same-origin cookie (the
    web chat card)."""
    log.set(browser={"operation": "live_view_page"})
    session_id, user_id = await _resolve_target_page(code, request, t)
    owner = await registry.session_owner(session_id)
    if owner is None or owner != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session"
        )
    log.set(browser={"session_id": session_id})
    log.info(f"{LogTag.BROWSER} browser live view page served")
    return HTMLResponse(content=render_live_view_page(session_id))


@router.websocket("/live/{code}")
async def live_view_ws(
    websocket: WebSocket,
    code: str,
    t: Annotated[str | None, Query()] = None,
) -> None:
    """Proxy the authenticated live view: host frames out to the viewer, the
    viewer's mouse/key input back to the host. ``code`` is a short capability code
    (bot link) or a raw session id + ``?t=`` token / cookie (web card). A token
    connection is bounded to the token's remaining lifetime."""
    log.set(browser={"operation": "live_view_ws"})

    resolved = await _resolve_target_ws(websocket, code, t)
    if resolved is None:
        return  # already closed the socket with a policy-violation code
    session_id, user_id, ttl_seconds = resolved
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
    await _proxy_live_view(websocket, entry.live_ws, ttl_seconds)


async def _resolve_target_page(code: str, request: Request, token: str | None) -> tuple[str, str]:
    """``(session_id, user_id)`` for a GET page: a short capability code (the code is the
    secret), else ``code`` as a raw session id authorized by the ``?t=`` token or cookie."""
    record = await resolve_live_code(code)
    if record is not None:
        return record.session_id, record.user_id
    user_id = await _authorize_page(request, code, token)
    return code, user_id


async def _resolve_target_ws(
    websocket: WebSocket, code: str, token: str | None
) -> tuple[str, str, float | None] | None:
    """``(session_id, user_id, ttl_seconds)`` for a WS, or ``None`` (socket closed). The
    code path has no per-connection deadline — the session reaper bounds it; the token
    path keeps the token's remaining lifetime."""
    record = await resolve_live_code(code)
    if record is not None:
        return record.session_id, record.user_id, None
    resolved = await _authorize_ws(websocket, code, token)
    if resolved is None:
        return None
    user_id, ttl_seconds = resolved
    return code, user_id, ttl_seconds


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
        return claims["user_id"], max(takeover_token_ttl_seconds(claims), 0.0)

    user = await get_current_user_ws(websocket)  # closes the socket on auth failure
    user_id = user.get("user_id")
    if not user_id:
        return None
    return str(user_id), None


def _verify_scoped_token(token: str, session_id: str) -> TakeoverTokenClaims:
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
