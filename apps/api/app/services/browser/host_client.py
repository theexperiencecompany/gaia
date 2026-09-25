"""API-side client for the browser host, a thin async wrapper over its JSON API.

The host owns the Chromium and enforces the concurrency cap; this client just
speaks to it. create_session returns the two websocket URLs the runner hands
to browser-use, cdp_ws and live_ws for the live-view proxy. A host at capacity
raises BrowserConcurrencyLimit; a session the host no longer holds raises
BrowserSessionGone; any transport failure raises BrowserUnavailableError, so
the browser tool degrades to a clean "not available" message rather than a raw
stack trace.
"""

from __future__ import annotations

from typing import TypedDict

import httpx
from playwright.sync_api import StorageState
from pydantic import BaseModel, ConfigDict

from app.config.settings import settings
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)

# Context creation launches a page and may seed cookies; give it real headroom.
_CREATE_TIMEOUT_SECONDS = 30.0
_DEFAULT_TIMEOUT_SECONDS = 15.0
_AT_CAPACITY_STATUS = 429
_SESSION_GONE_STATUS = 404


class _StorageStateBody(TypedDict):
    """A session's storage_state as the host returns it, from a dispose or a live read."""

    storage_state: StorageState


class HostSession(BaseModel):
    """A live session on the host: the ids and websocket URLs the runner needs."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    cdp_ws: str
    live_ws: str
    context_id: str


class HostSessionInfo(BaseModel):
    """The host's view of a session: liveness, last activity, current page."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    live: bool
    last_activity_at: float
    url: str | None = None
    title: str | None = None


def _host_headers() -> dict[str, str]:
    """Return the shared-secret header the host requires on every REST call."""
    headers: dict[str, str] = {}
    key = settings.BROWSER_HOST_KEY
    if key:
        headers["X-Host-Key"] = key
    return headers


async def create_session(storage_state: StorageState | None, host_url: str) -> HostSession:
    """Create an isolated browser session, seeding storage_state when given."""
    try:
        async with httpx.AsyncClient(
            base_url=host_url,
            timeout=_CREATE_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.post("/sessions", json={"storage_state": storage_state})
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc

    if response.status_code == _AT_CAPACITY_STATUS:
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
    _raise_for_status(response)

    return HostSession.model_validate(response.json())


async def delete_session(session_id: str, host_url: str) -> StorageState:
    """Dispose the session and return its storage_state for persistence."""
    try:
        async with httpx.AsyncClient(
            base_url=host_url,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.delete(f"/sessions/{session_id}")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc

    _raise_for_status(response)
    body: _StorageStateBody = response.json()
    return body["storage_state"]


async def get_storage_state(session_id: str, host_url: str) -> StorageState:
    """Read a live session's storage_state, leaving the session running."""
    try:
        async with httpx.AsyncClient(
            base_url=host_url,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.get(f"/sessions/{session_id}/storage-state")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc

    _raise_for_status(response)
    body: _StorageStateBody = response.json()
    return body["storage_state"]


async def touch_session(session_id: str, host_url: str) -> None:
    """Reset the session's idle clock on the host (handoff keepalive)."""
    try:
        async with httpx.AsyncClient(
            base_url=host_url,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.post(f"/sessions/{session_id}/touch")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc

    _raise_for_status(response)


async def get_session(
    session_id: str, host_url: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS
) -> HostSessionInfo:
    """Fetch the host's current view of a session."""
    try:
        async with httpx.AsyncClient(
            base_url=host_url,
            timeout=timeout,
            headers=_host_headers(),
        ) as client:
            response = await client.get(f"/sessions/{session_id}")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc

    _raise_for_status(response)
    return HostSessionInfo.model_validate(response.json())


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = f"Browser host returned {response.status_code} for {response.request.url}"
        if response.status_code == _SESSION_GONE_STATUS:
            raise BrowserSessionGone(message) from exc
        raise BrowserUnavailableError(message) from exc
