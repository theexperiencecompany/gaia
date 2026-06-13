"""Curated ElevenLabs voice catalog for voice mode.

The catalog is owned by GAIA (not fetched from ElevenLabs at request time) so
the voice picker is stable, fast, and works without an upstream call. Preview
URLs are the only upstream-sourced field — resolved lazily from the ElevenLabs
voices API and cached (see ``voice_service.get_elevenlabs_voices``).

All IDs are stable ElevenLabs premade voices available to every API key.
"""

from typing import TypedDict


class VoiceCatalogEntry(TypedDict):
    """Static catalog row describing one ElevenLabs premade voice."""

    voice_id: str
    name: str
    language: str
    accent: str
    country_code: str
    gender: str
    description: str


VOICE_CATALOG: list[VoiceCatalogEntry] = [
    {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "name": "Rachel",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Female",
        "description": "Calm and composed — a steady narrator",
    },
    {
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Sarah",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Female",
        "description": "Soft and warm, with a reassuring tone",
    },
    {
        "voice_id": "FGY2WhTYpPnrIDTdsKH5",
        "name": "Laura",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Female",
        "description": "Upbeat and sunny — energetic delivery",
    },
    {
        "voice_id": "cgSgspJ2msm6clMCkdW9",
        "name": "Jessica",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Female",
        "description": "Expressive and playful, conversational",
    },
    {
        "voice_id": "XrExE9yKIg1WjnnlVkGX",
        "name": "Matilda",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Female",
        "description": "Friendly professional with a bright edge",
    },
    {
        "voice_id": "Xb7hH8MSUJpSbSDYk0k2",
        "name": "Alice",
        "language": "English",
        "accent": "British",
        "country_code": "GB",
        "gender": "Female",
        "description": "Confident and crisp British clarity",
    },
    {
        "voice_id": "pFZP5JQG7iQjIQuC4Bku",
        "name": "Lily",
        "language": "English",
        "accent": "British",
        "country_code": "GB",
        "gender": "Female",
        "description": "Warm and velvety, gentle pace",
    },
    {
        "voice_id": "XB0fDUnXU5powFXDhCwa",
        "name": "Charlotte",
        "language": "English",
        "accent": "Swedish",
        "country_code": "SE",
        "gender": "Female",
        "description": "Seductive Scandinavian lilt",
    },
    {
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "name": "Adam",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Deep and resonant — classic narration",
    },
    {
        "voice_id": "TxGEqnHWrfWFTfGW9XjX",
        "name": "Josh",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Deep, young, and grounded",
    },
    {
        "voice_id": "ErXwobaYiN019PkySvjV",
        "name": "Antoni",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Well-rounded and easygoing",
    },
    {
        "voice_id": "bIHbv24MWmeRgasZH58o",
        "name": "Will",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Friendly and relaxed, like a good neighbor",
    },
    {
        "voice_id": "cjVigY5qzO86Huf0OWal",
        "name": "Eric",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Approachable mid-register everyman",
    },
    {
        "voice_id": "iP95p4xoKVk53GoZ742B",
        "name": "Chris",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Casual and natural — coffee-chat energy",
    },
    {
        "voice_id": "nPczCjzI2devNBz1zQrb",
        "name": "Brian",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Deep broadcast-grade authority",
    },
    {
        "voice_id": "pqHfZKP75CvOlQylNhV4",
        "name": "Bill",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Trustworthy and seasoned",
    },
    {
        "voice_id": "TX3LPaxmHKxFdv7VOQHJ",
        "name": "Liam",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Male",
        "description": "Articulate and energetic",
    },
    {
        "voice_id": "JBFqnCBsd6RMkjVDRZzb",
        "name": "George",
        "language": "English",
        "accent": "British",
        "country_code": "GB",
        "gender": "Male",
        "description": "Warm British storyteller",
    },
    {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Daniel",
        "language": "English",
        "accent": "British",
        "country_code": "GB",
        "gender": "Male",
        "description": "Authoritative and polished presenter",
    },
    {
        "voice_id": "IKne3meq5aSn9XLyUdCD",
        "name": "Charlie",
        "language": "English",
        "accent": "Australian",
        "country_code": "AU",
        "gender": "Male",
        "description": "Laid-back Aussie confidence",
    },
    {
        "voice_id": "N2lVS1w4EtoT3dr4eOWO",
        "name": "Callum",
        "language": "English",
        "accent": "Transatlantic",
        "country_code": "US",
        "gender": "Male",
        "description": "Intense with a hint of mystery",
    },
    {
        "voice_id": "SAz9YHcvj6GT2YYXdXww",
        "name": "River",
        "language": "English",
        "accent": "American",
        "country_code": "US",
        "gender": "Neutral",
        "description": "Calm and neutral — relaxed presence",
    },
]

VOICE_IDS: frozenset[str] = frozenset(v["voice_id"] for v in VOICE_CATALOG)

# Product default — Jessica. Used when a user has never picked a voice:
# embedded in the session token and shown as selected in settings.
DEFAULT_VOICE_ID = "cgSgspJ2msm6clMCkdW9"

# Users collection field holding the user's chosen ElevenLabs voice id.
SELECTED_VOICE_FIELD = "selected_voice_id"

# Users collection field holding the user's starred voice ids.
STARRED_VOICES_FIELD = "starred_voice_ids"

# Starred out of the box (until the user edits their stars): Eva, Jessica, Lucy.
DEFAULT_STARRED_VOICE_IDS: list[str] = [
    "weA4Q36twV5kwSaTEL0Q",  # Eva - Futuristic Robot Helper
    "cgSgspJ2msm6clMCkdW9",  # Jessica
    "lcMyyd2HUfFzxdCaC4Ta",  # Lucy - Fresh & Casual
]

# Maps ElevenLabs accent labels to ISO country codes for the flag column.
# Account voices outside the curated catalog derive their flag from this;
# unmapped accents render without a flag.
ACCENT_TO_COUNTRY: dict[str, str] = {
    "american": "US",
    "british": "GB",
    "english": "GB",
    "australian": "AU",
    "irish": "IE",
    "scottish": "GB",
    "canadian": "CA",
    "swedish": "SE",
    "transatlantic": "US",
    "indian": "IN",
    "nigerian": "NG",
    "south african": "ZA",
    "new zealand": "NZ",
    "german": "DE",
    "french": "FR",
    "spanish": "ES",
    "italian": "IT",
    "japanese": "JP",
    "korean": "KR",
    "chinese": "CN",
    "brazilian": "BR",
    "mexican": "MX",
    "polish": "PL",
    "portuguese": "PT",
    "russian": "RU",
    "turkish": "TR",
    "arabic": "SA",
    "african american": "US",
    "argentine": "AR",
    "bhojpuri": "IN",
    "canary islands": "ES",
    "chilean": "CL",
    "colombian": "CO",
    "dominican": "DO",
    "gyeongsang": "KR",
    "istanbul": "TR",
    "kanto": "JP",
    "omani": "OM",
    "peninsular": "ES",
    "peruvian": "PE",
    "quebec": "CA",
    "received pronunciation": "GB",
    "saudi": "SA",
    "seoul": "KR",
    "swiss": "CH",
    "venezuelan": "VE",
    "welsh": "GB",
}

# ElevenLabs API endpoints and request tuning for resolving preview samples and
# adding shared-library voices to the account.
ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_SHARED_VOICES_URL = "https://api.elevenlabs.io/v1/shared-voices"
ELEVENLABS_ADD_VOICE_URL = "https://api.elevenlabs.io/v1/voices/add/{owner_id}/{voice_id}"
ELEVENLABS_REQUEST_TIMEOUT_S = 10.0
# One page of featured library voices is plenty for the picker without
# ballooning the table; previews come straight off the library response.
SHARED_VOICES_PAGE_SIZE = 100

# Human names for ElevenLabs ISO-639 language labels.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "hi": "Hindi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "nl": "Dutch",
    "tr": "Turkish",
    "sv": "Swedish",
    "ru": "Russian",
    "id": "Indonesian",
    "ro": "Romanian",
    "vi": "Vietnamese",
    "cs": "Czech",
    "da": "Danish",
    "fi": "Finnish",
    "el": "Greek",
    "hu": "Hungarian",
    "no": "Norwegian",
    "sk": "Slovak",
    "uk": "Ukrainian",
    "ta": "Tamil",
}
