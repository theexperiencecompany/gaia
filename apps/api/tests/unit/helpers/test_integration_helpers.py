"""Unit tests for app.helpers.integration_helpers."""

import pytest

from app.helpers.integration_helpers import generate_integration_slug


@pytest.mark.parametrize(
    ("name", "category", "expected"),
    [
        # Below max_length: nothing is truncated or re-hyphened.
        ("OpenAI", "ai", "openai-mcp-ai"),
        (
            "Zapier Marketing Automation Suite",
            "marketing",
            "zapier-marketing-automation-suite-mcp-marketing",
        ),
    ],
)
def test_a_slug_under_the_cap_passes_through_verbatim(
    name: str, category: str, expected: str
) -> None:
    assert generate_integration_slug(name, category) == expected


def test_an_over_long_slug_is_truncated_at_the_last_complete_word() -> None:
    """The cap cuts mid-word otherwise, so the slug breaks after the last hyphen
    the truncated text still holds — and never exceeds max_length."""
    slug = generate_integration_slug("a" * 100, "b" * 30, max_length=50)

    assert slug == "a" * 40 + "-mcp"
    assert len(slug) <= 50


def test_slug_cap_cuts_the_name_at_40_chars_even_when_the_result_fits() -> None:
    """The name segment is slugified with its own 40-char cap, independent of
    the overall max_length — a 45-char name contributes exactly 40 chars."""
    slug = generate_integration_slug("x" * 45, "c", max_length=60)

    assert slug == "x" * 40 + "-mcp-c"


def test_category_segment_is_capped_at_20_chars() -> None:
    """The category segment never exceeds its own 20-char slugify cap."""
    assert generate_integration_slug("n", "c" * 40) == "n-mcp-" + "c" * 20


def test_slug_exactly_at_max_length_is_not_touched() -> None:
    """A slug equal to the cap takes neither truncation branch (>= would)."""
    category = "c" * 20
    exact = f"n-mcp-{category}"
    assert generate_integration_slug("n", category, max_length=len(exact)) == exact


def test_truncation_keeps_only_complete_words_up_to_the_cap() -> None:
    """Over-cap slugs are cut back to the last hyphen that fits the cap."""
    slug = generate_integration_slug("alpha-beta-gamma-delta-epsilon-zeta", "tools", max_length=30)

    assert slug == "alpha-beta-gamma-delta"
    assert len(slug) <= 30


def test_leading_and_trailing_hyphens_are_stripped_from_the_final_slug() -> None:
    """An empty name yields a leading hyphen and truncation can end on one —
    rstrip('-') cleans the edges of the finished slug."""
    assert generate_integration_slug("", "cccccccccc", max_length=8) == "-mcp"


def test_a_trailing_hyphen_in_the_name_passes_through_below_the_cap() -> None:
    """Below the cap nothing is re-hyphened: 'ab-' keeps its hyphen verbatim."""
    assert generate_integration_slug("ab-", "c") == "ab-mcp-c"


def test_truncation_window_starting_on_a_hyphen_is_kept_verbatim() -> None:
    """An empty name puts the slug's only in-window hyphen at index 0: the cut
    keeps it (last_hyphen > 0 is false, so the raw window wins)."""
    assert generate_integration_slug("", "cc", max_length=3) == "-mc"


def test_truncation_cutting_right_after_a_one_char_name() -> None:
    """With the window's last hyphen at index 1 the cut lands before it —
    a one-character name survives, the rest is dropped."""
    assert generate_integration_slug("a", "cc", max_length=4) == "a"


def test_empty_category_leaves_a_trailing_hyphen_for_rstrip() -> None:
    """An empty category ends the raw slug on '-'; rstrip('-') removes it."""
    assert generate_integration_slug("ab-", "") == "ab-mcp"


def test_default_cap_is_60_chars() -> None:
    """Without an explicit max_length the cap is 60: a 66-char raw slug comes
    back truncated to the 65-char word boundary — not passed through at 61."""
    slug = generate_integration_slug("n" * 100, "c" * 20)

    assert len(slug) == 65
    assert slug == "n" * 40 + "-mcp-" + "c" * 20
