"""Curated ElevenLabs voice catalog for voice mode.

The catalog is owned by GAIA (not fetched from ElevenLabs at request time) so
the voice picker is stable, fast, and works without an upstream call. Preview
URLs are the only upstream-sourced field — resolved lazily from the ElevenLabs
voices API and cached (see ``voice_service.get_preview_urls``).

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

# Users collection field holding the user's chosen ElevenLabs voice id.
SELECTED_VOICE_FIELD = "selected_voice_id"

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
}

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
}
