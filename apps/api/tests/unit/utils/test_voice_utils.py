"""Unit tests for the ElevenLabs voice mappers in app/utils/voice_utils.py."""

from app.models.voice_models import ElevenLabsAccountVoice
from app.utils.voice_utils import (
    ElevenLabsVoiceLanguages,
    _map_account_voice,
    _verified_language_codes,
)


class TestVerifiedLanguageCodes:
    def test_dedupes_lowercases_and_keeps_first_seen_order(self) -> None:
        raw = {
            "voice_id": "v1",
            "verified_languages": [
                {"language": "EN", "model_id": "m1"},
                {"language": "de", "model_id": "m1"},
                {"language": "en", "model_id": "m2"},
                {"language": None},
                {"language": ""},
            ],
        }
        assert _verified_language_codes(ElevenLabsVoiceLanguages.model_validate(raw)) == [
            "en",
            "de",
        ]

    def test_missing_or_null_verified_languages_is_empty(self) -> None:
        assert _verified_language_codes(ElevenLabsVoiceLanguages.model_validate({})) == []
        assert (
            _verified_language_codes(
                ElevenLabsVoiceLanguages.model_validate({"verified_languages": None})
            )
            == []
        )


class TestMapAccountVoice:
    def test_reads_documented_labels(self) -> None:
        voice = ElevenLabsAccountVoice(
            voice_id="acct-1",
            name="Clone - Warm narrator",
            preview_url="https://p/1.mp3",
            language_codes=["en", "de"],
            labels={
                "accent": "british",
                "gender": "female",
                "descriptive": "calm",
                "use_case": "audiobook",
                "language": "en",
                "custom_key": "ignored",
            },
        )
        option = _map_account_voice(voice)
        assert option.model_dump() == {
            "voice_id": "acct-1",
            "name": "Clone",
            "language": "English",
            "accent": "British",
            "country_code": "GB",
            "gender": "Female",
            "description": "Warm narrator",
            "preview_url": "https://p/1.mp3",
            "source": "account",
            "languages": ["English", "German"],
            "starred": False,
        }

    def test_empty_labels_fall_back(self) -> None:
        voice = ElevenLabsAccountVoice(voice_id="acct-2", name="Plain", labels={})
        option = _map_account_voice(voice)
        assert option.accent == "International"
        assert option.gender == "Neutral"
        assert option.language == "English"
        assert option.description == "Account voice"
        assert option.languages == ["English"]

    def test_underscored_labels_render_as_spaced_titles(self) -> None:
        descriptive = _map_account_voice(
            ElevenLabsAccountVoice(
                voice_id="acct-3", name="Plain", labels={"descriptive": "soft_spoken"}
            )
        )
        use_case = _map_account_voice(
            ElevenLabsAccountVoice(
                voice_id="acct-4", name="Plain", labels={"use_case": "social_media"}
            )
        )
        assert descriptive.description == "Soft Spoken"
        assert use_case.description == "Social Media"
