"""Pydantic schemas for voice mode — voice catalog and user voice selection."""

from pydantic import BaseModel, Field


class VoiceOption(BaseModel):
    """One selectable ElevenLabs voice from the curated catalog."""

    voice_id: str = Field(description="ElevenLabs voice id")
    name: str = Field(description="Display name")
    language: str = Field(description="Primary spoken language")
    accent: str = Field(description="Accent, e.g. American, British")
    country_code: str = Field(description="ISO 3166-1 alpha-2 country code for the accent")
    gender: str = Field(description="Voice gender presentation")
    description: str = Field(description="Short character description")
    preview_url: str | None = Field(
        default=None,
        description="Public MP3 sample for the play button; null when unavailable",
    )


class VoiceListResponse(BaseModel):
    voices: list[VoiceOption]
    selected_voice_id: str | None = Field(
        default=None,
        description="The user's chosen voice id; null means the default voice",
    )


class UpdateVoiceRequest(BaseModel):
    voice_id: str = Field(min_length=1, description="Catalog voice id to use for voice mode")


class VoiceSelectionResponse(BaseModel):
    selected_voice_id: str
