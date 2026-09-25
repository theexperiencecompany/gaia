"""Let Obscura finish loading a page before Browser-Use gives up on the navigation.

Chrome answers Page.navigate the moment the navigation is committed and loads
the page in the background; Browser-Use therefore wraps the call in a
hardcoded 20 s timeout. Obscura answers only once the page has loaded (or its
own OBSCURA_NAV_TIMEOUT has passed), so on a slow link that 20 s cut the load
short and the page was left without its scripts (measured 2026-09-22 on a
70 KB/s link: a jQuery page needed 64 s). Under Obscura the navigate call
gets the engine's own deadline plus a margin, and its return already means
"loaded", so Browser-Use's lifecycle polling is skipped.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

import asyncio

from browser_use.browser.session import BrowserSession

from app.config.settings import settings
from app.patches.obscura_sessions import on_obscura

_NAVIGATE_MARGIN_SECONDS = 10.0

_original_navigate_and_wait = BrowserSession._navigate_and_wait


async def _navigate_and_wait(
    self: BrowserSession,
    url: str,
    target_id: str,
    timeout: float | None = None,
    wait_until: str = "load",
) -> None:
    """Navigate with the engine's own deadline on Obscura; Browser-Use's path elsewhere."""
    if not on_obscura(self):
        await _original_navigate_and_wait(
            self, url, target_id, timeout=timeout, wait_until=wait_until
        )
        return
    cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)
    deadline = settings.OBSCURA_NAV_TIMEOUT_SECONDS + _NAVIGATE_MARGIN_SECONDS
    try:
        result = await asyncio.wait_for(
            cdp_session.cdp_client.send.Page.navigate(
                params={"url": url, "transitionType": "address_bar"},
                session_id=cdp_session.session_id,
            ),
            timeout=deadline,
        )
    except TimeoutError:
        raise RuntimeError(f"Page.navigate() timed out after {deadline}s for {url}") from None
    if result.get("errorText"):
        raise RuntimeError(f"Navigation failed: {result['errorText']}")


def apply() -> None:
    type.__setattr__(BrowserSession, "_navigate_and_wait", _navigate_and_wait)


apply()
