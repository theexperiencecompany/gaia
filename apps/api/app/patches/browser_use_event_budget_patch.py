"""Give Browser-Use's screenshot and state-read events a budget this engine can meet.

Measured on Obscura 2026-09-19: the first Page.captureScreenshot of a very long
page (de.wikipedia.org/wiki/Berlin, 85,000px, 14,000 nodes) took 24 to 35s, and
about 2s once rendered. Browser-Use allows a screenshot 15s and the state read
that contains it 30s, so the capture errored, was retried, and the user sat
through a minute of silence for a page that had loaded in 3.5s. A slow render
that completes costs less than a timeout plus a retry.

Only the defaults move: Browser-Use's own TIMEOUT_<Event> environment override
still wins, read through its own parser.

Pinned to browser-use==0.11.13; the import fails loudly if the events move.
"""

from collections.abc import Callable

from browser_use.browser import events
from browser_use.browser.events import (
    BrowserStateRequestEvent,
    NavigateToUrlEvent,
    ScreenshotEvent,
)
from bubus import BaseEvent

from app.config.settings import settings

# The state read carries the screenshot, so its budget has to sit above it.
_SCREENSHOT_SECONDS = 60.0
# Obscura lays out a 30k-node page in one ~50s pass that every CDP command queues
# behind, once per page; waiting it out beats failing the step twice and ending
# the run (measured 2026-09-22: 57-62s stalls on a long Wikipedia article).
_STATE_READ_SECONDS = 120.0
# Obscura answers Page.navigate only once the page has loaded or its own
# deadline has passed (OBSCURA_NAV_TIMEOUT_SECONDS); a shorter budget here
# interrupted the load and left the page without its scripts.
_NAVIGATE_SECONDS = float(settings.OBSCURA_NAV_TIMEOUT_SECONDS + 10)


def _budget(env_var: str, seconds: float) -> Callable[[], float | None]:
    return lambda: events._get_timeout(env_var, seconds)


def _set_default_budget(event: type[BaseEvent[object]], env_var: str, seconds: float) -> None:
    event.model_fields["event_timeout"].default_factory = _budget(env_var, seconds)
    event.model_rebuild(force=True)


def apply() -> None:
    """Raise the three default budgets, leaving the environment override in charge."""
    _set_default_budget(ScreenshotEvent, "TIMEOUT_ScreenshotEvent", _SCREENSHOT_SECONDS)
    _set_default_budget(
        BrowserStateRequestEvent, "TIMEOUT_BrowserStateRequestEvent", _STATE_READ_SECONDS
    )
    _set_default_budget(NavigateToUrlEvent, "TIMEOUT_NavigateToUrlEvent", _NAVIGATE_SECONDS)


apply()
