"""Trimmed ElevenLabs voice payloads.

What ``voice_service`` keeps from the ElevenLabs voices / shared-voices APIs —
the raw provider response is read once at the boundary and reduced to these
shapes, which are what everything downstream (the picker mappers in
``app/utils/voice_utils.py``, the availability checks) actually consumes.

These cross a serialization boundary: both fetchers are ``@Cacheable`` for a
day, so an instance is JSON-encoded into Redis and validated back out of it —
hence Pydantic models rather than TypedDicts. The cached JSON is field-for-field
what the previous plain dicts stored, so entries written before this shape
existed still validate.
"""

from typing import Any

from pydantic import BaseModel, Field


class ElevenLabsVoice(BaseModel):
    """What both voice sources have in common — all ``_build_voice_option`` needs."""

    voice_id: str
    name: str
    preview_url: str | None = None
    language_codes: list[str] = Field(default_factory=list)


class ElevenLabsAccountVoice(ElevenLabsVoice):
    """A voice on the ElevenLabs account, whose metadata lives in ``labels``."""

    # Provider-owned free-form label bag: ElevenLabs lets an account define its own
    # label keys on cloned voices, so this is a genuinely dynamic mapping, not a
    # fixed shape. ``_map_account_voice`` reads the documented keys defensively.
    labels: dict[str, Any] = Field(default_factory=dict)


class ElevenLabsSharedVoice(ElevenLabsVoice):
    """A voice from the public ElevenLabs library, whose metadata is top-level."""

    public_owner_id: str
    gender: str = ""
    accent: str = ""
    language: str = ""
    descriptive: str = ""
    use_case: str = ""
