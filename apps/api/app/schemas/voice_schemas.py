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
    source: str = Field(
        default="account",
        description="'account' for voices already usable, 'library' for shared-library voices added to the account on selection",
    )
    languages: list[str] = Field(
        default_factory=list,
        description="All verified languages (display names, primary first)",
    )
    starred: bool = Field(default=False, description="Starred by this user")


class VoiceListResponse(BaseModel):
    """Catalog of selectable voices plus the user's current selection."""

    voices: list[VoiceOption]
    selected_voice_id: str | None = Field(
        default=None,
        description="The user's chosen voice id; null means the default voice",
    )


class UpdateVoiceRequest(BaseModel):
    """Request body for choosing a voice."""

    voice_id: str = Field(min_length=1, description="Catalog voice id to use for voice mode")


class VoiceSelectionResponse(BaseModel):
    """Confirmation of the persisted voice selection."""

    selected_voice_id: str


class StarVoiceRequest(BaseModel):
    """Request body for starring/unstarring a voice."""

    starred: bool = Field(description="True to star, False to unstar")


class StarredVoicesResponse(BaseModel):
    """The user's full starred set after a star/unstar."""

    starred_voice_ids: list[str]
