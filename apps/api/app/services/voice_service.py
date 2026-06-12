"""Voice selection — curated catalog listing and per-user voice preference.

The catalog lives in ``app/constants/voices.py``. ElevenLabs is contacted only
to resolve preview sample URLs (cached for a day); listing and selection work
even when the upstream call fails.
"""

import asyncio
from typing import Any

from bson import ObjectId
import httpx

from app.config.settings import settings
from app.constants.cache import (
    ELEVENLABS_SHARED_VOICES_CACHE_KEY,
    ELEVENLABS_VOICES_CACHE_KEY,
    ONE_DAY_TTL,
)
from app.constants.voices import (
    ACCENT_TO_COUNTRY,
    DEFAULT_STARRED_VOICE_IDS,
    DEFAULT_VOICE_ID,
    LANGUAGE_NAMES,
    SELECTED_VOICE_FIELD,
    STARRED_VOICES_FIELD,
    VOICE_CATALOG,
    VOICE_IDS,
)
from app.db.mongodb.collections import users_collection
from app.db.redis import redis_cache
from app.decorators.caching import Cacheable
from app.schemas.voice_schemas import VoiceListResponse, VoiceOption
from app.utils.errors import AppError
from shared.py.wide_events import log

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_SHARED_VOICES_URL = "https://api.elevenlabs.io/v1/shared-voices"
ELEVENLABS_ADD_VOICE_URL = "https://api.elevenlabs.io/v1/voices/add/{owner_id}/{voice_id}"
ELEVENLABS_REQUEST_TIMEOUT_S = 10.0
# One page of featured library voices is plenty for the picker without
# ballooning the table; previews come straight off the library response.
SHARED_VOICES_PAGE_SIZE = 100


def _verified_language_codes(voice: dict[str, Any]) -> list[str]:
    """Ordered, deduped ISO codes from a voice's verified_languages.

    ElevenLabs repeats a language once per supporting model — collapse to one
    entry per language, preserving first-seen order.
    """
    seen: list[str] = []
    for entry in voice.get("verified_languages") or []:
        code = str(entry.get("language") or "").lower()
        if code and code not in seen:
            seen.append(code)
    return seen


def _language_names(codes: list[str], primary: str) -> list[str]:
    """Display names for language codes, with the primary language first."""
    names: list[str] = []
    for code in codes:
        name = LANGUAGE_NAMES.get(code, code.upper())
        if name not in names:
            names.append(name)
    if primary in names:
        names.remove(primary)
    return [primary, *names]


def _normalize_accent(raw: str) -> str:
    """Human label for an ElevenLabs accent string.

    ElevenLabs tags accent-neutral voices as "standard" — render those as
    International rather than a meaningless "Standard" country.
    """
    accent = raw.strip().lower()
    if not accent or accent == "standard":
        return "International"
    return accent.title()


@Cacheable(ttl=ONE_DAY_TTL, key_pattern=ELEVENLABS_VOICES_CACHE_KEY)
async def _fetch_elevenlabs_voices() -> list[dict[str, Any]]:
    """Fetch the account's voices (trimmed) from the ElevenLabs voices API.

    Raises on any upstream failure so a transient error is never cached as an
    empty list for the full TTL — only successful responses are stored.
    """
    async with httpx.AsyncClient(timeout=ELEVENLABS_REQUEST_TIMEOUT_S) as client:
        resp = await client.get(
            ELEVENLABS_VOICES_URL,
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY or ""},
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

    return [
        {
            "voice_id": voice["voice_id"],
            "name": voice.get("name") or "",
            "preview_url": voice.get("preview_url"),
            "labels": voice.get("labels") or {},
            "language_codes": _verified_language_codes(voice),
        }
        for voice in payload.get("voices", [])
        if isinstance(voice.get("voice_id"), str)
    ]


async def get_elevenlabs_voices() -> list[dict[str, Any]]:
    """Resolve account voices, degrading to an empty list when unavailable.

    The curated catalog still lists without samples or account extras when the
    API key is missing or ElevenLabs is unreachable.
    """
    if not settings.ELEVENLABS_API_KEY:
        return []
    try:
        return await _fetch_elevenlabs_voices()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("Failed to fetch ElevenLabs voices", error=str(e))
        return []


@Cacheable(ttl=ONE_DAY_TTL, key_pattern=ELEVENLABS_SHARED_VOICES_CACHE_KEY)
async def _fetch_shared_voices() -> list[dict[str, Any]]:
    """Fetch featured shared-library voices (trimmed) from ElevenLabs.

    Raises on any upstream failure so a transient error is never cached as an
    empty list for the full TTL — only successful responses are stored.
    """
    async with httpx.AsyncClient(timeout=ELEVENLABS_REQUEST_TIMEOUT_S) as client:
        resp = await client.get(
            ELEVENLABS_SHARED_VOICES_URL,
            params={"page_size": SHARED_VOICES_PAGE_SIZE},
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY or ""},
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

    return [
        {
            "voice_id": voice["voice_id"],
            "name": voice.get("name") or "",
            "preview_url": voice.get("preview_url"),
            "public_owner_id": voice.get("public_owner_id"),
            "gender": voice.get("gender") or "",
            "accent": voice.get("accent") or "",
            "language": voice.get("language") or "",
            "descriptive": voice.get("descriptive") or "",
            "use_case": voice.get("use_case") or "",
            "language_codes": _verified_language_codes(voice),
        }
        for voice in payload.get("voices", [])
        if isinstance(voice.get("voice_id"), str) and voice.get("public_owner_id")
    ]


async def get_shared_voices() -> list[dict[str, Any]]:
    """Resolve shared-library voices, degrading to an empty list when unavailable."""
    if not settings.ELEVENLABS_API_KEY:
        return []
    try:
        return await _fetch_shared_voices()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("Failed to fetch ElevenLabs shared voices", error=str(e))
        return []


def _split_display_name(raw_name: str) -> tuple[str, str]:
    """Split ElevenLabs' "Name - Short description" naming into columns."""
    name, _, blurb = raw_name.partition(" - ")
    return name.strip() or raw_name, blurb.strip()


def _build_voice_option(
    voice: dict[str, Any],
    *,
    accent: str,
    gender: str,
    descriptive: str,
    use_case: str,
    language_code: str,
    source: str,
    fallback_description: str,
) -> VoiceOption:
    """Shape a non-catalog ElevenLabs voice into a catalog-compatible option."""
    name, blurb = _split_display_name(voice["name"])
    accent_label = _normalize_accent(accent)
    primary = LANGUAGE_NAMES.get(language_code, language_code.upper() or "English")
    descriptive = descriptive.replace("_", " ")
    use_case = use_case.replace("_", " ")
    return VoiceOption(
        voice_id=voice["voice_id"],
        name=name,
        language=primary,
        accent=accent_label,
        country_code=ACCENT_TO_COUNTRY.get(accent_label.lower(), ""),
        gender=gender.strip().title() or "Neutral",
        description=blurb or descriptive.title() or use_case.title() or fallback_description,
        preview_url=voice.get("preview_url"),
        source=source,
        languages=_language_names(voice.get("language_codes") or [], primary),
    )


def _map_account_voice(voice: dict[str, Any]) -> VoiceOption:
    """Shape a non-catalog account voice (metadata in ``labels``) into an option."""
    labels: dict[str, Any] = voice["labels"]
    return _build_voice_option(
        voice,
        accent=str(labels.get("accent") or ""),
        gender=str(labels.get("gender") or ""),
        descriptive=str(labels.get("descriptive") or ""),
        use_case=str(labels.get("use_case") or ""),
        language_code=str(labels.get("language") or ""),
        source="account",
        fallback_description="Account voice",
    )


def _map_shared_voice(voice: dict[str, Any]) -> VoiceOption:
    """Shape a shared-library voice (metadata at the top level) into an option."""
    return _build_voice_option(
        voice,
        accent=voice["accent"],
        gender=voice["gender"],
        descriptive=voice["descriptive"],
        use_case=voice["use_case"],
        language_code=voice["language"],
        source="library",
        fallback_description="Community voice",
    )


async def _known_voice_ids() -> set[str]:
    """All selectable voice ids.

    Only voices that exist on the ElevenLabs account are selectable — a
    catalog entry the account no longer carries would fail TTS. The catalog
    is the fallback when the account list is unavailable.
    """
    account = await get_elevenlabs_voices()
    if account:
        return {v["voice_id"] for v in account}
    return set(VOICE_IDS)


async def get_user_voice(user_id: str) -> str | None:
    """Return the user's selected voice id, falling back to the product default.

    Plain Mongo read — deliberately NO availability validation here. This runs
    in the /token critical path (every session start), and validation would
    drag a (cached, but worst-case live) ElevenLabs lookup into it. Selections
    are validated once at ``set_user_voice`` time instead.
    """
    doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {SELECTED_VOICE_FIELD: 1})
    voice_id = (doc or {}).get(SELECTED_VOICE_FIELD)
    if isinstance(voice_id, str) and voice_id:
        return voice_id
    return DEFAULT_VOICE_ID


async def list_voices(user_id: str) -> VoiceListResponse:
    """Return the curated catalog plus account voices, with the user's selection.

    Curated entries come first (stable copy, hand-written descriptions); any
    other voice on the ElevenLabs account — premades we did not curate and the
    account's own cloned voices — is appended with metadata derived from its
    labels. Catalog entries the account no longer carries are dropped: they
    would have no preview and, worse, fail TTS if selected.
    """
    account, shared, selected, starred = await asyncio.gather(
        get_elevenlabs_voices(),
        get_shared_voices(),
        get_user_voice(user_id),
        get_starred_voice_ids(user_id),
    )
    by_id = {v["voice_id"]: v for v in account}
    voices: list[VoiceOption] = []
    for entry in VOICE_CATALOG:
        fetched = by_id.get(entry["voice_id"])
        if account and not fetched:
            continue
        voices.append(
            VoiceOption(
                **entry,
                preview_url=(fetched or {}).get("preview_url"),
                languages=_language_names(
                    (fetched or {}).get("language_codes") or [], entry["language"]
                ),
            )
        )
    voices.extend(
        _map_account_voice(voice) for voice in account if voice["voice_id"] not in VOICE_IDS
    )
    listed = {v.voice_id for v in voices}
    voices.extend(_map_shared_voice(voice) for voice in shared if voice["voice_id"] not in listed)

    starred_set = set(starred)
    for voice in voices:
        voice.starred = voice.voice_id in starred_set
    # Starred voices float to the top; order is otherwise preserved
    # (curated catalog, then account, then library).
    voices.sort(key=lambda v: not v.starred)
    return VoiceListResponse(voices=voices, selected_voice_id=selected)


async def get_starred_voice_ids(user_id: str) -> list[str]:
    """The user's starred voice ids, defaulting to the product starter set."""
    doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {STARRED_VOICES_FIELD: 1})
    stored = (doc or {}).get(STARRED_VOICES_FIELD)
    if isinstance(stored, list):
        return [v for v in stored if isinstance(v, str)]
    return list(DEFAULT_STARRED_VOICE_IDS)


async def set_voice_star(user_id: str, voice_id: str, starred: bool) -> list[str]:
    """Star or unstar a voice for the user; returns the updated starred set."""
    current = await get_starred_voice_ids(user_id)
    updated = [v for v in current if v != voice_id]
    if starred:
        updated.insert(0, voice_id)
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {STARRED_VOICES_FIELD: updated}},
    )
    return updated


async def _add_library_voice_to_account(voice: dict[str, Any]) -> str:
    """Add a shared-library voice to the ElevenLabs account so TTS can use it.

    Returns the (account) voice id. Raises AppError with ElevenLabs' reason
    when the add fails — most commonly the account's voice slots are full.
    """
    url = ELEVENLABS_ADD_VOICE_URL.format(
        owner_id=voice["public_owner_id"], voice_id=voice["voice_id"]
    )
    try:
        async with httpx.AsyncClient(timeout=ELEVENLABS_REQUEST_TIMEOUT_S) as client:
            resp = await client.post(
                url,
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY or ""},
                json={"new_name": voice["name"]},
            )
            resp.raise_for_status()
            added_id = resp.json().get("voice_id") or voice["voice_id"]
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:200]
        log.warning("Failed to add library voice", voice_id=voice["voice_id"], detail=detail)
        raise AppError(
            message="Could not add this voice to the account",
            why=f"ElevenLabs rejected the add: {detail}",
            fix="Free a voice slot on the ElevenLabs account or pick another voice",
            status_code=422,
        ) from e
    except httpx.HTTPError as e:
        raise AppError(
            message="Could not reach ElevenLabs to add this voice",
            why=str(e),
            fix="Try again in a moment",
            status_code=502,
        ) from e

    # The account voice list changed — refetch on next read so the new voice
    # lists (and validates) immediately.
    await redis_cache.delete(ELEVENLABS_VOICES_CACHE_KEY)
    return str(added_id)


async def set_user_voice(user_id: str, voice_id: str) -> str:
    """Persist the user's voice selection, adding library voices to the account.

    Account (and curated-fallback) voices persist directly. A shared-library
    voice is first added to the ElevenLabs account — TTS can only synthesize
    account voices — and the resulting account voice id is stored.
    """
    if voice_id not in await _known_voice_ids():
        shared = {v["voice_id"]: v for v in await get_shared_voices()}
        if voice_id not in shared:
            raise AppError(
                message="Unknown voice",
                why=f"Voice id {voice_id!r} is not on the account or in the voice library",
                fix="Pick a voice from GET /voice/voices",
                status_code=404,
            )
        voice_id = await _add_library_voice_to_account(shared[voice_id])

    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {SELECTED_VOICE_FIELD: voice_id}},
    )
    return voice_id
