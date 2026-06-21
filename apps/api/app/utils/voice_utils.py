"""Pure mappers that normalize ElevenLabs voice payloads into catalog options.

Stateless helpers only — no I/O, DB, settings, or network. They shape raw
ElevenLabs account/shared-library voice dicts into the catalog-compatible
``VoiceOption`` schema used by the voice picker.
"""

from typing import Any

from app.constants.voices import ACCENT_TO_COUNTRY, LANGUAGE_NAMES
from app.schemas.voice_schemas import VoiceOption


def _verified_language_codes(voice: dict[str, Any]) -> list[str]:
    """Ordered, deduped ISO codes from a voice's verified_languages.

    ElevenLabs repeats a language once per supporting model — collapse to one
    entry per language, preserving first-seen order.
    """
    seen: list[str] = []
    for entry in voice.get("verified_languages") or []:
        code = str(entry.get("language") or "").lower()
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


def _build_voice_option(
    voice: dict[str, Any],
    *,
    accent: str,
    gender: str,
    descriptive: str,
    use_case: str,
    language_code: str,
    source: str,
    fallback_description: str,
) -> VoiceOption:
    """Shape a non-catalog ElevenLabs voice into a catalog-compatible option."""
    name, blurb = _split_display_name(voice["name"])
    accent_label = _normalize_accent(accent)
    primary = LANGUAGE_NAMES.get(language_code, language_code.upper() or "English")
    descriptive = descriptive.replace("_", " ")
    use_case = use_case.replace("_", " ")
    return VoiceOption(
        voice_id=voice["voice_id"],
        name=name,
        language=primary,
        accent=accent_label,
        country_code=ACCENT_TO_COUNTRY.get(accent_label.lower(), ""),
        gender=gender.strip().title() or "Neutral",
        description=blurb or descriptive.title() or use_case.title() or fallback_description,
        preview_url=voice.get("preview_url"),
        source=source,
        languages=_language_names(voice.get("language_codes") or [], primary),
    )


def _map_account_voice(voice: dict[str, Any]) -> VoiceOption:
    """Shape a non-catalog account voice (metadata in ``labels``) into an option."""
    labels: dict[str, Any] = voice["labels"]
    return _build_voice_option(
        voice,
        accent=str(labels.get("accent") or ""),
        gender=str(labels.get("gender") or ""),
        descriptive=str(labels.get("descriptive") or ""),
        use_case=str(labels.get("use_case") or ""),
        language_code=str(labels.get("language") or ""),
        source="account",
        fallback_description="Account voice",
    )


def _map_shared_voice(voice: dict[str, Any]) -> VoiceOption:
    """Shape a shared-library voice (metadata at the top level) into an option."""
    return _build_voice_option(
        voice,
        accent=voice["accent"],
        gender=voice["gender"],
        descriptive=voice["descriptive"],
        use_case=voice["use_case"],
        language_code=voice["language"],
        source="library",
        fallback_description="Community voice",
    )
