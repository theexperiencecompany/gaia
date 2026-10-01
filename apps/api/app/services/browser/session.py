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

from playwright.sync_api import StorageState

from app.constants.browser import (
    BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS,
    BROWSER_SESSION_LEASE_RENEW_SECONDS,
    BrowserEngine,
    EngineFailure,
)
from app.constants.log_tags import LogTag
from app.services.browser import host_client
from app.services.browser.exceptions import BrowserSessionGone, BrowserUnavailableError
from app.services.browser.live_view import live_view_url
from app.services.browser.registry import register_session, unregister_session
from app.services.browser.storage_persistence import (
    domain_of,
    load_storage_state,
    overlay_storage_state,
    save_storage_state,
    storage_state_for_host,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log


@dataclass(slots=True)
class BrowserHostSession:
    """Client-side handle to one browser-host context (CDP + live endpoints)."""

    session_id: str
    cdp_url: str
    live_view_url: str
    #: The browser host this context lives on: the primary engine's, or the
    #: fallback's after a switch.
    host_url: str
    #: The engine the host runs this context on, as the host reported it.
    engine: BrowserEngine
    #: The site the session opened on, where a sign-in on an unknown page is saved.
    start_domain: str | None = None
    #: The sites its returned state is saved under as a login on release: one it
    #: was seeded with a saved login for, or one the user said a sign-in finished on.
    login_domains: set[str] = field(default_factory=set)

    def mark_authenticated(self, url: str | None) -> None:
        """Record that the user said a sign-in finished here, on url's site, so the returned state is saved under it on release.

        The site signed in to, not the one the run started on: a run given no
        start URL once completed a login and saved nothing.
        """
        domain = self._site_of(url)
        if domain is not None:
            self.login_domains.add(domain)

    def forget_login(self, url: str | None) -> None:
        """Stop saving a login for url's site: the run is asking the user to sign in there, so none is held."""
        domain = self._site_of(url)
        if domain is not None:
            self.login_domains.discard(domain)

    def _site_of(self, url: str | None) -> str | None:
        return domain_of(url) or self.start_domain


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
    """Renew the host's lease on session for as long as this runs.

    The host disposes a session whose lease runs out, which is how a dead
    worker's browser is reclaimed; a failed renewal is logged and the next one,
    well inside the lease, tries again. Run under spawn_background_task, cancel to let go.
    """
    while True:
        await asyncio.sleep(BROWSER_SESSION_LEASE_RENEW_SECONDS)
        try:
            await host_client.renew_session_lease(session.session_id, session.host_url)
        except BrowserUnavailableError as exc:
            log.warning(
                f"{LogTag.BROWSER} Browser session lease renewal failed",
                error_type=type(exc).__name__,
                browser={"session_id": session.session_id, "operation": "lease_renewal"},
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
        host_url=host_url,
        engine=host.engine,
        start_domain=domain,
        login_domains=login_domains,
    )
    log.set(browser={"session_id": session.session_id, "operation": "create"})
    log.info(f"{LogTag.BROWSER} Browser session created")
    # The job holds the session's lease for its whole life, paused or not.
    lease = spawn_background_task(keep_session_alive(session))

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
        lease.cancel()
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
