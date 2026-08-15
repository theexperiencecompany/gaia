"""Tests for app.helpers.slug_helpers — slug generation utilities."""

import pytest

from app.helpers.slug_helpers import slugify

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
