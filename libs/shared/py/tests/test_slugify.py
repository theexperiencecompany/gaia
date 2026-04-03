"""Tests for shared.py.utils.slugify — various inputs, unicode, max_length, edge cases."""

import pytest

from shared.py.utils.slugify import slugify


# ---------------------------------------------------------------------------
# Basic conversion
# ---------------------------------------------------------------------------


class TestSlugifyBasic:
    """Test basic slugification behavior."""

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("Daily Email Summary", "daily-email-summary"),
            ("Hello World", "hello-world"),
            ("simple", "simple"),
            ("UPPERCASE", "uppercase"),
            ("MiXeD CaSe", "mixed-case"),
        ],
        ids=["multi-word", "two-word", "single-word", "all-upper", "mixed-case"],
    )
    def test_basic_conversion(self, input_text: str, expected: str):
        assert slugify(input_text) == expected


# ---------------------------------------------------------------------------
# Special characters
# ---------------------------------------------------------------------------


class TestSlugifySpecialChars:
    """Test handling of special characters and common separators."""

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("Gmail -> Slack Alerts", "gmail-slack-alerts"),
            ("  Spaces & Special! Chars ", "spaces-special-chars"),
            ("foo/bar/baz", "foo-bar-baz"),
            ("A + B = C", "a-b-c"),
            ("hello@world.com", "helloworld-com"),
            ("price: $100", "price-100"),
            ("50% off!", "50-off"),
            ("foo\\bar", "foo-bar"),
            ("pipe|separated", "pipe-separated"),
            ("hash#tag", "hash-tag"),
            ("caret^up", "caret-up"),
            ("star*power", "star-power"),
            ("less<more>equal", "less-more-equal"),
        ],
        ids=[
            "arrow",
            "spaces-and-special",
            "slashes",
            "plus-equals",
            "at-sign",
            "dollar",
            "percent",
            "backslash",
            "pipe",
            "hash",
            "caret",
            "star",
            "angle-brackets",
        ],
    )
    def test_special_characters(self, input_text: str, expected: str):
        assert slugify(input_text) == expected


# ---------------------------------------------------------------------------
# Unicode handling
# ---------------------------------------------------------------------------


class TestSlugifyUnicode:
    """Test unicode normalization (NFKD decomposition + ASCII encoding)."""

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("cafe\u0301", "cafe"),  # e + combining acute -> e
            ("na\u00efve", "naive"),  # i with diaeresis
            ("r\u00e9sum\u00e9", "resume"),
            ("\u00fc\u00f6\u00e4", "uoa"),  # German umlauts
            ("ni\u00f1o", "nino"),  # Spanish n-tilde
            ("Caf\u00e9 Latt\u00e9", "cafe-latte"),
        ],
        ids=["combining-acute", "diaeresis", "resume-accents", "umlauts", "n-tilde", "cafe-latte"],
    )
    def test_unicode_normalization(self, input_text: str, expected: str):
        assert slugify(input_text) == expected

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("\u4f60\u597d\u4e16\u754c", ""),  # Chinese characters stripped
            ("\u0410\u0411\u0412", ""),  # Cyrillic stripped
            ("\u3053\u3093\u306b\u3061\u306f", ""),  # Japanese hiragana stripped
            ("\ud83d\ude00\ud83d\ude01", ""),  # Emoji stripped
        ],
        ids=["chinese", "cyrillic", "japanese", "emoji"],
    )
    def test_non_latin_stripped(self, input_text: str, expected: str):
        assert slugify(input_text) == expected


# ---------------------------------------------------------------------------
# Whitespace and hyphen handling
# ---------------------------------------------------------------------------


class TestSlugifyWhitespace:
    """Test whitespace and hyphen collapsing."""

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("  leading", "leading"),
            ("trailing  ", "trailing"),
            ("  both  ", "both"),
            ("multiple   spaces   here", "multiple-spaces-here"),
            ("already-hyphenated", "already-hyphenated"),
            ("double--hyphen", "double-hyphen"),
            ("triple---hyphen", "triple-hyphen"),
            ("-leading-hyphen", "leading-hyphen"),
            ("trailing-hyphen-", "trailing-hyphen"),
            ("-both-sides-", "both-sides"),
            ("tabs\there", "tabshere"),
            ("newlines\nhere", "newlineshere"),
        ],
        ids=[
            "leading-space",
            "trailing-space",
            "both-spaces",
            "multiple-spaces",
            "already-hyphenated",
            "double-hyphen",
            "triple-hyphen",
            "leading-hyphen",
            "trailing-hyphen",
            "both-hyphens",
            "tabs",
            "newlines",
        ],
    )
    def test_whitespace_and_hyphens(self, input_text: str, expected: str):
        assert slugify(input_text) == expected


# ---------------------------------------------------------------------------
# max_length
# ---------------------------------------------------------------------------


class TestSlugifyMaxLength:
    """Test the max_length parameter and word-boundary truncation."""

    def test_default_max_length_is_80(self):
        long_text = "a " * 100  # 200 chars -> "a-a-a-a-..."
        result = slugify(long_text)
        assert len(result) <= 80

    def test_custom_max_length(self):
        result = slugify("one two three four five six seven eight", max_length=15)
        assert len(result) <= 15

    def test_truncates_at_word_boundary(self):
        result = slugify("hello world foo bar baz", max_length=12)
        # "hello-world-" is 12 chars; should split at last hyphen -> "hello-world"
        assert result == "hello-world"

    def test_short_text_unaffected(self):
        result = slugify("short", max_length=80)
        assert result == "short"

    def test_exact_length_no_truncation(self):
        # "ab-cd" is 5 chars
        result = slugify("ab cd", max_length=5)
        assert result == "ab-cd"

    def test_max_length_one(self):
        result = slugify("abc", max_length=1)
        # "abc" is 3 chars; truncated to 1 -> "a"; rsplit("-",1)[0] -> "a"
        assert result == "a"

    def test_max_length_very_large(self):
        result = slugify("hello world", max_length=10000)
        assert result == "hello-world"

    def test_hyphen_at_max_length_boundary(self):
        # "one-two-three" is 13 chars; max_length=7 -> "one-two"[:7] = "one-two", rsplit -> "one-two"
        result = slugify("one two three", max_length=7)
        assert result == "one-two"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSlugifyEdgeCases:
    """Test edge cases and degenerate inputs."""

    def test_empty_string(self):
        assert slugify("") == ""

    def test_only_spaces(self):
        assert slugify("   ") == ""

    def test_only_special_chars(self):
        assert slugify("!@#$%^&*()") == ""

    def test_only_hyphens(self):
        assert slugify("---") == ""

    def test_single_char(self):
        assert slugify("a") == "a"

    def test_single_number(self):
        assert slugify("7") == "7"

    def test_numbers_preserved(self):
        assert slugify("version 2.0.1") == "version-201"

    def test_mixed_numbers_and_letters(self):
        assert slugify("abc123def") == "abc123def"

    def test_dots_stripped(self):
        assert slugify("file.name.txt") == "filenametxt"

    def test_underscores_stripped(self):
        assert slugify("snake_case_name") == "snakecasename"

    def test_parentheses_stripped(self):
        assert slugify("hello (world)") == "hello-world"

    def test_brackets_stripped(self):
        assert slugify("test [value]") == "test-value"

    def test_question_and_exclamation(self):
        assert slugify("what? why!") == "what-why"

    def test_comma_stripped(self):
        assert slugify("one, two, three") == "one-two-three"

    def test_colon_stripped(self):
        assert slugify("key: value") == "key-value"

    def test_semicolon_stripped(self):
        assert slugify("a; b; c") == "a-b-c"

    def test_quotes_stripped(self):
        assert slugify("it's a \"test\"") == "its-a-test"

    def test_very_long_single_word(self):
        word = "a" * 200
        result = slugify(word, max_length=80)
        # Single word, no hyphen to split on -> rsplit returns the whole truncated string
        assert len(result) <= 80
        assert result == "a" * 80


# ---------------------------------------------------------------------------
# Regression / docstring examples
# ---------------------------------------------------------------------------


class TestSlugifyDocstringExamples:
    """Verify the examples from the docstring produce the expected output."""

    @pytest.mark.parametrize(
        ("input_text", "expected"),
        [
            ("Daily Email Summary", "daily-email-summary"),
            ("Gmail -> Slack Alerts", "gmail-slack-alerts"),
            ("  Spaces & Special! Chars ", "spaces-special-chars"),
        ],
        ids=["docstring-1", "docstring-2", "docstring-3"],
    )
    def test_docstring_examples(self, input_text: str, expected: str):
        assert slugify(input_text) == expected
