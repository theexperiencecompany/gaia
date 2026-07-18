"""Persistent Steel browser profiles, keyed by (user, domain).

A Steel profile persists cookies / localStorage / auth across sessions. We store
the profile id per user+domain in Mongo so a repeat task on a site the user has
already logged into skips the login entirely: the session is created with the
saved ``profile_id`` and Steel restores the authenticated context.

First-time auth is handled by the live-view handoff (the user logs in in the
live browser); we then persist the profile id here for next time.
"""

from datetime import UTC, datetime
from urllib.parse import urlparse

from app.db.mongodb.collections import browser_profiles_collection
from shared.py.wide_events import log


def domain_of(url: str | None) -> str | None:
    """Registrable host of a URL, used as the profile key. None if not a URL."""
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
    record = await browser_profiles_collection.find_one(
        {"user_id": user_id, "domain": domain}, {"steel_profile_id": 1}
    )
    return record.get("steel_profile_id") if record else None


async def save_profile_id(user_id: str, domain: str | None, steel_profile_id: str) -> None:
    """Persist the Steel profile id for this user+domain (upsert)."""
    if not user_id or not domain or not steel_profile_id:
        return
    await browser_profiles_collection.update_one(
        {"user_id": user_id, "domain": domain},
        {
            "$set": {"steel_profile_id": steel_profile_id, "updated_at": datetime.now(UTC)},
            "$setOnInsert": {"created_at": datetime.now(UTC)},
        },
        upsert=True,
    )
    log.info(f"Saved browser profile for {domain}")
