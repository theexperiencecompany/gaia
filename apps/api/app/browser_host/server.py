"""The browser-host HTTP/WS service, one Chromium behind a small JSON API.

Endpoints (all internal; the port is never published):
  * POST   /sessions            create an isolated context (429 at capacity)
  * DELETE /sessions/{id}       dispose it, returning its storage_state
  * GET    /sessions/{id}/storage-state  its live storage_state, session kept
  * GET    /sessions/{id}       liveness + current page url/title
  * GET    /healthz             CDP responsiveness (503 when wedged)
  * WS     /cdp/{id}            the per-session CDP filtering proxy
  * WS     /live/{id}           the screencast + input live view

The single :class:ChromiumHost is created at import (no side effects) and
started/stopped by the app lifespan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import secrets

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from playwright.sync_api import StorageState
from pydantic import BaseModel

from app.browser_host.chromium import (
    AtCapacityError,
    CDPTimeoutError,
    ChromiumHost,
    EngineUnresponsiveError,
    SessionNotFoundError,
)
from app.browser_host.proxy import run_cdp_proxy
from app.browser_host.screencast import run_live_view
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import HostRequestFailure
from app.constants.log_tags import LogTag
from shared.py.wide_events import log, log_context

# WebSocket close code for "session unknown or dead" (application 4xxx range).
_WS_AUTH_FAILED = 4401
_WS_SESSION_GONE = 4404


class CreateSessionRequest(BaseModel):
    """Create-session payload: optional storage state to seed the new context."""

    storage_state: StorageState | None = None


class CreateSessionResponse(BaseModel):
    """Handle for a created context: CDP + live websocket URLs and the context id."""

    session_id: str
    cdp_ws: str
    live_ws: str
    context_id: str


class DeleteSessionResponse(BaseModel):
    """Result of disposing a context: the storage state to persist, or None."""

    storage_state: StorageState


class SessionStorageStateResponse(BaseModel):
    """A live context's cookies and localStorage, read without disposing it."""

    storage_state: StorageState


class AggregateResponse(BaseModel):
    """A sampled quantity's spread over the session so far."""

    count: int
    min: float
    max: float
    avg: float


class SessionMetricsResponse(BaseModel):
    """Live per-session profiling numbers. Aggregates are null until first sampled.

    ``rss_mb``/``cpu_percent`` describe the whole Chromium process tree, which
    every session on this host shares — see ``browser_host/metrics.py``.
    """

    session_lifetime_seconds: float
    navigation_count: int
    context_count: int
    page_count: int
    rss_mb: AggregateResponse | None = None
    cpu_percent: AggregateResponse | None = None
    navigation_ms: AggregateResponse | None = None


class SessionInfoResponse(BaseModel):
    """Live status for a session: activity timestamp, url, title, viewer state."""

    session_id: str
    live: bool
    last_activity_at: float
    url: str | None = None
    title: str | None = None
    metrics: SessionMetricsResponse


class TouchSessionResponse(BaseModel):
    """Acknowledgement that the session's activity clock was reset."""

    session_id: str


class HealthResponse(BaseModel):
    """Host health probe: process liveness plus a real CDP round-trip result."""

    ok: bool
    sessions: int
    chromium_up: bool
    cdp_responsive: bool


_host = ChromiumHost()


# --- host-key authentication ---------------------------------------------
# A rendered page can fetch() localhost, so every endpoint requires the shared key
# (REST: X-Host-Key header; WS: ?hk= query param). Production refuses to serve without one.


def _key_valid(candidate: str | None) -> bool:
    key: str | None = browser_host_settings.BROWSER_HOST_KEY
    if key is None:
        # No key configured: fine outside production (local dev tooling). In
        # production this host is unsafe to serve — fail loud instead of
        # silently running unauthenticated.
        return bool(browser_host_settings.ENV != "production")
    return bool(candidate) and secrets.compare_digest(candidate, key)


def _require_host_key(request: Request) -> None:
    if not _key_valid(request.headers.get("X-Host-Key")):
        log.fail(HostRequestFailure.INVALID_HOST_KEY)
        raise HTTPException(status_code=401, detail="missing or invalid host key")


def _session_not_found() -> HTTPException:
    log.fail(HostRequestFailure.SESSION_NOT_FOUND)
    return HTTPException(status_code=404, detail="session not found")


def _engine_unresponsive() -> HTTPException:
    log.fail(HostRequestFailure.ENGINE_UNRESPONSIVE)
    return HTTPException(status_code=503, detail="browser engine unresponsive")


_ALLOWED_WS_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ws_authorized(websocket: WebSocket) -> bool:
    if not _key_valid(websocket.query_params.get("hk")):
        return False
    # Defense-in-depth: server-side WS clients send no Origin; a rendered page
    # opening a raw socket would. Reject any non-loopback Origin even with a valid
    # key, so a leaked key alone is not enough. Rejections are logged.
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    try:
        netloc = (origin.split("://", 1)[1] if "://" in origin else origin).split("/")[0]
        host = netloc.rsplit(":", 1)[0]
    except (ValueError, IndexError) as exc:
        log.set(browser={"operation": "ws_origin_reject"})
        log.warning(
            f"{LogTag.BROWSER} live-view WS rejected: unparsable Origin",
            error_type=type(exc).__name__,
        )
        return False
    if host not in _ALLOWED_WS_ORIGIN_HOSTS:
        log.set(browser={"operation": "ws_origin_reject"})
        log.warning(f"{LogTag.BROWSER} live-view WS rejected: cross-origin Origin")
        return False
    return True


def _ws_url(path: str) -> str:
    """Absolute ws(s) URL for a host path, derived from BROWSER_HOST_URL."""
    # One replace per line so each carries its own suppression: the literals only
    # UPGRADE the configured scheme to its websocket form (https becomes wss); the
    # http arm applies only when the operator configured a plaintext host URL.
    base = browser_host_settings.BROWSER_HOST_URL.replace(
        "https://", "wss://", 1
    )  # NOSONAR python:S5332
    base = base.replace("http://", "ws://", 1)  # NOSONAR python:S5332
    url = f"{base.rstrip('/')}{path}"
    key = browser_host_settings.BROWSER_HOST_KEY
    if key:
        url = f"{url}?hk={key}" if "?" not in url else f"{url}&hk={key}"
    return url


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _host.start()
    try:
        yield
    finally:
        await _host.stop()


app = FastAPI(lifespan=_lifespan)

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
async def create_session(request: Request, payload: CreateSessionRequest) -> CreateSessionResponse:
    """Create a context on the host for one session; 429 at capacity."""
    _require_host_key(request)
    log.set(browser={"operation": "create"})
    try:
        session = await _host.create_context(payload.storage_state)
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
    return CreateSessionResponse(
        session_id=session.session_id,
        cdp_ws=_ws_url(f"/cdp/{session.session_id}"),
        live_ws=_ws_url(f"/live/{session.session_id}"),
        context_id=session.context_id,
    )


@app.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> DeleteSessionResponse:
    """Dispose the context and return the storage state to persist; 503 when its engine is down."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "delete"})
    try:
        storage_state = await _host.dispose_context(session_id)
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    except EngineUnresponsiveError as exc:
        raise _engine_unresponsive() from exc
    return DeleteSessionResponse(storage_state=storage_state)


@app.get("/sessions/{session_id}/storage-state")
async def get_session_storage_state(
    request: Request, session_id: str
) -> SessionStorageStateResponse:
    """Read the live context's storage state; 404 when the session is gone, 503 when its engine does not answer."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "storage_state"})
    try:
        storage_state = await _host.storage_state(session_id)
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    except (EngineUnresponsiveError, CDPTimeoutError) as exc:
        raise _engine_unresponsive() from exc
    return SessionStorageStateResponse(storage_state=storage_state)


@app.post("/sessions/{session_id}/touch")
async def touch_session(request: Request, session_id: str) -> TouchSessionResponse:
    """Reset the session's idle clock.

    The API calls this while a handoff is pending: the user may take minutes to
    come sign in, no CDP or live-view traffic flows in the meantime, and the idle
    reaper must not dispose the very browser the user was asked to return to.
    """
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "touch"})
    if _host.get(session_id) is None:
        raise _session_not_found()
    _host.touch(session_id)
    return TouchSessionResponse(session_id=session_id)


@app.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> SessionInfoResponse:
    """Fetch live session info; 404 when the session is gone, 503 when its engine does not answer."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "get"})
    try:
        info = await _host.session_info(session_id)
    except SessionNotFoundError as exc:
        raise _session_not_found() from exc
    except EngineUnresponsiveError as exc:
        raise _engine_unresponsive() from exc
    return SessionInfoResponse.model_validate(info)


@app.get("/healthz")
async def healthz(request: Request, response: Response) -> HealthResponse:
    """Report 503 when CDP is unresponsive so the orchestrator restarts the host."""
    _require_host_key(request)
    health = HealthResponse.model_validate(await _host.healthz())
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


@app.websocket("/cdp/{session_id}")
async def cdp_endpoint(websocket: WebSocket, session_id: str) -> None:
    """CDP websocket endpoint for one context, proxied through the filter."""
    async with _ws_wide_event("cdp_ws", session_id):
        if not _ws_authorized(websocket):
            log.fail(HostRequestFailure.INVALID_HOST_KEY)
            await websocket.close(code=_WS_AUTH_FAILED)
            return
        session = _host.get(session_id)
        if session is None or session.dead:
            log.fail(HostRequestFailure.SESSION_NOT_FOUND)
            await websocket.close(code=_WS_SESSION_GONE)
            return
        await websocket.accept()
        await run_cdp_proxy(_host, session, websocket)


@app.websocket("/live/{session_id}")
async def live_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Screencast + input websocket for one session's live view."""
    async with _ws_wide_event("live_ws", session_id):
        if not _ws_authorized(websocket):
            log.fail(HostRequestFailure.INVALID_HOST_KEY)
            await websocket.close(code=_WS_AUTH_FAILED)
            return
        session = _host.get(session_id)
        if session is None or session.dead:
            log.fail(HostRequestFailure.SESSION_NOT_FOUND)
            await websocket.close(code=_WS_SESSION_GONE)
            return
        await websocket.accept()
        await run_live_view(_host, session, websocket)
