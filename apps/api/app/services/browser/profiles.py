"""Saved-login (browser profile) management for the settings UI.

Lists the domains a user has a saved browser login for, and forgets them. The
encrypted ``storage_state_blob`` is never exposed — only the domain + timestamp.
"""

from app.db.repositories.browser_profiles import browser_profile_repository
from app.schemas.browser import BrowserLoginResponse


async def list_saved_logins(user_id: str) -> list[BrowserLoginResponse]:
    """Domains the user has a saved browser login for, most recently used first."""
    docs = await browser_profile_repository.list_for_user(user_id, sort=[("updated_at", -1)])
    return [BrowserLoginResponse(domain=doc.domain, updated_at=doc.updated_at) for doc in docs]


async def forget_saved_login(user_id: str, domain: str | None = None) -> int:
    """Forget one domain's saved login, or all of them when ``domain`` is None.

    Returns the number of logins removed.
    """
    return await browser_profile_repository.delete_for_user(user_id, domain)
