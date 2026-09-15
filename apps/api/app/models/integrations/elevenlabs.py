"""ElevenLabs voices API payloads (GET /v1/voices, GET /v1/shared-voices)."""

from pydantic import BaseModel, ConfigDict, Field

from app.utils.voice_utils import ElevenLabsVoiceLanguages


class ElevenLabsRawVoice(ElevenLabsVoiceLanguages):
    """One untrimmed voice object, as either voices endpoint lists it.

    Account voices carry their metadata in labels; shared-library voices carry
    it top-level alongside public_owner_id. Every field is optional because
    each endpoint sets only its own half, and a voice without an id is skipped.
    """

    model_config = ConfigDict(extra="ignore")

    voice_id: str | None = None
    name: str | None = None
    preview_url: str | None = None
    # Provider-owned free-form label bag: an account defines its own label keys.
    labels: dict[str, object] | None = None
    public_owner_id: str | None = None
    gender: str | None = None
    accent: str | None = None
    language: str | None = None
    descriptive: str | None = None
    use_case: str | None = None


class ElevenLabsVoicesPage(BaseModel):
    """A voices-endpoint response, read only for its voices list."""

    model_config = ConfigDict(extra="ignore")

    voices: list[ElevenLabsRawVoice] = Field(default_factory=list)
