"""Persistent Steel browser profiles, keyed by (user, domain).

A Steel profile persists cookies / localStorage / auth across sessions. We store
the profile id per user+domain so a repeat task on a site the user has already
logged into skips the login entirely: the session is created with the saved
``profile_id`` and Steel restores the authenticated context.

First-time auth is handled by the live-view handoff (the user logs in in the
live browser); we then persist the profile id here for next time.
"""

from urllib.parse import urlparse

from app.constants.log_tags import LogTag
from app.db.repositories.browser_profiles import browser_profile_repository
from shared.py.wide_events import log


def domain_of(url: str | None) -> str | None:
    """Lowercased hostname of a URL, used as the profile key. None if not a URL."""
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname
    except ValueError:
        return None
    return host.lower() if host else None


async def get_profile_id(user_id: str, domain: str | None) -> str | None:
    if not user_id or not domain:
        return None
    record = await browser_profile_repository.get_for_domain(user_id, domain)
    return record.steel_profile_id if record else None


async def save_profile_id(user_id: str, domain: str | None, steel_profile_id: str) -> None:
    """Persist the Steel profile id for this user+domain (upsert)."""
    if not user_id or not domain or not steel_profile_id:
        return
    await browser_profile_repository.upsert_steel_profile_id(user_id, domain, steel_profile_id)
    log.info(f"{LogTag.BROWSER} Saved browser profile", domain=domain)
