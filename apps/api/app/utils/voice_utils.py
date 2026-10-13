"""Pure mappers that normalize ElevenLabs voice payloads into catalog options.

Stateless helpers only — no I/O, DB, settings, or network. They shape the
trimmed account/shared-library voices (app/models/voice_models.py) into the
catalog-compatible VoiceOption schema used by the voice picker.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.constants.voices import ACCENT_TO_COUNTRY, LANGUAGE_NAMES
from app.models.voice_models import (
    ElevenLabsAccountVoice,
    ElevenLabsSharedVoice,
    ElevenLabsVoice,
)
from app.schemas.voice_schemas import VoiceOption


class ElevenLabsVerifiedLanguage(BaseModel):
    """One ``verified_languages`` entry of a raw ElevenLabs voice."""

    model_config = ConfigDict(extra="ignore")

    language: str | None = None


class ElevenLabsVoiceLanguages(BaseModel):
    """The verified_languages slice of a RAW ElevenLabs voice object, validated at the boundary."""

    model_config = ConfigDict(extra="ignore")

    verified_languages: list[ElevenLabsVerifiedLanguage] | None = None


class ElevenLabsVoiceLabels(BaseModel):
    """The documented keys of an account voice's free-form labels bag."""

    model_config = ConfigDict(extra="ignore")

    accent: str | None = None
    gender: str | None = None
    descriptive: str | None = None
    use_case: str | None = None
    language: str | None = None


def _verified_language_codes(voice: ElevenLabsVoiceLanguages) -> list[str]:
    """Ordered, deduped ISO codes from a voice's verified_languages.

    ElevenLabs repeats a language once per supporting model, so this collapses
    to one entry per language, preserving first-seen order.
    """
    seen: list[str] = []
    for entry in voice.verified_languages or []:
        code = (entry.language or "").lower()
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


def _split_display_name(raw_name: str) -> tuple[str, str]:
    """Split ElevenLabs' "Name - Short description" naming into columns."""
    name, _, blurb = raw_name.partition(" - ")
    return name.strip() or raw_name, blurb.strip()


@dataclass(frozen=True, slots=True)
class _VoiceTraits:
    """The descriptive labels a non-catalog voice carries, wherever ElevenLabs put them."""

    accent: str
    gender: str
    descriptive: str
    use_case: str
    language_code: str


def _build_voice_option(
    voice: ElevenLabsVoice,
    traits: _VoiceTraits,
    *,
    source: str,
    fallback_description: str,
) -> VoiceOption:
    """Shape a non-catalog ElevenLabs voice into a catalog-compatible option."""
    name, blurb = _split_display_name(voice.name)
    accent_label = _normalize_accent(traits.accent)
    language_code = traits.language_code
    gender = traits.gender
    primary = LANGUAGE_NAMES.get(language_code, language_code.upper() or "English")
    descriptive = traits.descriptive.replace("_", " ")
    use_case = traits.use_case.replace("_", " ")
    return VoiceOption(
        voice_id=voice.voice_id,
        name=name,
        language=primary,
        accent=accent_label,
        country_code=ACCENT_TO_COUNTRY.get(accent_label.lower(), ""),
        gender=gender.strip().title() or "Neutral",
        description=blurb or descriptive.title() or use_case.title() or fallback_description,
        preview_url=voice.preview_url,
        source=source,
        languages=_language_names(voice.language_codes, primary),
    )


def _map_account_voice(voice: ElevenLabsAccountVoice) -> VoiceOption:
    """Shape a non-catalog account voice (metadata in labels) into an option."""
    labels = ElevenLabsVoiceLabels.model_validate(voice.labels)
    return _build_voice_option(
        voice,
        _VoiceTraits(
            accent=labels.accent or "",
            gender=labels.gender or "",
            descriptive=labels.descriptive or "",
            use_case=labels.use_case or "",
            language_code=labels.language or "",
        ),
        source="account",
        fallback_description="Account voice",
    )


def _map_shared_voice(voice: ElevenLabsSharedVoice) -> VoiceOption:
    """Shape a shared-library voice (metadata at the top level) into an option."""
    return _build_voice_option(
        voice,
        _VoiceTraits(
            accent=voice.accent,
            gender=voice.gender,
            descriptive=voice.descriptive,
            use_case=voice.use_case,
            language_code=voice.language,
        ),
        source="library",
        fallback_description="Community voice",
    )
