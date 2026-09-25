"""Turn a page's window.open into a same-tab navigation; Obscura opens nothing.

Measured 2026-09-19, raw port and through our host alike: window.open returns
null, the target list is unchanged and no Target event fires. A real click on
an anchor with target=_blank navigates the CURRENT tab instead, which is how
the engine already resolves a page-opened window.

Target.createTarget, attachToTarget and activateTarget all work, so
Browser-Use's own new-tab and switch-tab actions are fine. Only the page's own
popups are dead, leaving Jev clicking an unchanged page until its budget runs
out. So this follows the engine's own target=_blank resolution. The stub it
returns is inert, because the real window would let a page close Jev's tab.
Injection rides the stealth patch's per-target funnel, since an init script is
scoped to the session that registers it, and runs the shim on the open document
too: Obscura accepts runImmediately and ignores it, arming only the next load.
"""

from __future__ import annotations

from browser_use.browser.session import BrowserSession, CDPSession

from app.constants.log_tags import LogTag
from app.patches.obscura_sessions import on_obscura
from shared.py.wide_events import log

# A URL-less window.open builds a document to write into; navigating away from
# the page for that would lose it, so only a real destination is followed.
WINDOW_OPEN_SHIM = """(() => {
  const stub = {closed: false, focus() {}, blur() {}, close() {}, postMessage() {}};
  window.open = function (url) {
    if (!url) return null;
    try {
      const target = new URL(String(url), document.baseURI);
      if (target.protocol !== 'http:' && target.protocol !== 'https:') return null;
      window.location.href = target.href;
    } catch (err) {
      return null;
    }
    return stub;
  };
})();"""

_original_get_or_create_cdp_session = BrowserSession.get_or_create_cdp_session
_INJECTED_ATTR = "_gaia_window_open_target_ids"


async def _get_or_create_cdp_session(
    self: BrowserSession, target_id: str | None = None, focus: bool = True
) -> CDPSession:
    """Wrap Browser-Use's per-target session accessor to install the shim once per target."""
    cdp_session = await _original_get_or_create_cdp_session(self, target_id=target_id, focus=focus)
    if not on_obscura(self):
        return cdp_session

    injected: set[str] | None = getattr(self, _INJECTED_ATTR, None)
    if injected is None:
        injected = set()
        setattr(self, _INJECTED_ATTR, injected)

    if cdp_session.target_id not in injected:
        injected.add(cdp_session.target_id)
        try:
            await cdp_session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
                params={"source": WINDOW_OPEN_SHIM, "runImmediately": True},
                session_id=cdp_session.session_id,
            )
            # Measured: Obscura accepts runImmediately and ignores it, so the
            # page already open would keep the native window.open until it
            # navigated. Running the shim once covers it.
            await cdp_session.cdp_client.send.Runtime.evaluate(
                params={"expression": WINDOW_OPEN_SHIM},
                session_id=cdp_session.session_id,
            )
        except Exception as exc:
            injected.discard(cdp_session.target_id)
            log.warning(
                f"{LogTag.BROWSER} browser window.open shim injection failed",
                error_type=type(exc).__name__,
                browser={"target_id": cdp_session.target_id},
            )

    return cdp_session


def apply() -> None:
    """Install the window.open shim on every target Browser-Use touches."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(BrowserSession, "get_or_create_cdp_session", _get_or_create_cdp_session)


apply()
