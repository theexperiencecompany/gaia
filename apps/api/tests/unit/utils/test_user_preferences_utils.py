"""Unit tests for user preferences utility functions."""

from typing import Any
from unittest.mock import patch

import pytest

from app.utils.user_preferences_utils import (
    build_user_context_parts,
    format_profession_for_display,
    format_response_style_instruction,
    format_user_preferences_for_agent,
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
        preferences: dict[str, Any] = {
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
        preferences: dict[str, Any] = {
            "profession": None,
            "response_style": None,
            "custom_instructions": None,
        }
        parts = build_user_context_parts(preferences)
        assert parts == []

    @patch("app.utils.user_preferences_utils.log")
    def test_empty_string_values_ignored(self, mock_log: Any) -> None:
        preferences: dict[str, Any] = {
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
        preferences: dict[str, Any] = {
            "profession": "designer",
            "response_style": "detailed",
            "custom_instructions": "Use visual examples",
        }
        result = format_user_preferences_for_agent(preferences)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "User Profession: Designer"
        assert lines[1] == "Communication Style: Provide detailed and comprehensive responses"
        assert lines[2] == "Special Instructions: Use visual examples"

    @patch("app.utils.user_preferences_utils.log")
    def test_single_preference_returns_string(self, mock_log: Any) -> None:
        result = format_user_preferences_for_agent({"profession": "engineer"})
        assert result == "User Profession: Engineer"

    @patch("app.utils.user_preferences_utils.log")
    def test_all_empty_values_returns_none(self, mock_log: Any) -> None:
        preferences: dict[str, Any] = {
            "profession": "",
            "response_style": "",
            "custom_instructions": "",
        }
        result = format_user_preferences_for_agent(preferences)
        assert result is None

    @patch("app.utils.user_preferences_utils.log")
    def test_all_none_values_returns_none(self, mock_log: Any) -> None:
        preferences: dict[str, Any] = {
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
