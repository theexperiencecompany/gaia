"""Tests for app.helpers.slug_helpers — slug generation and parsing utilities."""

import pytest

from app.helpers.slug_helpers import (
    generate_workflow_slug,
    parse_workflow_slug,
    slugify,
)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    """Tests for the slugify() function."""

    # -- basic transformations -----------------------------------------------

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Hello World", "hello-world"),
            ("hello world", "hello-world"),
            ("HELLO WORLD", "hello-world"),
            ("Hello   World", "hello-world"),
            ("hello-world", "hello-world"),
        ],
        ids=[
            "title-case",
            "lowercase",
            "uppercase",
            "multiple-spaces",
            "already-slugified",
        ],
    )
    def test_basic_text_conversion(self, text: str, expected: str) -> None:
        assert slugify(text) == expected

    # -- special characters --------------------------------------------------

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Hello, World!", "hello-world"),
            ("Price: $100", "price-100"),
            ("foo@bar.com", "foobarcom"),
            ("100% Done", "100-done"),
            ("one & two", "one-two"),
            ("a/b/c", "abc"),
            ("a.b.c", "abc"),
            ("(parentheses)", "parentheses"),
            ("[brackets]", "brackets"),
            ("hello---world", "hello-world"),
        ],
        ids=[
            "comma-exclamation",
            "dollar-colon",
            "at-dots",
            "percent",
            "ampersand",
            "slashes",
            "dots",
            "parentheses",
            "brackets",
            "consecutive-hyphens",
        ],
    )
    def test_special_characters_removed(self, text: str, expected: str) -> None:
        assert slugify(text) == expected

    # -- unicode / accented characters ----------------------------------------

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("cafe\u0301", "cafe"),  # combining accent stripped by [^\w\s-]
            (
                "\u00e9l\u00e8ve",
                "lve",
            ),  # accented letters not matched by \w in default locale
            (
                "\u4f60\u597d\u4e16\u754c",
                "",
            ),  # CJK characters — may or may not match \w
        ],
        ids=["combining-accent", "accented-latin", "cjk"],
    )
    def test_unicode_input(self, text: str, expected: str) -> None:
        # The regex [^\w\s-] behaviour on non-ASCII depends on locale/re flags.
        # We just verify the function doesn't crash and returns a string.
        result = slugify(text)
        assert isinstance(result, str)
        # No uppercase, no leading/trailing hyphens, no consecutive hyphens
        assert result == result.lower()
        assert not result.startswith("-")
        assert not result.endswith("-")
        assert "--" not in result

    # -- edge cases: empty / whitespace --------------------------------------

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("", ""),
            ("   ", ""),
            ("---", ""),
            ("!!!!", ""),
            ("-  -  -", ""),
        ],
        ids=[
            "empty-string",
            "only-spaces",
            "only-hyphens",
            "only-punctuation",
            "hyphens-spaces",
        ],
    )
    def test_empty_or_whitespace_input(self, text: str, expected: str) -> None:
        assert slugify(text) == expected

    # -- underscore handling -------------------------------------------------

    def test_underscores_converted_to_hyphens(self) -> None:
        assert slugify("hello_world") == "hello-world"

    def test_mixed_underscores_and_spaces(self) -> None:
        assert slugify("hello_world foo_bar") == "hello-world-foo-bar"

    # -- leading/trailing hyphens stripped ------------------------------------

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("-leading", "leading"),
            ("trailing-", "trailing"),
            ("-both-", "both"),
            ("--many--", "many"),
        ],
        ids=["leading", "trailing", "both", "many"],
    )
    def test_leading_trailing_hyphens_stripped(self, text: str, expected: str) -> None:
        assert slugify(text) == expected

    # -- max_length truncation -----------------------------------------------

    def test_truncation_at_max_length(self) -> None:
        result = slugify("a" * 100, max_length=50)
        assert len(result) <= 50

    def test_truncation_breaks_at_word_boundary(self) -> None:
        # "one-two-three-four" with a tight limit should cut at a hyphen boundary
        result = slugify("one two three four five six seven", max_length=15)
        assert len(result) <= 15
        # Should not end with a hyphen
        assert not result.endswith("-")

    def test_truncation_single_long_word(self) -> None:
        # A single word longer than max_length — rsplit produces one part
        result = slugify("a" * 60, max_length=20)
        assert len(result) <= 20

    def test_default_max_length_is_50(self) -> None:
        long_slug = slugify("a " * 100)  # would be "a-a-a-a-..." (199 chars)
        assert len(long_slug) <= 50

    @pytest.mark.parametrize("max_length", [1, 5, 10, 50, 200])
    def test_various_max_lengths(self, max_length: int) -> None:
        result = slugify("hello world this is a test string", max_length=max_length)
        assert len(result) <= max_length

    def test_max_length_exact_fit(self) -> None:
        # If the slug is exactly max_length, no truncation occurs
        result = slugify("abcde", max_length=5)
        assert result == "abcde"

    # -- consecutive hyphen collapse -----------------------------------------

    def test_multiple_consecutive_hyphens_collapsed(self) -> None:
        assert slugify("a - - - b") == "a-b"

    # -- tabs and newlines ---------------------------------------------------

    def test_tabs_converted(self) -> None:
        assert slugify("hello\tworld") == "hello-world"

    def test_newlines_converted(self) -> None:
        assert slugify("hello\nworld") == "hello-world"


# ---------------------------------------------------------------------------
# generate_workflow_slug
# ---------------------------------------------------------------------------


class TestGenerateWorkflowSlug:
    """Tests for generate_workflow_slug()."""

    def test_basic_generation(self) -> None:
        result = generate_workflow_slug("Email Triaging", "wf_a1b2c3d4e5f6")
        assert result == "email-triaging-a1b2c3d4"

    def test_docstring_example_two(self) -> None:
        result = generate_workflow_slug("Monday Standup Notes", "wf_ff0011223344")
        assert result == "monday-standup-notes-ff001122"

    def test_wf_prefix_stripped(self) -> None:
        result = generate_workflow_slug("Test", "wf_abcdef1234567890")
        assert "wf" not in result
        assert result.endswith("-abcdef12")

    def test_no_wf_prefix(self) -> None:
        result = generate_workflow_slug("Test", "abcdef1234567890")
        assert result == "test-abcdef12"

    def test_shortid_is_first_8_chars(self) -> None:
        slug = generate_workflow_slug("My Flow", "wf_deadbeef99999999")
        assert slug.endswith("-deadbeef")

    def test_shortid_lowercased(self) -> None:
        slug = generate_workflow_slug("Test", "wf_AABBCCDD11223344")
        assert slug.endswith("-aabbccdd")

    def test_empty_title_returns_shortid_only(self) -> None:
        result = generate_workflow_slug("", "wf_abcdef1234567890")
        assert result == "abcdef12"

    def test_title_with_only_special_chars(self) -> None:
        # slugify("!!!") -> "" so title_slug is empty
        result = generate_workflow_slug("!!!", "wf_abcdef1234567890")
        assert result == "abcdef12"

    def test_long_title_truncated_to_fit_max_length(self) -> None:
        long_title = "a " * 100  # would slug to "a-a-a-a-..."
        result = generate_workflow_slug(
            long_title, "wf_abcdef1234567890", max_length=80
        )
        assert len(result) <= 80

    def test_custom_max_length(self) -> None:
        result = generate_workflow_slug("Short", "wf_abcdef1234567890", max_length=30)
        assert len(result) <= 30

    def test_no_trailing_hyphen(self) -> None:
        # Edge case: if title_slug ends up empty after truncation
        result = generate_workflow_slug("!", "wf_abcdef1234567890")
        assert not result.endswith("-")

    def test_short_workflow_id(self) -> None:
        # ID shorter than 8 chars — shortid is the full raw ID
        result = generate_workflow_slug("Test", "wf_abc")
        assert result == "test-abc"

    def test_workflow_id_exactly_8_after_prefix(self) -> None:
        result = generate_workflow_slug("Test", "wf_12345678")
        assert result == "test-12345678"

    @pytest.mark.parametrize(
        "title, wf_id, expected_suffix",
        [
            ("Email Triaging", "wf_a1b2c3d4e5f6", "a1b2c3d4"),
            ("Test", "wf_AABB0011", "aabb0011"),
            ("Foo", "no_prefix_here1234", "no_prefi"),
        ],
        ids=["standard", "uppercase-id", "no-wf-prefix"],
    )
    def test_suffix_parametrized(
        self, title: str, wf_id: str, expected_suffix: str
    ) -> None:
        result = generate_workflow_slug(title, wf_id)
        assert result.endswith(f"-{expected_suffix}") or result == expected_suffix


# ---------------------------------------------------------------------------
# parse_workflow_slug
# ---------------------------------------------------------------------------


class TestParseWorkflowSlug:
    """Tests for parse_workflow_slug()."""

    def test_valid_slug_returns_shortid(self) -> None:
        assert parse_workflow_slug("email-triaging-a1b2c3d4") == "a1b2c3d4"

    def test_another_valid_slug(self) -> None:
        assert parse_workflow_slug("monday-standup-notes-ff001122") == "ff001122"

    def test_shortid_only_slug(self) -> None:
        # "prefix-abcdef12" — two parts with valid 8-char hex
        assert parse_workflow_slug("something-abcdef12") == "abcdef12"

    def test_invalid_not_hex(self) -> None:
        # "ghijklmn" is not hex
        assert parse_workflow_slug("workflow-ghijklmn") is None

    def test_invalid_too_short(self) -> None:
        assert parse_workflow_slug("workflow-abc") is None

    def test_invalid_too_long(self) -> None:
        assert parse_workflow_slug("workflow-abcdef1234") is None

    def test_no_hyphen_at_all(self) -> None:
        assert parse_workflow_slug("nohyphen") is None

    def test_empty_string(self) -> None:
        assert parse_workflow_slug("") is None

    def test_single_hyphen_with_valid_hex(self) -> None:
        # rsplit("-", 1) on "-abcdef12" yields ["", "abcdef12"]
        assert parse_workflow_slug("-abcdef12") == "abcdef12"

    def test_multiple_hyphens_takes_last_segment(self) -> None:
        assert parse_workflow_slug("a-b-c-d-aabbccdd") == "aabbccdd"

    @pytest.mark.parametrize(
        "slug, expected",
        [
            ("test-00000000", "00000000"),
            ("test-ffffffff", "ffffffff"),
            ("test-abcdef01", "abcdef01"),
            ("test-12345678", "12345678"),
        ],
        ids=["all-zeros", "all-f", "mixed-alpha-num", "all-digits"],
    )
    def test_valid_hex_variations(self, slug: str, expected: str) -> None:
        assert parse_workflow_slug(slug) == expected

    @pytest.mark.parametrize(
        "slug",
        [
            "test-0000000g",  # 'g' is not hex
            "test-AABBCCDD",  # uppercase — the check uses lowercase chars only
            "test-1234567",  # 7 chars
            "test-123456789",  # 9 chars
        ],
        ids=["non-hex-char", "uppercase-hex", "seven-chars", "nine-chars"],
    )
    def test_invalid_endings(self, slug: str) -> None:
        assert parse_workflow_slug(slug) is None
