"""Resolve an email address to a person preview (name, photo, bio).

Powers link previews for email anchors in chat markdown. Resolution order:

1. Google Contacts (People API ``people:searchContacts`` through the user's
   Composio Gmail connection) — best source for people the user actually
   emails: real saved names and contact photos.
2. Gravatar public profile — covers addresses with a Gravatar account
   (name, avatar, bio) when the person is not in the user's contacts.

Results are cached per (user, email) in Redis: contact lookups are
user-specific, so they must never share the global URL-metadata cache.
"""

import asyncio
import hashlib

import httpx

from app.constants.email import (
    EMAIL_PROFILE_CACHE_KEY_TEMPLATE,
    EMAIL_PROFILE_CACHE_TTL_SECONDS,
    GOOGLE_CONTACTS_SOURCE_NAME,
    GRAVATAR_CONNECT_TIMEOUT_SECONDS,
    GRAVATAR_PROFILE_URL_TEMPLATE,
    GRAVATAR_SOURCE_NAME,
    GRAVATAR_TIMEOUT_SECONDS,
    PEOPLE_SEARCH_ENDPOINT,
    PEOPLE_SEARCH_READ_MASK,
)
from app.db.redis import get_cache, set_cache
from app.models.search_models import URLResponse
from app.services.composio.proxy_client import proxy_request
from app.utils.email_utils import normalize_email
from shared.py.wide_events import log

_GMAIL_TOOLKIT = "GMAIL"
_GRAVATAR_TIMEOUT = httpx.Timeout(
    GRAVATAR_TIMEOUT_SECONDS, connect=GRAVATAR_CONNECT_TIMEOUT_SECONDS
)


def _first_value(entries: list[dict], key: str) -> str | None:
    """First non-empty ``key`` across a People API field's entries."""
    return next((entry[key] for entry in entries if entry.get(key)), None)


async def _search_google_contacts(user_id: str, email: str) -> dict | None:
    """Look the email up in the user's Google contacts via the Composio proxy.

    Any failure (Gmail not connected, missing People scope, provider error)
    degrades silently to the next source — previews must never surface errors.
    """
    try:
        data = await proxy_request(
            user_id=user_id,
            toolkit=_GMAIL_TOOLKIT,
            method="GET",
            endpoint=PEOPLE_SEARCH_ENDPOINT,
            query={"query": email, "readMask": PEOPLE_SEARCH_READ_MASK},
        )
    except Exception as exc:
        log.debug(f"email_profile google contacts lookup failed: {exc}")
        return None

    for result in (data or {}).get("results", []):
        person = result.get("person", {})
        emails = {
            entry.get("value", "").strip().lower() for entry in person.get("emailAddresses", [])
        }
        if email not in emails:
            continue
        name = _first_value(person.get("names", []), "displayName")
        photo = _first_value(person.get("photos", []), "url")
        if not name and not photo:
            continue
        return {
            "title": name,
            "description": _first_value(person.get("biographies", []), "value"),
            "favicon": photo,
            "website_name": GOOGLE_CONTACTS_SOURCE_NAME,
        }
    return None


async def _fetch_gravatar_profile(email: str) -> dict | None:
    """Fetch the public Gravatar profile for an email, if one exists."""
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=_GRAVATAR_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                GRAVATAR_PROFILE_URL_TEMPLATE.format(email_hash=email_hash),
                headers={"User-Agent": "GAIA"},
            )
        if response.status_code != httpx.codes.OK:
            return None
        entries = response.json().get("entry", [])
    except (httpx.HTTPError, ValueError) as exc:
        log.debug(f"email_profile gravatar lookup failed: {exc}")
        return None

    if not entries:
        return None
    entry = entries[0]
    name = entry.get("displayName") or (entry.get("name") or {}).get("formatted")
    return {
        "title": name,
        "description": entry.get("aboutMe"),
        "favicon": entry.get("thumbnailUrl"),
        "website_name": GRAVATAR_SOURCE_NAME,
    }


async def fetch_email_profile(user_id: str, raw_value: str) -> URLResponse:
    """Resolve an email (or ``mailto:`` URL) to preview metadata for the user.

    Always returns a URLResponse; when no source knows the address, all
    fields except ``url`` are None and the frontend shows its fallback.
    """
    email = normalize_email(raw_value)
    if email is None:
        return URLResponse(url=raw_value)

    cache_key = EMAIL_PROFILE_CACHE_KEY_TEMPLATE.format(user_id=user_id, email=email)
    cached = await get_cache(cache_key)
    if cached:
        return URLResponse(**{**cached, "url": raw_value})

    profile = (
        await _search_google_contacts(user_id, email) or await _fetch_gravatar_profile(email) or {}
    )
    metadata = {
        "title": profile.get("title"),
        "description": profile.get("description"),
        "favicon": profile.get("favicon"),
        "website_name": profile.get("website_name"),
        "website_image": None,
    }
    await set_cache(cache_key, metadata, EMAIL_PROFILE_CACHE_TTL_SECONDS)
    return URLResponse(**{**metadata, "url": raw_value})


async def fetch_email_profiles(user_id: str, raw_values: list[str]) -> dict[str, URLResponse]:
    """Resolve several emails concurrently, keyed by the original input."""
    results = await asyncio.gather(
        *(fetch_email_profile(user_id, value) for value in raw_values),
        return_exceptions=True,
    )
    return {
        raw_value: result
        for raw_value, result in zip(raw_values, results)
        if isinstance(result, URLResponse)
    }
