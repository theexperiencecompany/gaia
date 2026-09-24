"""Stop a page load the site never answers, as a person presses Stop.

While a tab's top-level navigation waits for the server's first byte, Chrome
answers no Runtime.evaluate on that tab, so one silent site freezes every read
Jev and Browser-Use make. Page.stopLoading is still answered, releases the
queued reads at once, and leaves the tab on the page it was on (measured
2026-09-25 against a server that never responds, for typed, clicked and
cross-site navigations alike).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.constants.browser import BROWSER_LOAD_STALL_SECONDS, BROWSER_LOAD_STOP_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.events import BrowserConnectedEvent
    from browser_use.browser.session import BrowserSession
    from cdp_use.cdp.page.events import (
        FrameNavigatedEvent,
        FrameStartedNavigatingEvent,
        FrameStoppedLoadingEvent,
    )

#: Navigation types that stay on the current document and never wait on a server.
_SAME_DOCUMENT = frozenset({"sameDocument", "historySameDocument"})


class StalledLoads:
    """Watches one Browser-Use session's tabs and stops any top-level load left unanswered."""

    def __init__(self, browser: BrowserSession) -> None:
        self._browser = browser
        #: Tab (main frame) id -> the timer that stops its pending load. A tab can carry
        #: several CDP sessions, and each reports the same navigation.
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._stalled: list[str] = []

    async def attach(self, event: BrowserConnectedEvent) -> None:
        """Listen on the session's CDP connection; runs on every (re)connect."""
        del event
        client = self._browser.cdp_client
        client.register.Page.frameStartedNavigating(self._on_started)
        client.register.Page.frameNavigated(self._on_committed)
        client.register.Page.frameStoppedLoading(self._on_stopped)

    def take(self) -> list[str]:
        """Return what stalled since the last call, as notes a model reads."""
        stalled, self._stalled = self._stalled, []
        return stalled

    def close(self) -> None:
        """Drop every pending timer; the session is ending."""
        for tab in list(self._timers):
            self._cancel(tab)

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
        self._timers[tab] = asyncio.create_task(self._stop_after(tab, session_id, event["url"]))

    def _on_committed(self, event: FrameNavigatedEvent, session_id: str | None) -> None:
        del session_id
        if "parentId" not in event["frame"]:
            self._cancel(event["frame"]["id"])

    def _on_stopped(self, event: FrameStoppedLoadingEvent, session_id: str | None) -> None:
        del session_id
        self._cancel(event["frameId"])

    def _cancel(self, tab: str) -> None:
        timer = self._timers.pop(tab, None)
        if timer is not None:
            timer.cancel()

    async def _stop_after(self, tab: str, session_id: str, url: str) -> None:
        await asyncio.sleep(BROWSER_LOAD_STALL_SECONDS)
        self._timers.pop(tab, None)
        log.warning(f"{LogTag.BROWSER} browser load stalled; stopping it", error_type="LoadStalled")
        self._stalled.append(
            f"{url} sent nothing for {BROWSER_LOAD_STALL_SECONDS:.0f} s, so its loading was stopped; "
            "the tab is still on the page it was on."
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
