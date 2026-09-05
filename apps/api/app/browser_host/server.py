"""The browser-host HTTP/WS service — one Chromium behind a small JSON API.

Endpoints (all internal; the port is never published):
  * ``POST   /sessions``            create an isolated context (429 at capacity)
  * ``DELETE /sessions/{id}``       dispose it, returning its storage_state
  * ``GET    /sessions/{id}``       liveness + current page url/title
  * ``GET    /healthz``             CDP responsiveness (503 when wedged)
  * ``WS     /cdp/{id}``            the per-session CDP filtering proxy
  * ``WS     /live/{id}``           the screencast + input live view

The single :class:`ChromiumHost` is created at import (no side effects) and
started/stopped by the app lifespan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from playwright.sync_api import StorageState
from pydantic import BaseModel

from app.browser_host.chromium import AtCapacityError, ChromiumHost, SessionNotFoundError
from app.browser_host.proxy import run_cdp_proxy
from app.browser_host.screencast import run_live_view
from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

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
# The host renders attacker-controlled pages in the SAME container, so a page
# can fetch() the control plane on localhost with no network boundary in the
# way. Every host endpoint therefore requires a shared secret the API/worker
# presents (REST: X-Host-Key header; WS: ?hk= query param on the URLs the API
# returns). The key lives only in API/worker config + env — page JS never sees
# it. In production the host refuses to serve at all without a configured key.


def _key_valid(candidate: str | None) -> bool:
    key: str | None = settings.BROWSER_HOST_KEY
    if key is None:
        # No key configured: fine outside production (local dev tooling). In
        # production this host is unsafe to serve — fail loud instead of
        # silently running unauthenticated.
        return bool(settings.ENV != "production")
    return bool(candidate) and secrets.compare_digest(candidate, key)


def _require_host_key(request: Request) -> None:
    if not _key_valid(request.headers.get("X-Host-Key")):
        raise HTTPException(status_code=401, detail="missing or invalid host key")


_ALLOWED_WS_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ws_authorized(websocket: WebSocket) -> bool:
    if not _key_valid(websocket.query_params.get("hk")):
        return False
    # Defense-in-depth: server-side WS clients (Browser-Use/Playwright, the API's
    # live-view upstream proxy) send no Origin; a rendered page connecting a raw
    # socket would. Reject any non-loopback Origin even with a valid key (the
    # page could only have the key if the API leaked it — this makes that leak
    # more survivable). Rejections are logged so they are observable.
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
    """Absolute ws(s) URL for a host path, derived from ``BROWSER_HOST_URL``."""
    # One replace per line so each carries its own suppression: these literals are
    # the search/replace pair that UPGRADES the configured scheme to its websocket
    # form. Nothing here opens a cleartext connection — https becomes wss, and the
    # http arm only applies when the operator configured a plaintext host URL.
    base = settings.BROWSER_HOST_URL.replace("https://", "wss://", 1)  # NOSONAR python:S5332
    base = base.replace("http://", "ws://", 1)  # NOSONAR python:S5332
    url = f"{base.rstrip('/')}{path}"
    key = settings.BROWSER_HOST_KEY
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


@app.post("/sessions")
async def create_session(request: Request, payload: CreateSessionRequest) -> CreateSessionResponse:
    """Create a context on the host for one session; 429 at capacity."""
    _require_host_key(request)
    log.set(browser={"operation": "create"})
    try:
        session = await _host.create_context(payload.storage_state)
    except AtCapacityError as exc:
        log.warning(f"{LogTag.BROWSER} browser host at capacity")
        raise HTTPException(status_code=429, detail="at_capacity") from exc
    return CreateSessionResponse(
        session_id=session.session_id,
        cdp_ws=_ws_url(f"/cdp/{session.session_id}"),
        live_ws=_ws_url(f"/live/{session.session_id}"),
        context_id=session.context_id,
    )


@app.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> DeleteSessionResponse:
    """Dispose the context and return the storage state to persist."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "delete"})
    try:
        storage_state = await _host.dispose_context(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return DeleteSessionResponse(storage_state=storage_state)


@app.post("/sessions/{session_id}/touch")
async def touch_session(request: Request, session_id: str) -> TouchSessionResponse:
    """Reset the session's idle clock. The API calls this while a handoff is
    pending: the user may take minutes to come sign in, no CDP or live-view
    traffic flows in the meantime, and the idle reaper must not dispose the
    very browser the user was asked to return to."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "touch"})
    if _host.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    _host.touch(session_id)
    return TouchSessionResponse(session_id=session_id)


@app.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> SessionInfoResponse:
    """Fetch live session info; 404 when the session is gone."""
    _require_host_key(request)
    log.set(browser={"session_id": session_id, "operation": "get"})
    try:
        info = await _host.session_info(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
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


@app.websocket("/cdp/{session_id}")
async def cdp_endpoint(websocket: WebSocket, session_id: str) -> None:
    """CDP websocket endpoint for one context, proxied through the filter."""
    if not _ws_authorized(websocket):
        await websocket.close(code=_WS_AUTH_FAILED)
        return
    log.set(browser={"operation": "cdp_ws", "session_id": session_id})
    session = _host.get(session_id)
    if session is None or session.dead:
        await websocket.close(code=_WS_SESSION_GONE)
        return
    await websocket.accept()
    await run_cdp_proxy(_host, session, websocket)


@app.websocket("/live/{session_id}")
async def live_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Screencast + input websocket for one session's live view."""
    if not _ws_authorized(websocket):
        await websocket.close(code=_WS_AUTH_FAILED)
        return
    log.set(browser={"operation": "live_ws", "session_id": session_id})
    session = _host.get(session_id)
    if session is None or session.dead:
        await websocket.close(code=_WS_SESSION_GONE)
        return
    await websocket.accept()
    await run_live_view(_host, session, websocket)
