"""Scroll the page in JavaScript, because Obscura drops synthesized scroll gestures.

Measured on the Obscura host: Input.synthesizeScrollGesture returns cleanly and
window.scrollY never moves, so Browser-Use reports "Scrolled down 800px" on a
page that stayed put -- ten steps of an agent reading the same screen. That
call is the only scroll path in the watchdog, so there is nothing to fall back
to. Runtime works there, and window.scrollBy moves the page.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from __future__ import annotations

from typing import Any

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

from app.constants.log_tags import LogTag
from app.patches.obscura_sessions import on_obscura
from shared.py.wide_events import log

# Scroll the window, and when the window is not the scroller (an app whose
# content lives in an overflow container) the largest scrollable box on screen.
_SCROLL_JS = """(pixels) => {
  const moved = (read) => { const before = read(); return () => read() !== before; };
  const page = moved(() => window.scrollY);
  window.scrollBy(0, pixels);
  if (page()) return true;
  let best = null, area = 0;
  for (const el of document.querySelectorAll('*')) {
    if (el.scrollHeight <= el.clientHeight + 4) continue;
    const style = getComputedStyle(el);
    if (!/(auto|scroll)/.test(style.overflowY)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width * rect.height > area) { area = rect.width * rect.height; best = el; }
  }
  if (!best) return false;
  const box = moved(() => best.scrollTop);
  best.scrollTop += pixels;
  return box();
}"""


_original_scroll_with_cdp_gesture = DefaultActionWatchdog._scroll_with_cdp_gesture


async def _scroll_with_cdp_gesture(self: DefaultActionWatchdog, pixels: int) -> bool:
    """Scroll by pixels (positive is down) and report whether anything actually moved."""
    if not on_obscura(self.browser_session):
        return await _original_scroll_with_cdp_gesture(self, pixels)
    cdp_session = await self.browser_session.get_or_create_cdp_session()
    response: dict[str, Any] = dict(
        await cdp_session.cdp_client.send.Runtime.evaluate(
            params={
                "expression": f"({_SCROLL_JS})({pixels})",
                # A boolean result comes back by value with or without it.
                "returnByValue": True,  # pragma: no mutate
            },
            session_id=cdp_session.session_id,
        )
    )
    moved = bool((response.get("result") or {}).get("value"))
    if not moved:
        log.warning(
            f"{LogTag.BROWSER} Scroll left the page where it was",
            browser={"pixels": pixels},
        )
    return moved


def apply() -> None:
    """Route every page scroll through the page's own scrollBy."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a private
    # coroutine method that keeps mypy satisfied without an ignore.
    type.__setattr__(DefaultActionWatchdog, "_scroll_with_cdp_gesture", _scroll_with_cdp_gesture)


apply()
