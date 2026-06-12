"""Voice selection — curated catalog listing and per-user voice preference.

The catalog lives in ``app/constants/voices.py``. ElevenLabs is contacted only
to resolve preview sample URLs (cached for a day); listing and selection work
even when the upstream call fails.
"""

from typing import Any

from bson import ObjectId
import httpx

from app.config.settings import settings
from app.constants.cache import ONE_DAY_TTL
from app.constants.voices import (
    ACCENT_TO_COUNTRY,
    LANGUAGE_NAMES,
    SELECTED_VOICE_FIELD,
    VOICE_CATALOG,
    VOICE_IDS,
)
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable
from app.schemas.voice_schemas import VoiceListResponse, VoiceOption
from app.utils.errors import AppError
from shared.py.wide_events import log

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_REQUEST_TIMEOUT_S = 10.0


@Cacheable(ttl=ONE_DAY_TTL, key_pattern="voice:elevenlabs_voices")
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


def _map_account_voice(voice: dict[str, Any]) -> VoiceOption:
    """Shape a non-catalog account voice into a catalog-compatible option.

    ElevenLabs names premades as "Name - Short description"; split that into
    the name/description columns. Accent and language come from the labels.
    """
    raw_name = voice["name"]
    name, _, blurb = raw_name.partition(" - ")
    labels: dict[str, Any] = voice["labels"]
    accent = str(labels.get("accent") or "").strip()
    descriptive = str(labels.get("descriptive") or "").replace("_", " ")
    use_case = str(labels.get("use_case") or "").replace("_", " ")
    language_code = str(labels.get("language") or "")
    gender = str(labels.get("gender") or "").strip().title() or "Neutral"
    return VoiceOption(
        voice_id=voice["voice_id"],
        name=name.strip() or raw_name,
        language=LANGUAGE_NAMES.get(language_code, language_code.upper() or "English"),
        accent=accent.title() or "Unknown",
        country_code=ACCENT_TO_COUNTRY.get(accent.lower(), ""),
        gender=gender,
        description=blurb.strip() or descriptive.title() or use_case.title() or "Account voice",
        preview_url=voice.get("preview_url"),
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
    """Return the user's selected voice id, or None for the default."""
    doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {SELECTED_VOICE_FIELD: 1})
    voice_id = (doc or {}).get(SELECTED_VOICE_FIELD)
    # A stale selection (voice no longer available) falls back to default.
    if isinstance(voice_id, str) and voice_id in await _known_voice_ids():
        return voice_id
    return None


async def list_voices(user_id: str) -> VoiceListResponse:
    """Return the curated catalog plus account voices, with the user's selection.

    Curated entries come first (stable copy, hand-written descriptions); any
    other voice on the ElevenLabs account — premades we did not curate and the
    account's own cloned voices — is appended with metadata derived from its
    labels. Catalog entries the account no longer carries are dropped: they
    would have no preview and, worse, fail TTS if selected.
    """
    account = await get_elevenlabs_voices()
    by_id = {v["voice_id"]: v for v in account}
    selected = await get_user_voice(user_id)
    voices = [
        VoiceOption(**entry, preview_url=(by_id.get(entry["voice_id"]) or {}).get("preview_url"))
        for entry in VOICE_CATALOG
        if not account or entry["voice_id"] in by_id
    ]
    voices.extend(
        _map_account_voice(voice) for voice in account if voice["voice_id"] not in VOICE_IDS
    )
    return VoiceListResponse(voices=voices, selected_voice_id=selected)


async def set_user_voice(user_id: str, voice_id: str) -> str:
    """Persist the user's voice selection after validating it is selectable."""
    if voice_id not in await _known_voice_ids():
        raise AppError(
            message="Unknown voice",
            why=f"Voice id {voice_id!r} is neither in the catalog nor on the account",
            fix="Pick a voice from GET /voice/voices",
            status_code=404,
        )
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {SELECTED_VOICE_FIELD: voice_id}},
    )
    return voice_id
