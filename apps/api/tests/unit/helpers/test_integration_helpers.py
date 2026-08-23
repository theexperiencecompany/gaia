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
