"""Keep the step screenshot out of Browser-Use's state read on sessions that take their own.

Browser-Use asks for a screenshot inside every state read, in parallel with the
DOM build. Obscura serialises the two, so on a long page the DOM waited 4s for
the render (measured, de.wikipedia.org/wiki/Berlin) before the decision could
even start. A session registered here answers its state reads without one; the
Jev policy captures the frame itself while the decision is in flight.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from __future__ import annotations

import weakref

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary

# Keyed by id: a BrowserSession is a pydantic model, so it is not hashable; the
# weak reference drops the entry when the session is gone.
_deferred: dict[int, weakref.ref[BrowserSession]] = {}

_original_get_browser_state_summary = BrowserSession.get_browser_state_summary


def defer_screenshots_for(session: BrowserSession) -> None:
    """Answer this session's state reads without a screenshot from now on."""
    key = id(session)
    # Re-registering drops the old ref before it can fire, so the default is never read.
    _deferred[key] = weakref.ref(
        session,
        lambda _ref: _deferred.pop(key, None),  # pragma: no mutate
    )


def _is_deferred(session: BrowserSession) -> bool:
    ref = _deferred.get(id(session))
    return ref is not None and ref() is session


async def _get_browser_state_summary(
    self: BrowserSession,
    include_screenshot: bool = True,
    cached: bool = False,
    include_recent_events: bool = False,
) -> BrowserStateSummary:
    """Wrap the state read, dropping the screenshot for a session that takes its own."""
    if _is_deferred(self):
        include_screenshot = False
    return await _original_get_browser_state_summary(
        self,
        include_screenshot=include_screenshot,
        cached=cached,
        include_recent_events=include_recent_events,
    )


def apply() -> None:
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a coroutine
    # method that keeps mypy satisfied without an ignore.
    type.__setattr__(BrowserSession, "get_browser_state_summary", _get_browser_state_summary)


apply()
