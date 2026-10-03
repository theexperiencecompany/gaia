"""The capability link a bot sends so its user can take over a browser handoff.

The link opens the web app's full-page live view ({FRONTEND_URL}/live/{code}),
which, like the chat card, dials this API's /live/{code} socket and answers the
handoff through /live/{code}/decision; the code is the authority.
"""

from __future__ import annotations

from app.config.settings import settings
from app.services.browser.live_code import mint_live_code


async def create_live_view_link(session_id: str, user_id: str, handoff_id: str) -> str:
    """Mint a short capability link a bot delivers so user_id can take over this handoff without a web login.

    The code maps to the session + owner in Redis, so no session id or token is
    in the URL."""
    code = await mint_live_code(session_id, user_id, handoff_id)
    return f"{settings.FRONTEND_URL}/live/{code}"
