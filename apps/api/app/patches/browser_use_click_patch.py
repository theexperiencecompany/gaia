"""Click through the element itself: a dispatched press is slow and aims blind.

Measured on Obscura 2026-09-19. Input.dispatchMouseEvent lands exactly and is
trusted, but a pressed button costs 450ms to 5.6s, and aiming at a rect centre
needs occlusion data from the DOM snapshot, whose geometry this engine
fabricates. So scroll-into-view and the click go in one
Runtime.callFunctionOn on the element handle, reporting the measured centre.
The cost is isTrusted, which a page gating on it will refuse.

The click is deferred by a zero-delay timer: Obscura loads the page a click
navigates to INSIDE the command that clicked (4.5s for a cross-origin link,
20ms deferred), so a slow page outlived Browser-Use's 15s click budget.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

from app.constants.log_tags import LogTag
from app.patches.obscura_sessions import on_obscura
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.dom.views import EnhancedDOMTreeNode

# One round trip: measure where the element really is, then press it there.
_CLICK_JS = """function() {
  const rect = this.getBoundingClientRect();
  if (!rect.width && !rect.height) return null;
  const element = this;
  setTimeout(() => element.click(), 0);
  return {click_x: rect.left + rect.width / 2, click_y: rect.top + rect.height / 2};
}"""

# The deferred click fires within 50ms (measured); wait past that so the next
# command sees its effect, and a navigation it starts reaches the watchdogs.
_SETTLE_SECONDS = 0.15

_original_click_element_node_impl = DefaultActionWatchdog._click_element_node_impl


def _needs_browser_use(node: EnhancedDOMTreeNode) -> bool:
    """Say whether this is a <select> or a file input, which Browser-Use rejects with its own message."""
    # tag_name is already lower-cased by the node; an attribute value keeps the page's case.
    return node.tag_name == "select" or (
        node.tag_name == "input" and str(node.attributes.get("type")).lower() == "file"
    )


async def _click_element_node_impl(
    self: DefaultActionWatchdog, element_node: EnhancedDOMTreeNode
) -> dict[str, Any] | None:
    """Click the element in the page and return the real centre Browser-Use records."""
    if _needs_browser_use(element_node) or not on_obscura(self.browser_session):
        return await _original_click_element_node_impl(self, element_node)

    cdp_session = await self.browser_session.cdp_client_for_node(element_node)
    backend_node_id = element_node.backend_node_id
    try:
        await cdp_session.cdp_client.send.DOM.scrollIntoViewIfNeeded(
            params={"backendNodeId": backend_node_id}, session_id=cdp_session.session_id
        )
    except Exception as exc:
        # Already-visible elements on some engines answer this with an error;
        # the click below still measures wherever the element ended up.
        log.debug(
            f"{LogTag.BROWSER} Could not scroll an element into view before clicking",
            error_type=type(exc).__name__,
        )

    resolved: dict[str, Any] = dict(
        await cdp_session.cdp_client.send.DOM.resolveNode(
            params={"backendNodeId": backend_node_id}, session_id=cdp_session.session_id
        )
    )
    object_id = (resolved.get("object") or {}).get("objectId")
    if not object_id:
        return await _original_click_element_node_impl(self, element_node)

    response: dict[str, Any] = dict(
        await cdp_session.cdp_client.send.Runtime.callFunctionOn(
            params={
                "functionDeclaration": _CLICK_JS,
                "objectId": object_id,
                "returnByValue": True,
            },
            session_id=cdp_session.session_id,
        )
    )
    point = (response.get("result") or {}).get("value")
    if response.get("exceptionDetails") or not isinstance(point, dict):
        return await _original_click_element_node_impl(self, element_node)

    await asyncio.sleep(_SETTLE_SECONDS)
    return {"click_x": float(point["click_x"]), "click_y": float(point["click_y"])}


def apply() -> None:
    """Route every element click through the page's own rect and click handler."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a private
    # coroutine method that keeps mypy satisfied without an ignore.
    type.__setattr__(DefaultActionWatchdog, "_click_element_node_impl", _click_element_node_impl)


apply()
