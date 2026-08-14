"""Unit tests for ``app.helpers.integration_helpers`` slug parsing."""

from app.helpers.integration_helpers import parse_integration_slug


def test_plain_slug_parses_with_no_category_or_shortid() -> None:
    result = parse_integration_slug("gmail")
    assert result == {"name_part": "gmail", "category": None, "shortid": None}


def test_legacy_six_char_hash_suffix_is_extracted() -> None:
    result = parse_integration_slug("gmail-a1b2c3")
    assert result["name_part"] == "gmail"
    assert result["shortid"] == "a1b2c3"
    assert result["category"] is None


def test_mcp_slug_splits_name_and_category() -> None:
    result = parse_integration_slug("google-mcp-calendar")
    assert result["name_part"] == "google"
    assert result["category"] == "calendar"
    assert result["shortid"] is None


def test_mcp_slug_with_legacy_hash() -> None:
    result = parse_integration_slug("notion-mcp-docs-7f3a9b")
    assert result["name_part"] == "notion"
    assert result["category"] == "docs"
    assert result["shortid"] == "7f3a9b"


def test_hash_like_category_is_not_mistaken_for_shortid() -> None:
    """A 6-char trailing segment is only a shortid when it's the final piece
    and there's no mcp marker."""
    result = parse_integration_slug("slack")
    assert result["shortid"] is None
