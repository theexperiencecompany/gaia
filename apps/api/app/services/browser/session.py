"""Browser-host session lifecycle: create, live-view URL, guaranteed release.

The infrastructure layer: it talks to gaia-browser-host through host_client
and knows nothing about the agent. The session is always released on exit
(success, error or cancellation) so no browser context is orphaned; the user's
saved login for the target domain is seeded before the agent gets the session
and persisted back when it ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from playwright.sync_api import StorageState

from app.constants.browser import (
    BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS,
    BROWSER_HANDOFF_KEEPALIVE_SECONDS,
    HANDOFF_AUTORESOLVE_POLL_SECONDS,
    HANDOFF_AUTORESOLVE_STABLE_POLLS,
    HANDOFF_AUTORESOLVED_NOTE,
    EngineFailure,
    HandoffDecision,
)
from app.constants.log_tags import LogTag
from app.services.browser import host_client
from app.services.browser.exceptions import BrowserSessionGone, BrowserUnavailableError
from app.services.browser.handoff import resolve_handoff
from app.services.browser.live_view import live_view_url
from app.services.browser.registry import register_session, unregister_session
from app.services.browser.storage_persistence import (
    domain_of,
    load_storage_state,
    overlay_storage_state,
    save_storage_state,
    storage_state_for_host,
)
from shared.py.wide_events import log


@dataclass(slots=True)
class BrowserHostSession:
    """Client-side handle to one browser-host context (CDP + live endpoints)."""

    session_id: str
    cdp_url: str
    live_view_url: str
    context_id: str
    #: The browser host this context lives on: the primary engine's, or the
    #: fallback's after a switch.
    host_url: str
    #: The site the session opened on, where a sign-in on an unknown page is saved.
    start_domain: str | None = None
    #: The sites its returned state is saved under as a login on release: one it
    #: was seeded with a saved login for, or one a sign-in completed on.
    login_domains: set[str] = field(default_factory=set)

    def mark_authenticated(self, url: str | None) -> None:
        """Record that a sign-in completed here, on url's site, so the returned state is saved under it on release.

        The site signed in to, not the one the run started on: a run given no
        start URL once completed a login and saved nothing.
        """
        domain = domain_of(url) or self.start_domain
        if domain is not None:
            self.login_domains.add(domain)


@dataclass(frozen=True, slots=True)
class LiveSessionState:
    """A live session's cookies and localStorage, and the session they were read from.

    What a run takes with it to another engine, so it opens there as the same
    signed-in browser. The source keeps its right to save its logins until the
    session opened with this state has saved them itself.
    """

    storage_state: StorageState
    source: BrowserHostSession


async def hand_over_state(session: BrowserHostSession) -> LiveSessionState:
    """Read session's live state for the session taking its run over; raises BrowserUnavailableError when its engine cannot give it."""
    storage_state = await host_client.get_storage_state(session.session_id, session.host_url)
    return LiveSessionState(storage_state=storage_state, source=session)


async def keep_session_alive(session: BrowserHostSession) -> None:
    """Periodically reset the host's idle clock while a handoff is pending.

    A paused session has no CDP or live-view traffic and the idle TTL is
    shorter than the handoff timeout, so without this the reaper disposes the
    browser. Best-effort: a failed touch is only logged. Run under
    spawn_background_task and cancel when the handoff resolves.
    """
    while True:
        await asyncio.sleep(BROWSER_HANDOFF_KEEPALIVE_SECONDS)
        try:
            await host_client.touch_session(session.session_id, session.host_url)
        except BrowserUnavailableError as exc:
            log.warning(
                f"{LogTag.BROWSER} Browser handoff keepalive failed",
                error_type=type(exc).__name__,
                browser={"session_id": session.session_id, "operation": "handoff_keepalive"},
            )


async def engine_failure(session: BrowserHostSession) -> EngineFailure | None:
    """Ask the host whether the engine under session still serves it; None when it does.

    The host is the one witness a run can trust here: Browser-Use reports a
    crashed, dropped or wedged engine only as step failures it ends the run on.
    """
    try:
        info = await host_client.get_session(
            session.session_id, session.host_url, timeout=BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS
        )
    except BrowserSessionGone:
        return EngineFailure.SESSION_GONE
    except BrowserUnavailableError:
        return EngineFailure.UNRESPONSIVE
    return None if info.live else EngineFailure.SESSION_GONE


# Path fragments that mean "still inside the auth flow": a login walks
# /login -> /two-factor -> /verify, each a real navigation, so navigation alone
# must not end the handoff or the agent wakes mid-2FA and hands off again.
_AUTH_PATH_MARKERS = (
    "login",
    "signin",
    "sign-in",
    "auth",
    "session",
    "two-factor",
    "two_factor",
    "2fa",
    "mfa",
    "otp",
    "verify",
    "verification",
    "challenge",
    "password",
    "consent",
    "oauth",
    "sso",
    "register",
    "signup",
    "sign-up",
    "forgot",
    "reset",
    "recover",
)


def _is_auth_url(url: str | None) -> bool:
    """Whether the URL still looks like part of a sign-in flow."""
    if not url:
        return False
    path = urlsplit(url).path.lower()
    return any(marker in path for marker in _AUTH_PATH_MARKERS)


def _navigated_away(start: str | None, current: str | None) -> bool:
    """Return whether the page moved to a different page that is no longer part of the auth flow.

    Compare scheme, host and path only, so a login adding a return_to query is
    not a navigation. Staying inside auth (2FA, OTP, verification) is not done.
    """
    # A missing URL has no host, so the host check below already says False.
    if not start or not current:  # pragma: no mutate
        return False
    a, b = urlsplit(start), urlsplit(current)
    if (a.scheme, a.netloc, a.path) == (b.scheme, b.netloc, b.path):
        return False
    # An identity provider on another host is the middle of the flow, not its end;
    # the flow is done when the page is back on the site that asked, off its auth paths.
    if b.netloc != a.netloc:
        return False
    return not _is_auth_url(current)


async def auto_resolve_handoff_on_navigation(
    handoff_id: str, session: BrowserHostSession, user_id: str
) -> None:
    """Auto-complete a login handoff once the page navigates off the sign-in URL.

    Best-effort: the manual "I'm done" races this through the same
    resolve_handoff (first write wins), so a missed detection only means the
    user taps the button. Debounced so a transient redirect does not resolve
    early. Run under spawn_background_task and cancel when the handoff resolves.
    """
    try:
        start = (await host_client.get_session(session.session_id, session.host_url)).url
    except BrowserUnavailableError:
        return
    stable = 0
    while True:
        await asyncio.sleep(HANDOFF_AUTORESOLVE_POLL_SECONDS)
        try:
            current = (await host_client.get_session(session.session_id, session.host_url)).url
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
                HANDOFF_AUTORESOLVED_NOTE,
            )
            return


@asynccontextmanager
async def browser_session(
    *,
    user_id: str,
    host_url: str,
    start_url: str | None = None,
    carried: LiveSessionState | None = None,
) -> AsyncIterator[BrowserHostSession]:
    """Create a browser-host session, yield it, and always release it.

    Seed the saved login for start_url's domain, under carried's live state when a run
    moves here; on exit save each of login_domains its own slice of the returned state. Raises
    BrowserUnavailableError, or BrowserConcurrencyLimit at capacity.
    """
    domain = domain_of(start_url)
    saved_login = await load_storage_state(user_id, domain)
    # A seeded run writes its state back so a rotated token is not lost.
    login_domains = {domain} if saved_login is not None and domain is not None else set()
    storage_state = saved_login
    if carried is not None:
        source = carried.source
        # The sites the source opened on or held a login for: a logout there can leave no cookie behind to show it.
        held = {site for site in (source.start_domain, *source.login_domains) if site}
        storage_state = overlay_storage_state(saved_login, carried.storage_state, held)
        login_domains |= source.login_domains

    host = await host_client.create_session(storage_state, host_url)
    session = BrowserHostSession(
        session_id=host.session_id,
        cdp_url=host.cdp_ws,
        live_view_url=live_view_url(host.session_id),
        context_id=host.context_id,
        host_url=host_url,
        start_domain=domain,
        login_domains=login_domains,
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
                "Could not register the browser session (storage unavailable)."  # pragma: no mutate
            )
        yield session
    finally:
        try:
            returned_state = await host_client.delete_session(session.session_id, host_url)
            # Saving every run turned the login store into an invisible preference
            # cache: one task's Deutsch cookie answered the next task in German.
            for login_domain in session.login_domains:
                await save_storage_state(
                    user_id, login_domain, storage_state_for_host(returned_state, login_domain)
                )
                if carried is not None:
                    # Saved newer than the source holds; its later release must not write over it.
                    carried.source.login_domains.discard(login_domain)
            log.info(f"{LogTag.BROWSER} Browser session released")
        except Exception as exc:
            log.warning(
                f"{LogTag.BROWSER} Failed to release browser session",
                error_type=type(exc).__name__,
                browser={"session_id": session.session_id, "operation": "release_failed"},
            )
        await unregister_session(session.session_id)
