"""Saved-login (browser profile) management for the settings UI.

Lists the domains a user has a saved browser login for, and forgets them. The
encrypted ``storage_state_blob`` is never exposed — only the domain + timestamp.
"""

from datetime import timedelta

from app.constants.browser import BROWSER_PROFILE_TTL_SECONDS
from app.db.repositories.browser_profiles import browser_profile_repository
from app.schemas.browser import BrowserLoginResponse
from app.services.browser.storage_persistence import forget_browser_logins


async def list_saved_logins(user_id: str) -> list[BrowserLoginResponse]:
    """Domains the user has a saved browser login for, most recently used first.

    Each carries ``expires_at`` (last use + the TTL) so the UI can count down to
    the Mongo TTL that auto-forgets unused session data.
    """
    docs = await browser_profile_repository.list_for_user(user_id, sort=[("updated_at", -1)])
    return [
        BrowserLoginResponse(
            domain=doc.domain,
            updated_at=doc.updated_at,
            expires_at=(
                doc.updated_at + timedelta(seconds=BROWSER_PROFILE_TTL_SECONDS)
                if doc.updated_at
                else None
            ),
            source=doc.source,
            source_browser=doc.source_browser,
            source_ip=doc.source_ip,
        )
        for doc in docs
    ]


async def forget_saved_login(user_id: str, domain: str | None = None) -> int:
    """Forget one domain's saved login, or all of them when ``domain`` is None.

    Returns the number of logins removed. Delegates to the storage-layer
    primitive so there is one canonical delete path (see
    ``storage_persistence.forget_browser_logins``).
    """
    return await forget_browser_logins(user_id, domain)
