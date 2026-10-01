"""API-side client for the browser host, a thin async wrapper over its JSON API.

The host owns the engine and enforces admission; this client just speaks to it.
create_session returns the two websocket URLs the runner hands to browser-use,
cdp_ws and live_ws for the live-view proxy, and renew_session_lease keeps the
session alive while its run is. Every call sends its own deadline, so the host
finishes or gives up inside it. A host at capacity raises BrowserConcurrencyLimit;
a session the host no longer holds raises BrowserSessionGone; any other failure
raises BrowserUnavailableError, so the browser tool degrades to a clean "not
available" message rather than a raw stack trace.
"""

from __future__ import annotations

from http import HTTPMethod
from typing import TypedDict

import httpx
from playwright.sync_api import StorageState
from pydantic import BaseModel, ConfigDict

from app.config.settings import settings
from app.constants.browser import BROWSER_HOST_DEADLINE_HEADER, BROWSER_HOST_KEY_HEADER
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)

# Context creation opens a page and may seed a saved login; give it real headroom.
_CREATE_TIMEOUT_SECONDS = 30.0
_DEFAULT_TIMEOUT_SECONDS = 15.0
_AT_CAPACITY_STATUS = 429
_SESSION_GONE_STATUS = 404


class _StorageStateBody(TypedDict):
    """A session's storage_state as the host returns it, from a dispose or a live read."""

    storage_state: StorageState


class HostSession(BaseModel):
    """A live session on the host: its id and the websocket URLs the runner needs."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    cdp_ws: str
    live_ws: str


class HostSessionInfo(BaseModel):
    """The host's view of a session: liveness and its focused page."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    live: bool
    url: str | None = None
    title: str | None = None


async def _request(
    method: HTTPMethod,
    path: str,
    host_url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    json: object | None = None,
) -> httpx.Response:
    """Make one keyed request to the host, carrying the deadline the host must answer inside."""
    headers = {BROWSER_HOST_DEADLINE_HEADER: str(timeout)}
    if settings.BROWSER_HOST_KEY:
        headers[BROWSER_HOST_KEY_HEADER] = settings.BROWSER_HOST_KEY
    try:
        async with httpx.AsyncClient(base_url=host_url, timeout=timeout, headers=headers) as client:
            response = await client.request(method.value, path, json=json)
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {host_url}: {exc}"
        ) from exc
    if response.status_code == _AT_CAPACITY_STATUS:
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = f"Browser host returned {response.status_code} for {response.request.url}"
        if response.status_code == _SESSION_GONE_STATUS:
            raise BrowserSessionGone(message) from exc
        raise BrowserUnavailableError(message) from exc
    return response


async def create_session(storage_state: StorageState | None, host_url: str) -> HostSession:
    """Create an isolated browser session, seeding storage_state when given.

    The session lives on a lease: call renew_session_lease while the run is alive.
    """
    response = await _request(
        HTTPMethod.POST,
        "/sessions",
        host_url,
        timeout=_CREATE_TIMEOUT_SECONDS,
        json={"storage_state": storage_state},
    )
    return HostSession.model_validate(response.json())


async def delete_session(session_id: str, host_url: str) -> StorageState:
    """Dispose the session and return its storage_state for persistence."""
    response = await _request(HTTPMethod.DELETE, f"/sessions/{session_id}", host_url)
    body: _StorageStateBody = response.json()
    return body["storage_state"]


async def get_storage_state(session_id: str, host_url: str) -> StorageState:
    """Read a live session's storage_state, leaving the session running."""
    response = await _request(HTTPMethod.GET, f"/sessions/{session_id}/storage-state", host_url)
    body: _StorageStateBody = response.json()
    return body["storage_state"]


async def renew_session_lease(session_id: str, host_url: str) -> None:
    """Renew the lease the run holds on its session; the host disposes one left unrenewed.

    Call every BROWSER_SESSION_LEASE_RENEW_SECONDS for as long as the job is alive,
    paused for the user or the agent included. Raises BrowserSessionGone once it has ended.
    """
    await _request(HTTPMethod.POST, f"/sessions/{session_id}/lease", host_url)


async def get_session(
    session_id: str, host_url: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS
) -> HostSessionInfo:
    """Fetch the host's current view of a session."""
    response = await _request(HTTPMethod.GET, f"/sessions/{session_id}", host_url, timeout=timeout)
    return HostSessionInfo.model_validate(response.json())
