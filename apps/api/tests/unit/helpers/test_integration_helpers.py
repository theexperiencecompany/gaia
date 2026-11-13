"""Unit tests for app.helpers.integration_helpers."""

from datetime import UTC, datetime

import pytest

from app.helpers.integration_helpers import (
    dedup_server_url_key,
    format_public_integration_response,
    normalize_server_url,
)
from app.helpers.slug_helpers import generate_integration_slug
from app.models.integration_models import IntegrationWithCreator
from app.models.oauth_models import IntegrationContent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://mcp.sentry.dev/mcp", "https://mcp.sentry.dev/mcp"),
        # trailing slash stripped
        ("https://mcp.sentry.dev/mcp/", "https://mcp.sentry.dev/mcp"),
        # ONLY the trailing slash is stripped — a real path char before it (and
        # its case) survives, even an uppercase 'X'.
        ("https://x.example/mcpX/", "https://x.example/mcpX"),
        # scheme + host lowercased, path case preserved
        ("HTTPS://MCP.Sentry.DEV/McP", "https://mcp.sentry.dev/McP"),
        # fragment dropped, query preserved
        ("https://x.example/mcp?v=2#frag", "https://x.example/mcp?v=2"),
        # surrounding whitespace stripped
        ("  https://x.example/mcp  ", "https://x.example/mcp"),
    ],
)
def test_normalize_server_url(raw, expected):
    assert normalize_server_url(raw) == expected


def test_normalize_server_url_dedupes_case_and_slash_variants():
    """The whole point: two spellings of one server collapse to one key."""
    a = normalize_server_url("https://MCP.Sentry.dev/mcp/")
    b = normalize_server_url("https://mcp.sentry.dev/mcp")
    assert a == b


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://mcp.sentry.dev/mcp", "https://mcp.sentry.dev/mcp"),
        ("https://mcp.sentry.dev/mcp/", "https://mcp.sentry.dev/mcp"),
        ("HTTPS://MCP.Sentry.DEV/McP", "https://mcp.sentry.dev/McP"),
    ],
)
def test_dedup_server_url_key_matches_normalize(raw, expected):
    assert dedup_server_url_key(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_dedup_server_url_key_blank_is_none(raw):
    """Blank keys are None, never "" — an empty key would collide under the per-creator unique index."""
    assert dedup_server_url_key(raw) is None


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
    """The cap cuts mid-word otherwise; the slug must break after the last hyphen and never exceed max_length."""
    slug = generate_integration_slug("a" * 100, "b" * 30, max_length=50)

    assert slug == "a" * 40 + "-mcp"
    assert len(slug) <= 50


def test_slug_cap_cuts_the_name_at_40_chars_even_when_the_result_fits() -> None:
    """The name segment has its own 40-char cap, independent of max_length."""
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
    """An empty name yields a leading hyphen; rstrip('-') cleans the edges of the finished slug."""
    assert generate_integration_slug("", "cccccccccc", max_length=8) == "-mcp"


def test_a_trailing_hyphen_in_the_name_passes_through_below_the_cap() -> None:
    """Below the cap nothing is re-hyphened: 'ab-' keeps its hyphen verbatim."""
    assert generate_integration_slug("ab-", "c") == "ab-mcp-c"


def test_truncation_window_starting_on_a_hyphen_is_kept_verbatim() -> None:
    """An empty name puts the only in-window hyphen at index 0, so the cut keeps it (last_hyphen > 0 is false)."""
    assert generate_integration_slug("", "cc", max_length=3) == "-mc"


def test_truncation_cutting_right_after_a_one_char_name() -> None:
    """With the window's last hyphen at index 1 the cut lands before it, keeping only the one-char name."""
    assert generate_integration_slug("a", "cc", max_length=4) == "a"


def test_empty_category_leaves_a_trailing_hyphen_for_rstrip() -> None:
    """An empty category ends the raw slug on '-'; rstrip('-') removes it."""
    assert generate_integration_slug("ab-", "") == "ab-mcp"


def test_public_response_carries_every_published_field() -> None:
    """Each stored field reaches the public detail page under its own name."""
    published = datetime(2026, 3, 1, tzinfo=UTC)
    integration = IntegrationWithCreator.model_validate(
        {
            "integration_id": "int-1",
            "name": "My Tool",
            "description": "Does things",
            "category": "developer",
            "managed_by": "mcp",
            "is_public": True,
            "slug": "my-tool-mcp-developer",
            "mcp_config": {
                "server_url": "https://mcp.example.com/mcp",
                "requires_auth": True,
                "auth_type": "bearer",
            },
            "creator": {"name": "Ada", "picture": "https://pics.example/ada.png"},
            "icon_url": "https://icons.example/tool.png",
            "tools": [{"name": "t1", "description": "does t1"}],
            "clone_count": 3,
            "published_at": published,
            "content": {"use_cases": ["triage"]},
        }
    )

    result = format_public_integration_response(integration)

    assert result.integration_id == "int-1"
    assert result.slug == "my-tool-mcp-developer"
    assert result.icon_url == "https://icons.example/tool.png"
    assert result.creator is not None
    assert result.creator.model_dump() == {"name": "Ada", "picture": "https://pics.example/ada.png"}
    assert result.mcp_config is not None
    assert result.mcp_config.model_dump() == {
        "server_url": "https://mcp.example.com/mcp",
        "requires_auth": True,
        "auth_type": "bearer",
    }
    assert [t.model_dump() for t in result.tools] == [
        {"name": "t1", "description": "does t1", "destructive": False}
    ]
    assert result.clone_count == 3
    assert result.tool_count == 1
    assert result.published_at == published
    assert result.source == "custom"
    assert result.content == IntegrationContent(use_cases=["triage"])


def test_default_cap_is_60_chars() -> None:
    """Without an explicit max_length the cap is 60, not 61."""
    slug = generate_integration_slug("n" * 100, "c" * 20)

    assert len(slug) == 65
    assert slug == "n" * 40 + "-mcp-" + "c" * 20
