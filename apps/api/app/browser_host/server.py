"""The browser-host HTTP/WS service — one Chromium behind a small JSON API.

Endpoints (all internal; the port is never published):
  * ``POST   /sessions``            create an isolated context (429 at capacity)
  * ``DELETE /sessions/{id}``       dispose it, returning its storage_state
  * ``GET    /sessions/{id}``       liveness + current page url/title
  * ``GET    /healthz``             process liveness
  * ``WS     /cdp/{id}``            the per-session CDP filtering proxy
  * ``WS     /live/{id}``           the screencast + input live view

The single :class:`ChromiumHost` is created at import (no side effects) and
started/stopped by the app lifespan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.browser_host.chromium import AtCapacityError, ChromiumHost, SessionNotFoundError
from app.browser_host.proxy import run_cdp_proxy
from app.browser_host.screencast import run_live_view
from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# WebSocket close code for "session unknown or dead" (application 4xxx range).
_WS_SESSION_GONE = 4404


class CreateSessionRequest(BaseModel):
    storage_state: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    cdp_ws: str
    live_ws: str
    context_id: str


class DeleteSessionResponse(BaseModel):
    storage_state: dict[str, Any]


class SessionInfoResponse(BaseModel):
    session_id: str
    live: bool
    last_activity_at: float
    url: str | None = None
    title: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    sessions: int
    chromium_up: bool


_host = ChromiumHost()


def _ws_url(path: str) -> str:
    """Absolute ws(s) URL for a host path, derived from ``BROWSER_HOST_URL``."""
    base = settings.BROWSER_HOST_URL.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{base.rstrip('/')}{path}"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _host.start()
    try:
        yield
    finally:
        await _host.stop()


app = FastAPI(lifespan=_lifespan)


@app.post("/sessions", response_model=None)
async def create_session(payload: CreateSessionRequest) -> CreateSessionResponse | JSONResponse:
    log.set(browser={"operation": "create"})
    try:
        session = await _host.create_context(payload.storage_state)
    except AtCapacityError:
        log.warning(f"{LogTag.BROWSER} browser host at capacity")
        return JSONResponse(status_code=429, content={"error": "at_capacity"})
    return CreateSessionResponse(
        session_id=session.session_id,
        cdp_ws=_ws_url(f"/cdp/{session.session_id}"),
        live_ws=_ws_url(f"/live/{session.session_id}"),
        context_id=session.context_id,
    )


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> DeleteSessionResponse:
    log.set(browser={"session_id": session_id, "operation": "delete"})
    try:
        storage_state = await _host.dispose_context(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return DeleteSessionResponse(storage_state=storage_state)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> SessionInfoResponse:
    log.set(browser={"session_id": session_id, "operation": "get"})
    try:
        info = await _host.session_info(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return SessionInfoResponse.model_validate(info)


@app.get("/healthz")
async def healthz() -> HealthResponse:
    return HealthResponse.model_validate(_host.healthz())


@app.websocket("/cdp/{session_id}")
async def cdp_endpoint(websocket: WebSocket, session_id: str) -> None:
    session = _host.get(session_id)
    if session is None or session.dead:
        await websocket.close(code=_WS_SESSION_GONE)
        return
    await websocket.accept()
    await run_cdp_proxy(_host, session, websocket)


@app.websocket("/live/{session_id}")
async def live_endpoint(websocket: WebSocket, session_id: str) -> None:
    session = _host.get(session_id)
    if session is None or session.dead:
        await websocket.close(code=_WS_SESSION_GONE)
        return
    await websocket.accept()
    await run_live_view(_host, session, websocket)
