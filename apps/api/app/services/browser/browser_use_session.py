"""GaiaBrowserSession: Browser-Use's session as a run drives it, with GAIA's stealth, load wait and tab titles.

Each change is an override of one BrowserSession method, made on the run's own
session (no process-wide patch, nothing done at import). Pinned to
browser-use==0.11.13; an override whose method moved fails loudly at its super() call.
"""

from __future__ import annotations

import hashlib

from browser_use.browser.session import BrowserSession, CDPSession
from browser_use.browser.views import TabInfo
from cdp_use.cdp.runtime.commands import EvaluateReturns
from cdp_use.cdp.runtime.types import RemoteObject
from pydantic import PrivateAttr
from typing_extensions import override

from app.browser_host.stealth import build_stealth_script
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

#: A run with no user still presents one consistent device, never a random one per call.
_DEFAULT_SEED = 0x5EED
# Browser-Use waits 3 s same-domain, 8 s cross-domain for a load event that may never come;
# measured, that wait was 8.5 s of a 21 s time-to-first-action. StalledLoads tells the agent.
_MAX_READINESS_WAIT_SECONDS = 4.0


def seed_for_user(user_id: str | None) -> int:
    """Return user_id's stable 32-bit fingerprint seed: one person, one device; different people, different ones."""
    if not user_id:
        return _DEFAULT_SEED
    return int.from_bytes(hashlib.sha256(user_id.encode()).digest()[:4], "big")


class GaiaBrowserSession(BrowserSession):
    """The run's Browser-Use session on the host, sized to the screencast and fingerprinted for its user."""

    _fingerprint_seed: int = PrivateAttr(default=_DEFAULT_SEED)
    #: Targets that already carry the stealth script: it is registered once per target.
    _stealthed: set[str] = PrivateAttr(default_factory=set)

    def __init__(self, *, cdp_url: str, user_id: str | None) -> None:
        # Browser-Use sizes the page to a given viewport (at scale 1): the size the host screencasts.
        super().__init__(
            cdp_url=cdp_url,
            viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
        )
        self._fingerprint_seed = seed_for_user(user_id)

    @override
    async def get_or_create_cdp_session(
        self, target_id: str | None = None, focus: bool = True
    ) -> CDPSession:
        """Return the target's CDP session, its stealth script registered on first use.

        addScriptToEvaluateOnNewDocument is scoped to the CDP session that registers
        it, so a tab window.open made would be fingerprint-naked without its own.
        """
        cdp_session = await super().get_or_create_cdp_session(target_id=target_id, focus=focus)
        if cdp_session.target_id in self._stealthed:
            return cdp_session
        self._stealthed.add(cdp_session.target_id)
        try:
            await cdp_session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
                params={
                    "source": build_stealth_script(self._fingerprint_seed),
                    "runImmediately": True,
                },
                session_id=cdp_session.session_id,
            )
        except Exception as exc:
            # The page interaction goes on unstealthed; the next use of the target tries again.
            self._stealthed.discard(cdp_session.target_id)
            log.warning(
                f"{LogTag.BROWSER} Stealth script not registered",
                error_type=type(exc).__name__,
                target_id=cdp_session.target_id,
            )
        return cdp_session

    @override
    async def _navigate_and_wait(
        self, url: str, target_id: str, timeout: float | None = None, wait_until: str = "load"
    ) -> None:
        """Wait for a load at most _MAX_READINESS_WAIT_SECONDS unless the caller set its own wait."""
        await super()._navigate_and_wait(
            url,
            target_id,
            timeout=_MAX_READINESS_WAIT_SECONDS if timeout is None else timeout,
            wait_until=wait_until,
        )

    @override
    async def get_tabs(self) -> list[TabInfo]:
        """List the tabs, the agent's own titled from its document.

        Chrome's target label can still be the address after the page has its title:
        asked for example.com's title, the agent reported "example.com" (h_stall).
        """
        focused = self.agent_focus_target_id
        target = focused and self.session_manager and self.session_manager.get_target(focused)
        if target and (title := await self.document_title()):
            target.title = title
        return await super().get_tabs()

    async def document_title(self) -> str | None:
        """Return the focused page's document.title, or None when it has none or does not answer."""
        try:
            cdp = await self.get_or_create_cdp_session(focus=False)
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
