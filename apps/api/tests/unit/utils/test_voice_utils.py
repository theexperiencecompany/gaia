"""Unit tests for ``app.utils.voice_utils`` — ElevenLabs voice metadata helpers."""

from app.utils.voice_utils import _verified_language_codes


def test_verified_language_codes_deduplicates_by_language() -> None:
    """ElevenLabs repeats a language once per supporting model — collapse to
    one entry per language, preserving first-seen order."""
    voice = {
        "verified_languages": [
            {"language": "en", "model": "a"},
            {"language": "EN", "model": "b"},
            {"language": "fr", "model": "a"},
        ]
    }
    assert _verified_language_codes(voice) == ["en", "fr"]


def test_verified_language_codes_skips_non_dict_entries() -> None:
    voice = {"verified_languages": ["not-a-dict", {"language": "de"}, None]}
    assert _verified_language_codes(voice) == ["de"]


def test_verified_language_codes_missing_or_blank_language() -> None:
    voice = {"verified_languages": [{"language": ""}, {"language": None}, {"other": 1}]}
    assert _verified_language_codes(voice) == []


def test_verified_language_codes_missing_key() -> None:
    assert _verified_language_codes({}) == []
