"""Unit tests for user preferences utility functions."""

from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.utils.user_preferences_utils import (
    build_user_context_parts,
    format_profession_for_display,
    format_response_style_instruction,
    format_user_preferences_for_agent,
    get_user_preference_summary,
    validate_user_preferences,
)


# ---------------------------------------------------------------------------
# format_response_style_instruction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatResponseStyleInstruction:
    @pytest.mark.parametrize(
        "style, expected",
        [
            ("brief", "Keep responses brief and to the point"),
            ("detailed", "Provide detailed and comprehensive responses"),
            ("casual", "Use a casual and friendly tone"),
            ("professional", "Maintain a professional and formal tone"),
        ],
    )
    def test_known_style_returns_mapped_value(self, style: str, expected: str) -> None:
        assert format_response_style_instruction(style) == expected

    @pytest.mark.parametrize(
        "style",
        [
            "verbose",
            "terse",
            "academic",
            "Use bullet points and be concise",
        ],
    )
    def test_unknown_style_returned_as_is(self, style: str) -> None:
        assert format_response_style_instruction(style) == style

    def test_empty_string_returned_as_is(self) -> None:
        # Empty string is not in the style_map, so dict.get returns the default (the key itself)
        assert format_response_style_instruction("") == ""


# ---------------------------------------------------------------------------
# format_profession_for_display
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatProfessionForDisplay:
    @pytest.mark.parametrize(
        "profession, expected",
        [
            ("software engineer", "Software Engineer"),
            ("data scientist", "Data Scientist"),
            ("DESIGNER", "Designer"),
            ("product manager", "Product Manager"),
        ],
    )
    def test_valid_profession_title_cased(self, profession: str, expected: str) -> None:
        assert format_profession_for_display(profession) == expected

    def test_empty_string_returns_empty(self) -> None:
        assert format_profession_for_display("") == ""

    def test_none_returns_empty(self) -> None:
        # None is falsy, so the `if not profession` guard catches it
        assert format_profession_for_display(None) == ""  # type: ignore[arg-type]

    def test_whitespace_only_returns_empty(self) -> None:
        # strip() produces "", which is then title-cased to "" (empty)
        result = format_profession_for_display("   ")
        assert result == ""

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert format_profession_for_display("  doctor  ") == "Doctor"

    def test_single_word(self) -> None:
        assert format_profession_for_display("teacher") == "Teacher"


# ---------------------------------------------------------------------------
# build_user_context_parts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildUserContextParts:
    @patch("app.utils.user_preferences_utils.log")
    def test_all_fields_present(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "software engineer",
            "response_style": "brief",
            "custom_instructions": "Always use Python examples",
        }
        parts = build_user_context_parts(preferences)
        assert len(parts) == 3
        assert parts[0] == "User Profession: Software Engineer"
        assert parts[1] == "Communication Style: Keep responses brief and to the point"
        assert parts[2] == "Special Instructions: Always use Python examples"

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_preferences(self, mock_log: Any) -> None:
        parts = build_user_context_parts({})
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_only_profession(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"profession": "doctor"})
        assert parts == ["User Profession: Doctor"]

    @patch("app.utils.user_preferences_utils.log")
    def test_only_response_style(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"response_style": "casual"})
        assert parts == ["Communication Style: Use a casual and friendly tone"]

    @patch("app.utils.user_preferences_utils.log")
    def test_only_custom_instructions(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"custom_instructions": "Respond in Spanish"})
        assert parts == ["Special Instructions: Respond in Spanish"]

    @patch("app.utils.user_preferences_utils.log")
    def test_none_values_ignored(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": None,
            "response_style": None,
            "custom_instructions": None,
        }
        parts = build_user_context_parts(preferences)
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_string_values_ignored(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "",
            "response_style": "",
            "custom_instructions": "",
        }
        parts = build_user_context_parts(preferences)
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_whitespace_only_custom_instructions_ignored(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"custom_instructions": "   "})
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_custom_instructions_stripped(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"custom_instructions": "  Be concise  "})
        assert parts == ["Special Instructions: Be concise"]

    @patch("app.utils.user_preferences_utils.log")
    def test_unknown_response_style_used_as_is(self, mock_log: Any) -> None:
        parts = build_user_context_parts({"response_style": "academic"})
        assert parts == ["Communication Style: academic"]

    @patch("app.utils.user_preferences_utils.log")
    def test_profession_whitespace_only_ignored(self, mock_log: Any) -> None:
        # Profession "   " is truthy so it enters the branch,
        # but format_profession_for_display("   ") returns "" which is falsy
        parts = build_user_context_parts({"profession": "   "})
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_long_profession_still_included(self, mock_log: Any) -> None:
        # build_user_context_parts does NOT enforce length limits
        long_profession = "a" * 100
        parts = build_user_context_parts({"profession": long_profession})
        assert len(parts) == 1
        assert parts[0] == f"User Profession: {long_profession.title()}"

    @patch("app.utils.user_preferences_utils.log")
    def test_long_custom_instructions_still_included(self, mock_log: Any) -> None:
        # build_user_context_parts does NOT enforce length limits
        long_instructions = "x" * 1000
        parts = build_user_context_parts({"custom_instructions": long_instructions})
        assert len(parts) == 1
        assert parts[0] == f"Special Instructions: {long_instructions}"


# ---------------------------------------------------------------------------
# format_user_preferences_for_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatUserPreferencesForAgent:
    @patch("app.utils.user_preferences_utils.log")
    def test_none_returns_none(self, mock_log: Any) -> None:
        assert format_user_preferences_for_agent(None) is None  # type: ignore[arg-type]

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_dict_returns_none(self, mock_log: Any) -> None:
        assert format_user_preferences_for_agent({}) is None

    @patch("app.utils.user_preferences_utils.log")
    def test_valid_preferences_returns_joined_string(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "designer",
            "response_style": "detailed",
            "custom_instructions": "Use visual examples",
        }
        result = format_user_preferences_for_agent(preferences)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "User Profession: Designer"
        assert (
            lines[1]
            == "Communication Style: Provide detailed and comprehensive responses"
        )
        assert lines[2] == "Special Instructions: Use visual examples"

    @patch("app.utils.user_preferences_utils.log")
    def test_single_preference_returns_string(self, mock_log: Any) -> None:
        result = format_user_preferences_for_agent({"profession": "engineer"})
        assert result == "User Profession: Engineer"

    @patch("app.utils.user_preferences_utils.log")
    def test_all_empty_values_returns_none(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "",
            "response_style": "",
            "custom_instructions": "",
        }
        result = format_user_preferences_for_agent(preferences)
        assert result is None

    @patch("app.utils.user_preferences_utils.log")
    def test_all_none_values_returns_none(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": None,
            "response_style": None,
            "custom_instructions": None,
        }
        result = format_user_preferences_for_agent(preferences)
        assert result is None

    @patch("app.utils.user_preferences_utils.log")
    def test_exception_in_build_returns_none(self, mock_log: Any) -> None:
        with patch(
            "app.utils.user_preferences_utils.build_user_context_parts",
            side_effect=RuntimeError("unexpected"),
        ):
            result = format_user_preferences_for_agent({"profession": "doctor"})
            assert result is None


# ---------------------------------------------------------------------------
# validate_user_preferences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateUserPreferences:
    @patch("app.utils.user_preferences_utils.log")
    def test_valid_data_all_fields(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "data scientist",
            "response_style": "brief",
            "custom_instructions": "Use code examples",
        }
        result = validate_user_preferences(preferences)
        assert result == {
            "profession": "data scientist",
            "response_style": "brief",
            "custom_instructions": "Use code examples",
        }

    @patch("app.utils.user_preferences_utils.log")
    def test_profession_too_long_excluded(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "a" * 51,
            "response_style": "brief",
        }
        result = validate_user_preferences(preferences)
        assert "profession" not in result
        assert result["response_style"] == "brief"

    @patch("app.utils.user_preferences_utils.log")
    def test_profession_at_max_length_included(self, mock_log: Any) -> None:
        profession_50 = "a" * 50
        result = validate_user_preferences({"profession": profession_50})
        assert result["profession"] == profession_50

    @patch("app.utils.user_preferences_utils.log")
    def test_custom_instructions_too_long_excluded(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "custom_instructions": "x" * 501,
            "response_style": "casual",
        }
        result = validate_user_preferences(preferences)
        assert "custom_instructions" not in result
        assert result["response_style"] == "casual"

    @patch("app.utils.user_preferences_utils.log")
    def test_custom_instructions_at_max_length_included(self, mock_log: Any) -> None:
        instructions_500 = "x" * 500
        result = validate_user_preferences({"custom_instructions": instructions_500})
        assert result["custom_instructions"] == instructions_500

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_strings_excluded(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "",
            "response_style": "",
            "custom_instructions": "",
        }
        result = validate_user_preferences(preferences)
        assert result == {}

    @patch("app.utils.user_preferences_utils.log")
    def test_whitespace_only_profession_excluded(self, mock_log: Any) -> None:
        result = validate_user_preferences({"profession": "   "})
        assert "profession" not in result

    @patch("app.utils.user_preferences_utils.log")
    def test_whitespace_only_response_style_excluded(self, mock_log: Any) -> None:
        result = validate_user_preferences({"response_style": "   "})
        assert "response_style" not in result

    @patch("app.utils.user_preferences_utils.log")
    def test_whitespace_only_custom_instructions_excluded(self, mock_log: Any) -> None:
        result = validate_user_preferences({"custom_instructions": "   "})
        assert "custom_instructions" not in result

    @patch("app.utils.user_preferences_utils.log")
    def test_none_input_returns_empty_dict(self, mock_log: Any) -> None:
        # None has no .get() method, so the try/except catches AttributeError
        result = validate_user_preferences(None)  # type: ignore[arg-type]
        assert result == {}

    @patch("app.utils.user_preferences_utils.log")
    def test_none_values_excluded(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": None,
            "response_style": None,
            "custom_instructions": None,
        }
        result = validate_user_preferences(preferences)
        assert result == {}

    @patch("app.utils.user_preferences_utils.log")
    def test_values_are_stripped(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "  doctor  ",
            "response_style": "  brief  ",
            "custom_instructions": "  Be concise  ",
        }
        result = validate_user_preferences(preferences)
        assert result["profession"] == "doctor"
        assert result["response_style"] == "brief"
        assert result["custom_instructions"] == "Be concise"

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_dict_returns_empty_dict(self, mock_log: Any) -> None:
        result = validate_user_preferences({})
        assert result == {}

    @patch("app.utils.user_preferences_utils.log")
    def test_extra_keys_ignored(self, mock_log: Any) -> None:
        preferences: Dict[str, Any] = {
            "profession": "nurse",
            "unknown_key": "should be ignored",
            "another": 42,
        }
        result = validate_user_preferences(preferences)
        assert result == {"profession": "nurse"}
        assert "unknown_key" not in result
        assert "another" not in result

    @patch("app.utils.user_preferences_utils.log")
    def test_profession_stripped_then_length_checked(self, mock_log: Any) -> None:
        # 48 chars + 4 spaces of padding = 52 total, but after strip it's 48 (valid)
        padded = "  " + "a" * 48 + "  "
        result = validate_user_preferences({"profession": padded})
        assert result["profession"] == "a" * 48

    @patch("app.utils.user_preferences_utils.log")
    def test_profession_stripped_still_too_long(self, mock_log: Any) -> None:
        # 51 chars + padding, after strip still 51 (too long)
        padded = " " + "b" * 51 + " "
        result = validate_user_preferences({"profession": padded})
        assert "profession" not in result


# ---------------------------------------------------------------------------
# get_user_preference_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserPreferenceSummary:
    def test_empty_dict_returns_no_preferences(self) -> None:
        assert get_user_preference_summary({}) == "No preferences set"

    def test_none_returns_no_preferences(self) -> None:
        assert get_user_preference_summary(None) == "No preferences set"  # type: ignore[arg-type]

    def test_with_profession_only(self) -> None:
        result = get_user_preference_summary({"profession": "engineer"})
        assert "Profession: engineer..." in result

    def test_with_style_only(self) -> None:
        result = get_user_preference_summary({"response_style": "brief"})
        assert result == "Style: brief"

    def test_with_custom_instructions_only(self) -> None:
        result = get_user_preference_summary({"custom_instructions": "Be concise"})
        assert result == "Has custom instructions"

    def test_all_present(self) -> None:
        preferences: Dict[str, Any] = {
            "profession": "designer",
            "response_style": "casual",
            "custom_instructions": "Use examples",
        }
        result = get_user_preference_summary(preferences)
        parts = result.split(" | ")
        assert len(parts) == 3
        assert parts[0] == "Profession: designer..."
        assert parts[1] == "Style: casual"
        assert parts[2] == "Has custom instructions"

    def test_profession_truncated_at_20_chars(self) -> None:
        long_profession = "a" * 30
        result = get_user_preference_summary({"profession": long_profession})
        # The function does profession[:20] + "..."
        assert result == f"Profession: {'a' * 20}..."

    def test_short_profession_still_gets_ellipsis(self) -> None:
        # The function always appends "..." regardless of length
        result = get_user_preference_summary({"profession": "dev"})
        assert result == "Profession: dev..."

    def test_all_none_values_returns_no_preferences(self) -> None:
        preferences: Dict[str, Any] = {
            "profession": None,
            "response_style": None,
            "custom_instructions": None,
        }
        assert get_user_preference_summary(preferences) == "No preferences set"

    def test_all_empty_values_returns_no_preferences(self) -> None:
        preferences: Dict[str, Any] = {
            "profession": "",
            "response_style": "",
            "custom_instructions": "",
        }
        assert get_user_preference_summary(preferences) == "No preferences set"

    def test_pipe_separator_between_parts(self) -> None:
        preferences: Dict[str, Any] = {
            "profession": "nurse",
            "response_style": "detailed",
        }
        result = get_user_preference_summary(preferences)
        assert " | " in result
        assert result == "Profession: nurse... | Style: detailed"

    def test_profession_exactly_20_chars(self) -> None:
        profession_20 = "a" * 20
        result = get_user_preference_summary({"profession": profession_20})
        assert result == f"Profession: {profession_20}..."
