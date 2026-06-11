"""Resolve an email address to a person preview (name, photo, bio).

Powers link previews for email anchors in chat markdown. Sources, merged
field-wise in priority order (the same surface Gmail itself draws from):

1. Saved Google contacts (People API ``people:searchContacts`` via the
   user's Composio Gmail connection) — saved names and contact photos.
2. Other contacts (``otherContacts:search``) — anyone the user has ever
   emailed, with their actual Google profile photo even when unsaved.
3. Gravatar public profile — name, avatar, and bio for addresses with a
   Gravatar account.
4. Domain favicon — for company addresses with no personal photo, the
   organization's logo beats an empty circle.

Results are cached per (user, email) in Redis: contact lookups are
user-specific, so they must never share the global URL-metadata cache.
"""

import asyncio
import hashlib

import httpx

from app.constants.email import (
    DOMAIN_FAVICON_URL_TEMPLATE,
    EMAIL_PROFILE_CACHE_KEY_TEMPLATE,
    EMAIL_PROFILE_CACHE_TTL_SECONDS,
    FREEMAIL_DOMAINS,
    GOOGLE_CONTACTS_SOURCE_NAME,
    GRAVATAR_CONNECT_TIMEOUT_SECONDS,
    GRAVATAR_PROFILE_URL_TEMPLATE,
    GRAVATAR_SOURCE_NAME,
    GRAVATAR_TIMEOUT_SECONDS,
    OTHER_CONTACTS_READ_MASK,
    OTHER_CONTACTS_SEARCH_ENDPOINT,
    PEOPLE_GET_ENDPOINT_TEMPLATE,
    PEOPLE_SEARCH_ENDPOINT,
    PEOPLE_SEARCH_READ_MASK,
    PEOPLE_SEARCH_WARMUP_DELAY_SECONDS,
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


def _pick_photo(photos: list[dict]) -> str | None:
    """Best real photo: prefer the Google account (PROFILE) photo, skip monograms.

    ``default=true`` marks Google's generated letter avatars — returning None
    instead lets the merge fall through to a source with an actual photo.
    """
    real = [photo for photo in photos if photo.get("url") and not photo.get("default")]
    for photo in real:
        if photo.get("metadata", {}).get("source", {}).get("type") == "PROFILE":
            return photo["url"]
    return real[0]["url"] if real else None


def _person_to_profile(person: dict, email: str) -> dict | None:
    """Map a People API person to profile fields, if it matches the email."""
    emails = {entry.get("value", "").strip().lower() for entry in person.get("emailAddresses", [])}
    if email not in emails:
        return None
    name = _first_value(person.get("names", []), "displayName")
    photo = _pick_photo(person.get("photos", []))
    if not name and not photo:
        return None
    return {
        "title": name,
        "description": _first_value(person.get("biographies", []), "value"),
        "favicon": photo,
        "website_name": GOOGLE_CONTACTS_SOURCE_NAME,
    }


async def _people_search(user_id: str, endpoint: str, query: str, read_mask: str) -> dict | None:
    """One People API search call via the Composio Gmail proxy, or None.

    Any failure (Gmail not connected, missing scope, provider error) degrades
    silently to the next source — previews must never surface errors.
    """
    try:
        return await proxy_request(
            user_id=user_id,
            toolkit=_GMAIL_TOOLKIT,
            method="GET",
            endpoint=endpoint,
            query={"query": query, "readMask": read_mask},
        )
    except Exception as exc:
        log.debug(f"email_profile people search failed ({endpoint}): {exc}")
        return None


async def _search_google_people(
    user_id: str, endpoint: str, email: str, read_mask: str
) -> dict | None:
    """Search one People API surface for the email, with Google's warmup retry.

    Both contact-search endpoints return empty after a period of inactivity
    until a warmup (empty-query) request is sent; retry once after warming up.
    """
    data = await _people_search(user_id, endpoint, email, read_mask)
    if data is None:
        return None
    if not data.get("results"):
        await _people_search(user_id, endpoint, "", read_mask)
        await asyncio.sleep(PEOPLE_SEARCH_WARMUP_DELAY_SECONDS)
        data = await _people_search(user_id, endpoint, email, read_mask) or {}

    for result in data.get("results", []):
        person = result.get("person", {})
        profile = _person_to_profile(person, email)
        if profile is not None:
            profile["favicon"] = await _fetch_profile_photo(user_id, person) or profile.get(
                "favicon"
            )
            return profile
    return None


async def _fetch_profile_photo(user_id: str, person: dict) -> str | None:
    """Fetch a saved contact's full photo list and pick the real one.

    searchContacts only returns the contact-card photo, which for contacts
    without an explicit picture is a generated gradient/monogram that is NOT
    flagged ``default``. people.get on the same resource also returns
    PROFILE-source photos — the person's actual Google account picture —
    which _pick_photo prefers.
    """
    resource_name = person.get("resourceName") or ""
    if not resource_name.startswith("people/"):
        return None
    try:
        full = await proxy_request(
            user_id=user_id,
            toolkit=_GMAIL_TOOLKIT,
            method="GET",
            endpoint=PEOPLE_GET_ENDPOINT_TEMPLATE.format(resource_name=resource_name),
            query={"personFields": "photos"},
        )
    except Exception as exc:
        log.debug(f"email_profile people.get failed ({resource_name}): {exc}")
        return None
    return _pick_photo((full or {}).get("photos", []))


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


def _domain_favicon_profile(email: str) -> dict | None:
    """Company-domain favicon as a last-resort avatar (never for freemail)."""
    domain = email.split("@", 1)[1]
    if domain in FREEMAIL_DOMAINS:
        return None
    return {"favicon": DOMAIN_FAVICON_URL_TEMPLATE.format(domain=domain)}


def _merge_profiles(profiles: list[dict | None]) -> dict:
    """First non-empty value per field across sources, in priority order."""
    merged: dict = {}
    for profile in profiles:
        if not profile:
            continue
        for key, value in profile.items():
            if value and not merged.get(key):
                merged[key] = value
    return merged


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

    contacts, other_contacts, gravatar = await asyncio.gather(
        _search_google_people(user_id, PEOPLE_SEARCH_ENDPOINT, email, PEOPLE_SEARCH_READ_MASK),
        _search_google_people(
            user_id, OTHER_CONTACTS_SEARCH_ENDPOINT, email, OTHER_CONTACTS_READ_MASK
        ),
        _fetch_gravatar_profile(email),
    )
    profile = _merge_profiles([contacts, other_contacts, gravatar, _domain_favicon_profile(email)])
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
