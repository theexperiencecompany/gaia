"""Browser-host session lifecycle — create, live-view URL, guaranteed release.

The *infrastructure* layer: it talks to gaia-browser-host (via ``host_client``)
and knows nothing about Browser-Use or the agent. The session is always released
on exit — success, error, or cancellation — so no browser context is ever
orphaned. It seeds the user's saved login for the target domain before handing
the session to the agent, persists the returned login back when the session
ends, and exposes a live-view URL served from our own authenticated API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.constants.log_tags import LogTag
from app.services.browser import host_client
from app.services.browser.live_view import live_view_url
from app.services.browser.registry import register_session, unregister_session
from app.services.browser.storage_persistence import (
    domain_of,
    load_storage_state,
    save_storage_state,
)
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class BrowserHostSession:
    """Client-side handle to one browser-host context (CDP + live endpoints)."""

    session_id: str
    cdp_url: str
    live_view_url: str
    context_id: str


@asynccontextmanager
async def browser_session(
    *,
    user_id: str,
    start_url: str | None = None,
) -> AsyncIterator[BrowserHostSession]:
    """Create a browser-host session, yield it, and always release it.

    Seeds the user's saved ``storage_state`` for ``start_url``'s domain, registers
    session ownership for live-view auth, and on exit persists the returned
    ``storage_state`` and unregisters the session. Raises
    :class:`BrowserUnavailableError` when the host cannot create the session and
    :class:`BrowserConcurrencyLimit` when the host is at capacity.
    """
    domain = domain_of(start_url)
    storage_state = await load_storage_state(user_id, domain)

    host = await host_client.create_session(storage_state)
    session = BrowserHostSession(
        session_id=host.session_id,
        cdp_url=host.cdp_ws,
        live_view_url=live_view_url(host.session_id),
        context_id=host.context_id,
    )
    log.set(browser={"session_id": session.session_id, "operation": "create"})
    log.info(f"{LogTag.BROWSER} Browser session created")

    try:
        await register_session(session.session_id, user_id, live_ws=host.live_ws)
        yield session
    finally:
        try:
            returned_state = await host_client.delete_session(session.session_id)
            await save_storage_state(user_id, domain, returned_state)
            log.info(f"{LogTag.BROWSER} Browser session released")
        except Exception as exc:
            log.warning(
                f"{LogTag.BROWSER} Failed to release browser session",
                error_type=type(exc).__name__,
                browser={"session_id": session.session_id, "operation": "release_failed"},
            )
        await unregister_session(session.session_id)
