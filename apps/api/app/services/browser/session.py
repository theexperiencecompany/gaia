"""Browser-host session lifecycle — create, live-view URL, guaranteed release.

The *infrastructure* layer: it talks to gaia-browser-host (via ``host_client``)
and knows nothing about Browser-Use or the agent. The session is always released
on exit — success, error, or cancellation — so no browser context is ever
orphaned. It seeds the user's saved login for the target domain before handing
the session to the agent, persists the returned login back when the session
ends, and exposes a live-view URL served from our own authenticated API.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.constants.browser import (
    BROWSER_HANDOFF_KEEPALIVE_SECONDS,
    HANDOFF_AUTORESOLVE_POLL_SECONDS,
    HANDOFF_AUTORESOLVE_STABLE_POLLS,
    HandoffDecision,
)
from app.constants.log_tags import LogTag
from app.services.browser import host_client
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.handoff import resolve_handoff
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


async def keep_session_alive(session_id: str) -> None:
    """Periodically reset the host's idle clock while a handoff is pending.

    A paused session has no CDP or live-view traffic — and if the user hasn't
    opened the live view yet, no viewer either — so without this the idle
    reaper disposes the very browser the user was asked to come back to
    (idle TTL is shorter than the handoff timeout). Best-effort: a failed
    touch is logged, and the resume itself fails loud if the session is gone.
    Run under ``spawn_background_task`` and cancel when the handoff resolves.
    """
    while True:
        await asyncio.sleep(BROWSER_HANDOFF_KEEPALIVE_SECONDS)
        try:
            await host_client.touch_session(session_id)
        except BrowserUnavailableError as exc:
            log.warning(
                f"{LogTag.BROWSER} Browser handoff keepalive failed",
                error_type=type(exc).__name__,
                browser={"session_id": session_id, "operation": "handoff_keepalive"},
            )


def _navigated_away(start: str | None, current: str | None) -> bool:
    """Whether ``current`` is a different page than ``start`` — a sign-in that
    left the login URL. Compared by scheme+host+path (query/fragment ignored, so
    a login flow adding ``?return_to=`` on the same page is not a navigation)."""
    if not start or not current:
        return False
    a, b = urlsplit(start), urlsplit(current)
    return (a.scheme, a.netloc, a.path) != (b.scheme, b.netloc, b.path)


async def auto_resolve_handoff_on_navigation(
    handoff_id: str, session_id: str, user_id: str
) -> None:
    """Auto-complete a login handoff once the page navigates off the sign-in URL.

    Best-effort convenience only: the manual "I'm done" always races this through
    the same ``resolve_handoff`` (first write wins), so a missed detection just
    means the user taps the button. Debounced so a transient mid-login redirect
    doesn't resolve it early; if the login lands on a further step (2FA), the
    agent re-evaluates on resume and hands off again. Run under
    ``spawn_background_task`` and cancel when the handoff resolves.
    """
    try:
        start = (await host_client.get_session(session_id)).url
    except BrowserUnavailableError:
        return
    stable = 0
    while True:
        await asyncio.sleep(HANDOFF_AUTORESOLVE_POLL_SECONDS)
        try:
            current = (await host_client.get_session(session_id)).url
        except BrowserUnavailableError:
            return
        if not _navigated_away(start, current):
            stable = 0
            continue
        stable += 1
        if stable >= HANDOFF_AUTORESOLVE_STABLE_POLLS:
            await resolve_handoff(
                handoff_id,
                HandoffDecision.CONTINUE,
                user_id,
                "Signed in — resuming automatically.",
            )
            return


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
        registered = await register_session(session.session_id, user_id, live_ws=host.live_ws)
        if not registered:
            # Without the ownership entry the live-view link we hand the user can
            # never authorize; fail the session (release runs in the finally below)
            # instead of stranding them in a handoff they can't open.
            raise BrowserUnavailableError(
                "Could not register the browser session (storage unavailable)."
            )
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
