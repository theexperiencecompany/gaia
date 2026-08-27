"""Cap Browser-Use's page-readiness wait so a straggling page can't stall a step.

``_navigate_and_wait`` waits for a CDP lifecycle event with a hardcoded default
timeout (3s same-domain, 8s cross-domain). The wait already returns the moment
the event fires, so the full timeout is only ever paid on pages whose ``load``
event never arrives (an ad/analytics subresource that hangs) — exactly the
pages where waiting longer buys nothing: the agent re-reads page state every
step anyway, so acting on a near-ready page is safe. Measured on a real run,
this wait was the single biggest slice of time-to-first-action (8.5s of 21s).
Callers that pass an explicit ``timeout`` are untouched.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from browser_use.browser.session import BrowserSession

# Generous enough for any page that will ever fire its load event promptly,
# small enough that a hung subresource costs seconds, not a third of the
# time-to-first-action budget.
_MAX_READINESS_WAIT_SECONDS = 4.0

_original_navigate_and_wait = BrowserSession._navigate_and_wait


async def _navigate_and_wait(
    self: BrowserSession,
    url: str,
    target_id: str,
    timeout: float | None = None,
    wait_until: str = "load",
) -> None:
    """Wrap Browser-Use's navigate-and-wait to cap the default readiness timeout."""
    if timeout is None:
        timeout = _MAX_READINESS_WAIT_SECONDS
    await _original_navigate_and_wait(self, url, target_id, timeout=timeout, wait_until=wait_until)


def apply() -> None:
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a private
    # coroutine method that keeps mypy satisfied without an ignore.
    type.__setattr__(BrowserSession, "_navigate_and_wait", _navigate_and_wait)


apply()
