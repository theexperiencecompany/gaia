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
from app.constants.voices import SELECTED_VOICE_FIELD, VOICE_CATALOG, VOICE_IDS
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable
from app.schemas.voice_schemas import VoiceListResponse, VoiceOption
from app.utils.errors import AppError
from shared.py.wide_events import log

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_REQUEST_TIMEOUT_S = 10.0


@Cacheable(ttl=ONE_DAY_TTL, key_pattern="voice:preview_urls")
async def get_preview_urls() -> dict[str, str]:
    """Resolve preview MP3 URLs for the catalog from the ElevenLabs voices API.

    Returns an empty mapping when the API key is missing or the call fails —
    the catalog still lists, just without playable samples.
    """
    api_key = settings.ELEVENLABS_API_KEY
    if not api_key:
        return {}
    try:
        async with httpx.AsyncClient(timeout=ELEVENLABS_REQUEST_TIMEOUT_S) as client:
            resp = await client.get(ELEVENLABS_VOICES_URL, headers={"xi-api-key": api_key})
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Failed to fetch ElevenLabs voice previews", error=str(e))
        return {}

    previews: dict[str, str] = {}
    for voice in payload.get("voices", []):
        voice_id = voice.get("voice_id")
        preview_url = voice.get("preview_url")
        if isinstance(voice_id, str) and isinstance(preview_url, str) and voice_id in VOICE_IDS:
            previews[voice_id] = preview_url
    return previews


async def get_user_voice(user_id: str) -> str | None:
    """Return the user's selected catalog voice id, or None for the default."""
    doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {SELECTED_VOICE_FIELD: 1})
    voice_id = (doc or {}).get(SELECTED_VOICE_FIELD)
    # A stale selection (voice removed from the catalog) falls back to default.
    if isinstance(voice_id, str) and voice_id in VOICE_IDS:
        return voice_id
    return None


async def list_voices(user_id: str) -> VoiceListResponse:
    """Return the curated catalog with preview URLs and the user's selection."""
    previews = await get_preview_urls()
    selected = await get_user_voice(user_id)
    voices = [
        VoiceOption(**entry, preview_url=previews.get(entry["voice_id"])) for entry in VOICE_CATALOG
    ]
    return VoiceListResponse(voices=voices, selected_voice_id=selected)


async def set_user_voice(user_id: str, voice_id: str) -> str:
    """Persist the user's voice selection after validating it against the catalog."""
    if voice_id not in VOICE_IDS:
        raise AppError(
            message="Unknown voice",
            why=f"Voice id {voice_id!r} is not in the curated catalog",
            fix="Pick a voice from GET /voice/voices",
            status_code=404,
        )
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {SELECTED_VOICE_FIELD: voice_id}},
    )
    return voice_id
