"""Title the agent's tab from its document, which the agent sees each step.

The page state lists each tab as "url - title", the title being Chrome's
target label, and that label can still be the address after the page has its
title: asked for example.com's title, the agent reported "example.com", not
"Example Domain" (h_stall, 2026-10-02). get_tabs, which the state calls first,
now reads the focused page's document.title into its target, so the tab list
and the state's title (read from the same target next) both carry it. extract
reads the page's markdown, which has no <title>, so it uses the same read.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from collections.abc import Awaitable, Callable

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import TabInfo
from cdp_use.cdp.runtime.commands import EvaluateReturns
from cdp_use.cdp.runtime.types import RemoteObject

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_original_get_tabs: Callable[[BrowserSession], Awaitable[list[TabInfo]]] = BrowserSession.get_tabs


async def document_title(session: BrowserSession) -> str | None:
    """Return the focused page's document.title, or None when it has none or does not answer the read."""
    try:
        cdp = await session.get_or_create_cdp_session(focus=False)
        reply: EvaluateReturns = await cdp.cdp_client.send.Runtime.evaluate(
            params={"expression": "document.title", "returnByValue": True},
            session_id=cdp.session_id,
        )
    except (RuntimeError, TimeoutError, ValueError) as exc:
        # A page navigating away or detached answers no read; the label stands.
        log.warning(f"{LogTag.BROWSER} Page title not read", error_type=type(exc).__name__)
        return None
    result: RemoteObject = reply["result"]
    return str(result.get("value") or "").strip() or None


async def _get_tabs(self: BrowserSession) -> list[TabInfo]:
    """List the tabs, the agent's own titled from its document."""
    focused = self.agent_focus_target_id
    target = focused and self.session_manager and self.session_manager.get_target(focused)
    if target and (title := await document_title(self)):
        target.title = title
    return await _original_get_tabs(self)


def apply() -> None:
    """Route Browser-Use's tab list through the document's title."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a coroutine method.
    type.__setattr__(BrowserSession, "get_tabs", _get_tabs)
