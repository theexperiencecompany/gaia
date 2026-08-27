"""API-side client for the browser host — thin async wrapper over its JSON API.

The host owns the Chromium and enforces the concurrency cap; this client just
speaks to it. ``create_session`` returns the two websocket URLs the runner hands
to browser-use (``cdp_ws``) and to the live-view proxy (``live_ws``). A host that
is at capacity surfaces as :class:`BrowserConcurrencyLimit`; any transport
failure surfaces as :class:`BrowserUnavailableError` — the browser tool degrades
to a clean "not available" message rather than a raw stack trace.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from playwright.sync_api import StorageState

from app.config.settings import settings
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserUnavailableError,
)

# Context creation launches a page and may seed cookies; give it real headroom.
_CREATE_TIMEOUT_SECONDS = 30.0
_DEFAULT_TIMEOUT_SECONDS = 15.0
_AT_CAPACITY_STATUS = 429


@dataclass(frozen=True, slots=True)
class HostSession:
    """A live session on the host: the ids and websocket URLs the runner needs."""

    session_id: str
    cdp_ws: str
    live_ws: str
    context_id: str


@dataclass(frozen=True, slots=True)
class HostSessionInfo:
    """The host's view of a session: liveness, last activity, current page."""

    session_id: str
    live: bool
    last_activity_at: float
    url: str | None
    title: str | None


def _host_headers() -> dict[str, str]:
    """The shared-secret header the host requires on every REST call."""
    headers: dict[str, str] = {}
    key = settings.BROWSER_HOST_KEY
    if key:
        headers["X-Host-Key"] = key
    return headers


async def create_session(storage_state: StorageState | None) -> HostSession:
    """Create an isolated browser session, seeding ``storage_state`` when given."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.BROWSER_HOST_URL,
            timeout=_CREATE_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.post("/sessions", json={"storage_state": storage_state})
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {settings.BROWSER_HOST_URL}: {exc}"
        ) from exc

    if response.status_code == _AT_CAPACITY_STATUS:
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
    _raise_for_status(response)

    data = response.json()
    return HostSession(
        session_id=data["session_id"],
        cdp_ws=data["cdp_ws"],
        live_ws=data["live_ws"],
        context_id=data["context_id"],
    )


async def delete_session(session_id: str) -> StorageState:
    """Dispose the session and return its ``storage_state`` for persistence."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.BROWSER_HOST_URL,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.delete(f"/sessions/{session_id}")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {settings.BROWSER_HOST_URL}: {exc}"
        ) from exc

    _raise_for_status(response)
    storage_state: StorageState = response.json()["storage_state"]
    return storage_state


async def touch_session(session_id: str) -> None:
    """Reset the session's idle clock on the host (handoff keepalive)."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.BROWSER_HOST_URL,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.post(f"/sessions/{session_id}/touch")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {settings.BROWSER_HOST_URL}: {exc}"
        ) from exc

    _raise_for_status(response)


async def get_session(session_id: str) -> HostSessionInfo:
    """Fetch the host's current view of a session."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.BROWSER_HOST_URL,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
            headers=_host_headers(),
        ) as client:
            response = await client.get(f"/sessions/{session_id}")
    except httpx.HTTPError as exc:
        raise BrowserUnavailableError(
            f"Could not reach the browser host at {settings.BROWSER_HOST_URL}: {exc}"
        ) from exc

    _raise_for_status(response)
    data = response.json()
    return HostSessionInfo(
        session_id=data["session_id"],
        live=data["live"],
        last_activity_at=data["last_activity_at"],
        url=data.get("url"),
        title=data.get("title"),
    )


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise BrowserUnavailableError(
            f"Browser host returned {response.status_code} for {response.request.url}"
        ) from exc
