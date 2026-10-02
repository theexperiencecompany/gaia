"""Stop a page load the site never answers, as a person presses Stop.

While a top-level navigation waits for the server's first byte, Chrome answers
no Runtime.evaluate on the tab; Page.stopLoading still answers (2026-09-25).
But it stops every load in the tab: stopped mid head script, the shown page
never ran a script (2026-10-02). So a stall waits for the shown page to load
first; after that, the stop takes the navigation alone.

A form submission is never stopped: the server may already be acting on it.
Chrome names one in Page.frameRequestedNavigation before it starts (2026-10-02).

It also tells the agent when Browser-Use's capped readiness wait
(browser_use_page_ready_patch) went on before a page finished loading.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.constants.browser import (
    BROWSER_LOAD_STALL_SECONDS,
    BROWSER_LOAD_STALLED_NOTE,
    BROWSER_LOAD_STOP_TIMEOUT_SECONDS,
    BROWSER_LOAD_UNFINISHED_NOTE,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.events import BrowserConnectedEvent, NavigationCompleteEvent
    from browser_use.browser.session import BrowserSession
    from cdp_use.cdp.page.events import (
        FrameNavigatedEvent,
        FrameRequestedNavigationEvent,
        FrameStartedNavigatingEvent,
        FrameStoppedLoadingEvent,
        LoadEventFiredEvent,
    )
    from cdp_use.cdp.page.types import Frame

#: Navigation types that stay on the current document and never wait on a server.
_SAME_DOCUMENT = frozenset({"sameDocument", "historySameDocument"})
#: Why a page asks to navigate when it submits a form.
_FORM_SUBMISSIONS = frozenset({"formSubmissionGet", "formSubmissionPost"})
#: A history navigation that sends a form's POST again.
_RESTORE_WITH_POST = "restoreWithPost"


class StalledLoads:
    """Watches one Browser-Use session's tabs and stops any top-level load left unanswered, once the page shown has loaded."""

    def __init__(self, browser: BrowserSession) -> None:
        self._browser = browser
        #: Tab (main frame) id -> the timer that stops its pending load. A tab can carry
        #: several CDP sessions, and each reports the same navigation.
        self._timers: dict[str, asyncio.Task[None]] = {}
        #: Tab -> the URL its page asked to submit a form to, until that load ends.
        self._form_submissions: dict[str, str] = {}
        #: Tab -> the URL of its top-level load, until the tab reports it stopped loading.
        self._loading: dict[str, str] = {}
        #: Tab -> a load Browser-Use stopped waiting on before it finished.
        self._unfinished: dict[str, str] = {}
        #: Tab -> set once the document it shows has loaded; absent when that already happened.
        self._showing_loaded: dict[str, asyncio.Event] = {}
        self._stalled: list[str] = []

    async def attach(self, event: BrowserConnectedEvent) -> None:
        """Listen on the session's CDP connection; runs on every (re)connect."""
        del event
        client = self._browser.cdp_client
        client.register.Page.frameRequestedNavigation(self._on_requested)
        client.register.Page.frameStartedNavigating(self._on_started)
        client.register.Page.frameNavigated(self._on_committed)
        client.register.Page.frameStoppedLoading(self._on_stopped)
        client.register.Page.loadEventFired(self._on_loaded)

    def take(self) -> list[str]:
        """Return what stalled since the last call, as notes a model reads."""
        stalled, self._stalled = self._stalled, []
        return stalled

    def on_navigation_complete(self, event: NavigationCompleteEvent) -> None:
        """Note a navigation Browser-Use called done while its tab was still loading."""
        url = self._loading.get(event.target_id)
        if url is not None and event.error_message is None:
            self._unfinished[event.target_id] = url

    def take_unfinished(self) -> list[str]:
        """Return, as notes a model reads, every load Browser-Use stopped waiting on that is still going."""
        unfinished, self._unfinished = self._unfinished, {}
        return [BROWSER_LOAD_UNFINISHED_NOTE.format(url=url) for url in unfinished.values()]

    def close(self) -> None:
        """Drop every pending timer; the session is ending."""
        for tab in list(self._timers):
            self._cancel(tab)

    def _on_requested(self, event: FrameRequestedNavigationEvent, session_id: str | None) -> None:
        del session_id
        if event["reason"] in _FORM_SUBMISSIONS:
            self._form_submissions[event["frameId"]] = event["url"]
        else:
            self._form_submissions.pop(event["frameId"], None)

    def _on_started(self, event: FrameStartedNavigatingEvent, session_id: str | None) -> None:
        tab = event["frameId"]
        # Chrome gives a tab's main frame its target's id.
        if (
            session_id is None
            or event["navigationType"] in _SAME_DOCUMENT
            or self._browser.session_manager.get_target_id_from_session_id(session_id) != tab
        ):
            return
        self._cancel(tab)
        self._loading[tab] = event["url"]
        if (
            event["navigationType"] == _RESTORE_WITH_POST
            or self._form_submissions.get(tab) == event["url"]
        ):
            return
        self._timers[tab] = asyncio.create_task(self._stop_after(tab, session_id, event["url"]))

    def _on_committed(self, event: FrameNavigatedEvent, session_id: str | None) -> None:
        del session_id
        frame: Frame = event["frame"]
        # The frame shows a new document, which loads from here. A child frame's id
        # is never a tab's, so only a tab's own commit answers its load or holds its stop.
        self._showing_loaded[frame["id"]] = asyncio.Event()
        self._answered(frame["id"])

    def _on_loaded(self, event: LoadEventFiredEvent, session_id: str | None) -> None:
        del event
        if session_id is not None:
            self._shown_page_loaded(
                self._browser.session_manager.get_target_id_from_session_id(session_id)
            )

    def _on_stopped(self, event: FrameStoppedLoadingEvent, session_id: str | None) -> None:
        del session_id
        tab = event["frameId"]
        self._answered(tab)
        self._loading.pop(tab, None)
        self._unfinished.pop(tab, None)
        self._shown_page_loaded(tab)

    def _shown_page_loaded(self, tab: str | None) -> None:
        loaded = self._showing_loaded.pop(tab, None) if tab is not None else None
        if loaded is not None:
            loaded.set()

    def _answered(self, tab: str) -> None:
        self._form_submissions.pop(tab, None)
        self._cancel(tab)

    def _cancel(self, tab: str) -> None:
        timer = self._timers.pop(tab, None)
        if timer is not None:
            timer.cancel()

    async def _stop_after(self, tab: str, session_id: str, url: str) -> None:
        await asyncio.sleep(BROWSER_LOAD_STALL_SECONDS)
        showing = self._showing_loaded.get(tab)
        if showing is not None:
            # Stopping now would cut that page short too; a commit meanwhile cancels this wait.
            await showing.wait()
        # Its own entry, until now: only a cancel removes it sooner, and a cancel ends this wait.
        del self._timers[tab]
        log.warning(
            f"{LogTag.BROWSER} browser load stalled; stopping it",
            error_type="LoadStalled",
            browser={"stalled_url": url},
        )
        self._stalled.append(
            BROWSER_LOAD_STALLED_NOTE.format(url=url, seconds=BROWSER_LOAD_STALL_SECONDS)
        )
        try:
            await asyncio.wait_for(
                self._browser.cdp_client.send.Page.stopLoading(session_id=session_id),
                timeout=BROWSER_LOAD_STOP_TIMEOUT_SECONDS,
            )
        except (TimeoutError, RuntimeError) as exc:
            # Detached from every caller: the log is the only place this failure can surface.
            log.error(
                f"{LogTag.BROWSER} browser could not stop a stalled load",
                error_type=type(exc).__name__,
            )
