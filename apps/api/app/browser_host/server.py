"""The browser-host HTTP/WS service: one engine behind a small JSON API.

Endpoints (all internal; the port is never published):
  * POST   /sessions                      create an isolated context (429 at capacity)
  * DELETE /sessions/{id}                 dispose it, returning its storage_state
  * GET    /sessions/{id}/storage-state   its live storage_state, session kept
  * POST   /sessions/{id}/lease           renew the lease its run holds on it
  * GET    /sessions/{id}                 liveness + current page url/title
  * GET    /healthz                       CDP responsiveness (503 when wedged)
  * WS     /cdp/{id}                      the per-session CDP filtering proxy
  * WS     /live/{id}                     the screencast + input live view

REST calls carry the shared host key; a websocket carries its session's own
token, so a leaked URL reaches that one session and nothing else.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial
import os
import secrets
import signal
from typing import TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import JSONResponse

from app.browser_host.cdp_mux import CdpCommandError, CdpConnectionClosed, CDPTimeoutError
from app.browser_host.host import (
    AtCapacityError,
    BrowserHost,
    EngineUnresponsiveError,
    HostSession,
    SessionNotFoundError,
)
from app.browser_host.proxy import run_cdp_proxy
from app.browser_host.screencast import run_live_view
from app.browser_host.wire import (
    CreatedSession,
    CreateSessionRequest,
    HealthResponse,
    SessionInfo,
    StorageStateResponse,
)
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import (
    BROWSER_HOST_DEADLINE_HEADER,
    BROWSER_HOST_KEY_HEADER,
    HostRequestFailure,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log, log_context

# WebSocket close codes in the application 4xxx range.
_WS_AUTH_FAILED = 4401
_WS_SESSION_GONE = 4404
_WS_TOKEN_PARAM = "token"  # nosec B105 -- the query parameter's name, not a credential
# Kept back from the caller's deadline for the answer to travel home in.
_DEADLINE_MARGIN_SECONDS = 1.0
_ALLOWED_WS_ORIGIN_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_T = TypeVar("_T")


class _DeadlineExceeded(RuntimeError):
    """Raised when a request outlives the deadline its caller sent."""


def _exit_for_restart() -> None:
    """Shut the process down so its orchestrator starts a fresh one; __main__ exits non-zero."""
    os.kill(os.getpid(), signal.SIGTERM)


_host = BrowserHost(on_fatal=_exit_for_restart)


def host_failed() -> bool:
    """Whether the host gave up because no engine could be brought back."""
    return _host.failed


# --- authentication -------------------------------------------------------
# A rendered page can fetch() localhost, so every REST endpoint requires the shared
# key and every websocket its session's token. Production refuses to serve keyless.


def _key_valid(candidate: str | None) -> bool:
    key = browser_host_settings.BROWSER_HOST_KEY
    if key is None:
        # Fine outside production (local dev tooling); in production an unkeyed
        # host is unsafe to serve, so every request fails loud instead.
        return browser_host_settings.ENV != "production"
    return candidate is not None and secrets.compare_digest(candidate, key)


def _require_host_key(request: Request) -> None:
    if not _key_valid(request.headers.get(BROWSER_HOST_KEY_HEADER)):
        log.fail(HostRequestFailure.INVALID_HOST_KEY)
        raise HTTPException(status_code=401, detail="missing or invalid host key")


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    """Reject a non-loopback Origin: server-side clients send none, a rendered page would."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    host = urlsplit(origin if "://" in origin else f"//{origin}").hostname
    if host not in _ALLOWED_WS_ORIGIN_HOSTS:
        log.warning(f"{LogTag.BROWSER} browser host WS rejected: cross-origin Origin")
        return False
    return True


def _ws_url(path: str, token: str) -> str:
    """Absolute ws(s) URL for a host path, derived from BROWSER_HOST_URL, carrying the session's token."""
    # Each replace only UPGRADES the configured scheme to its websocket form; the
    # http arm applies only when the operator configured a plaintext host URL.
    base = browser_host_settings.BROWSER_HOST_URL.replace(
        "https://", "wss://", 1
    )  # NOSONAR python:S5332
    base = base.replace("http://", "ws://", 1)  # NOSONAR python:S5332
    return f"{base.rstrip('/')}{path}?{_WS_TOKEN_PARAM}={token}"


async def _within_deadline(request: Request, work: Callable[[], Awaitable[_T]]) -> _T:
    """Run work inside the deadline the caller sent, so the host never works on for nobody."""
    header = request.headers.get(BROWSER_HOST_DEADLINE_HEADER)
    if header is None:
        return await work()
    budget = float(header) - _DEADLINE_MARGIN_SECONDS
    try:
        async with asyncio.timeout(budget) as scope:
            return await work()
    except TimeoutError as exc:
        if scope.expired():
            raise _DeadlineExceeded(f"deadline of {header}s passed") from exc
        raise


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _host.start()
    try:
        yield
    finally:
        await _host.stop()


app = FastAPI(lifespan=_lifespan)


_GONE = (404, HostRequestFailure.SESSION_NOT_FOUND, "session not found")
_UNRESPONSIVE = (503, HostRequestFailure.ENGINE_UNRESPONSIVE, "browser engine unresponsive")
# Every route's failures map here, in one table: a session that is gone (never
# was, ended, or its connection dropped) is a 404 wherever it is noticed.
_REFUSALS: dict[type[Exception], tuple[int, HostRequestFailure, str]] = {
    SessionNotFoundError: _GONE,
    CdpConnectionClosed: _GONE,
    EngineUnresponsiveError: _UNRESPONSIVE,
    CDPTimeoutError: _UNRESPONSIVE,
    CdpCommandError: (502, HostRequestFailure.ENGINE_REFUSED, "browser engine refused the request"),
    _DeadlineExceeded: (504, HostRequestFailure.DEADLINE_EXCEEDED, "the caller's deadline passed"),
}


async def _refuse(_request: Request, exc: Exception) -> Response:
    """Answer a failure from the table with its status, and log why on the request's event."""
    status, failure, detail = _REFUSALS[type(exc)]
    log.fail(failure, error_type=type(exc).__name__)
    return JSONResponse(status_code=status, content={"detail": detail})


for _refused_type in _REFUSALS:
    app.add_exception_handler(_refused_type, _refuse)

# Polled by the orchestrator; a degraded engine is logged by healthz itself.
_UNLOGGED_PATHS = frozenset({"/healthz"})


@app.middleware("http")
async def _request_wide_event(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One wide event per host request: its route, status, engine and, when refused, why."""
    if request.url.path in _UNLOGGED_PATHS:
        return await call_next(request)
    async with log_context(
        "browser_host_request",
        method=request.method,
        path=request.url.path,
        engine=browser_host_settings.BROWSER_ENGINE.value,
    ):
        response = await call_next(request)
        log.set(status_code=response.status_code)
        return response


@app.post("/sessions")
async def create_session(request: Request, payload: CreateSessionRequest) -> CreatedSession:
    """Create a context on the host for one session; 429 at capacity."""
    _require_host_key(request)
    log.set(browser={"operation": "create"})
    try:
        session = await _within_deadline(
            request, partial(_host.create_context, payload.storage_state)
        )
    except AtCapacityError as exc:
        admission = {
            "admission": exc.gate.value,
            "used_mb": exc.used_mb,
            "limit_mb": exc.limit_mb,
            "projected_mb": exc.projected_mb,
            "sessions": exc.sessions,
            "pending": exc.pending,
        }
        log.warning(f"{LogTag.BROWSER} browser host at capacity", browser=admission)
        log.fail(HostRequestFailure.AT_CAPACITY, browser=admission)
        raise HTTPException(status_code=429, detail="at_capacity") from exc
    return CreatedSession(
        session_id=session.session_id,
        cdp_ws=_ws_url(f"/cdp/{session.session_id}", session.token),
        live_ws=_ws_url(f"/live/{session.session_id}", session.token),
        engine=session.engine.kind,
    )


@app.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> StorageStateResponse:
    """Dispose the context and return the storage state to persist."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "delete"})
    storage_state = await _within_deadline(request, partial(_host.dispose_context, session_id))
    return StorageStateResponse(storage_state=storage_state)


@app.get("/sessions/{session_id}/storage-state")
async def get_session_storage_state(request: Request, session_id: str) -> StorageStateResponse:
    """Read the live context's storage state, leaving the session running."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "storage_state"})
    storage_state = await _within_deadline(request, partial(_host.storage_state, session_id))
    return StorageStateResponse(storage_state=storage_state)


@app.post("/sessions/{session_id}/lease", status_code=204)
async def renew_session_lease(request: Request, session_id: str) -> None:
    """Renew the lease the session's run holds; a session whose run stops renewing is disposed."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "lease"})
    _host.renew_lease(session_id)


@app.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> SessionInfo:
    """Fetch live session info; 404 when the session is gone, 503 when its engine does not answer."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "get"})
    return await _within_deadline(request, partial(_host.session_info, session_id))


@app.get("/healthz")
async def healthz(request: Request, response: Response) -> HealthResponse:
    """Report 503 when CDP is unresponsive so the orchestrator restarts the host."""
    _require_host_key(request)
    health = await _host.healthz()
    log.set(browser={"operation": "healthz", "session_id": ""})
    if not health.ok:
        response.status_code = 503
    return health


def _ws_wide_event(operation: str, session_id: str) -> AbstractAsyncContextManager[object]:
    """One wide event per websocket, emitted when it closes: which session, and why it was refused."""
    boundary: AbstractAsyncContextManager[object] = log_context(
        "browser_host_ws",
        engine=browser_host_settings.BROWSER_ENGINE.value,
        browser={"operation": operation, "session_id": session_id},
    )
    return boundary


async def _admit_ws(websocket: WebSocket, session_id: str) -> HostSession | None:
    """Return the live session this websocket's token opens, or close it and return None."""
    session = _host.get(session_id)
    if session is None:
        log.fail(HostRequestFailure.SESSION_NOT_FOUND)
        await websocket.close(code=_WS_SESSION_GONE)
        return None
    token = websocket.query_params.get(_WS_TOKEN_PARAM)
    if token is None or not secrets.compare_digest(token, session.token):
        log.fail(HostRequestFailure.INVALID_SESSION_TOKEN)
        await websocket.close(code=_WS_AUTH_FAILED)
        return None
    if not _ws_origin_allowed(websocket):
        log.fail(HostRequestFailure.INVALID_SESSION_TOKEN)
        await websocket.close(code=_WS_AUTH_FAILED)
        return None
    return session


@app.websocket("/cdp/{session_id}")
async def cdp_endpoint(websocket: WebSocket, session_id: str) -> None:
    """CDP websocket endpoint for one context, proxied through the filter."""
    async with _ws_wide_event("cdp_ws", session_id):
        session = await _admit_ws(websocket, session_id)
        if session is None:
            return
        await websocket.accept()
        await run_cdp_proxy(_host, session, websocket)


@app.websocket("/live/{session_id}")
async def live_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Screencast + input websocket for one session's live view."""
    async with _ws_wide_event("live_ws", session_id):
        session = await _admit_ws(websocket, session_id)
        if session is None:
            return
        await websocket.accept()
        await run_live_view(_host, session, websocket)
