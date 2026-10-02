"""Addressing for the browser live view: the socket the chat card dials, and the page a bot link opens.

The live view's WebSocket is served through our API (never the browser host
directly), at a short root path: {BROWSER_LIVE_VIEW_BASE_URL or HOST}/live/{session_id}.
In prod the base is a friendly vhost (browser.heygaia.io) that reverse-proxies
to THIS api service. A logged-in web user watches it through the chat card's
canvas (with a ?t= token, since the host-only session cookie is not sent
cross-origin). A bot user, who has no web session, is sent a capability link to
the web app's full-page viewer ({FRONTEND_URL}/live/{code}), which dials the
same socket with the code and answers the handoff through /live/{code}/decision.
"""

from __future__ import annotations

from app.config.settings import settings
from app.services.browser.links import browser_link_base
from app.services.browser.live_code import mint_live_code

_LIVE_VIEW_PATH_TEMPLATE = "/live/{session_id}"


def live_view_url(session_id: str) -> str:
    """Return the public live-view URL for a session (the base the chat card connects to)."""
    return f"{browser_link_base()}{_LIVE_VIEW_PATH_TEMPLATE.format(session_id=session_id)}"


async def create_live_view_link(session_id: str, user_id: str, handoff_id: str) -> str:
    """Mint a short capability link a bot delivers so user_id can take over this handoff without a web login.

    The link opens the web app's live page, {FRONTEND_URL}/live/{code}; the
    code maps to the session + owner in Redis, so no session id or token is
    in the URL."""
    code = await mint_live_code(session_id, user_id, handoff_id)
    return f"{settings.FRONTEND_URL}/live/{code}"
