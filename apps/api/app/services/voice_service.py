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
    DEFAULT_STARRED_VOICE_IDS,
    DEFAULT_VOICE_ID,
    ELEVENLABS_REQUEST_TIMEOUT_S,
    ELEVENLABS_SHARED_VOICES_URL,
    ELEVENLABS_VOICES_URL,
    SELECTED_VOICE_FIELD,
    SHARED_VOICES_PAGE_SIZE,
    STARRED_VOICES_FIELD,
    VOICE_CATALOG,
    VOICE_IDS,
)
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable
from app.schemas.voice_schemas import VoiceListResponse, VoiceOption
from app.utils.errors import AppError
from app.utils.voice_utils import (
    _language_names,
    _map_account_voice,
    _map_shared_voice,
    _verified_language_codes,
)
from shared.py.wide_events import log


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

    # Reconcile the stored selection against what is actually listed: a voice
    # deleted from the ElevenLabs account would otherwise show as selected in the
    # picker (and fail TTS if kept). Free here since the full catalog is already
    # assembled — unlike get_user_voice, which stays validation-free for /token.
    available_ids = {v.voice_id for v in voices}
    if selected not in available_ids:
        selected = DEFAULT_VOICE_ID if DEFAULT_VOICE_ID in available_ids else None
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


async def set_user_voice(user_id: str, voice_id: str) -> str:
    """Persist the user's voice selection.

    The voice must be on the account or in the public ElevenLabs library. Library
    voices are stored and synthesized by id directly — ElevenLabs TTS accepts a
    library voice id without first adding it to the account (verified across both
    free and professional library voices). The old add-to-account step was
    unnecessary: it consumed account voice slots and failed outright when the API
    key lacked the ``add_voice_from_voice_library`` permission, blocking
    otherwise-usable voices.
    """
    if voice_id not in await _known_voice_ids():
        shared_ids = {v["voice_id"] for v in await get_shared_voices()}
        if voice_id not in shared_ids:
            raise AppError(
                message="Unknown voice",
                why=f"Voice id {voice_id!r} is not on the account or in the voice library",
                fix="Pick a voice from GET /voice/voices",
                status_code=404,
            )

    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {SELECTED_VOICE_FIELD: voice_id}},
    )
    return voice_id
