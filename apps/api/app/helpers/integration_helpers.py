"""Integration-specific helper functions."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import TYPE_CHECKING

from app.helpers.slug_helpers import slugify

if TYPE_CHECKING:
    # Import under TYPE_CHECKING only: integration_models imports this module for
    # generate_integration_slug, so a runtime import back would be circular.
    from app.models.integration_models import IntegrationWithCreator

# Stopwords filtered out of free-text integration/tool search queries.
SEARCH_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "with",
    "and",
    "or",
    "in",
    "on",
    "my",
}


_SLUG_STRIP_CHARS = "-"


def build_search_patterns(query: str) -> list[str]:
    """Split a query into individual lowercase words for flexible matching.

    E.g. "Render deployment" -> ["render", "deployment"], so "Render" still
    matches when the query is "Render deployment". Short and common words are
    dropped so they do not match everything.
    """
    words = re.split(r"[\s,;]+", query.lower())
    return [w for w in words if len(w) >= 2 and w not in SEARCH_STOPWORDS]


def build_search_matcher(query: str | None) -> Callable[[str], bool]:
    """Predicate over a lowercase haystack for an optional free-text query.

    Distinguishes the two cases callers keep conflating: no query at all means
    "list everything", while a query that reduces to no usable words (all
    stopwords, e.g. "the" or "to my") means "nothing matches". Returning the
    whole catalog for the latter silently ignores the filter the caller asked for.
    """
    if not query or not query.strip():
        return lambda _haystack: True

    patterns = build_search_patterns(query)
    if not patterns:
        return lambda _haystack: False

    return lambda haystack: any(pattern in haystack for pattern in patterns)


def generate_integration_slug(
    name: str,
    category: str,
    max_length: int = 80,
) -> str:
    """Generate canonical slug: {name}-mcp-{category}.

    No longer appends a hash suffix — the slug is human-readable and
    stored/indexed in MongoDB for direct lookup.
    """
    # Named constant, not an inline literal: the strip charset is part of the
    # slug format contract, and rstrip("XX-XX")-style mutations of an inline
    # "-" are behaviorally identical to the original (the set still contains
    # '-'), which makes them untestable. A named reference has no value to
    # mutate.
    slug = f"{slugify(name, max_length=40)}-mcp-{slugify(category, max_length=20)}"

    if len(slug) > max_length:
        truncated = slug[:max_length]
        last_hyphen = truncated.rfind(_SLUG_STRIP_CHARS)
        slug = truncated[:last_hyphen] if last_hyphen > 0 else truncated

    return slug.rstrip(_SLUG_STRIP_CHARS)


def parse_integration_slug(slug: str) -> dict:
    """Parse slug to extract: name_part, category, shortid.

    Handles both new format (no hash) and legacy format (with 6-char hash).
    """
    result: dict = {
        "name_part": slug,
        "category": None,
        "shortid": None,
    }

    # Check for legacy 6-char hash suffix
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 6 and parts[1].isalnum():
        result["shortid"] = parts[1]
        slug = parts[0]

    mcp_marker = "-mcp-"
    if mcp_marker in slug:
        name_part, category = slug.split(mcp_marker, 1)
        result["name_part"] = name_part
        result["category"] = category
    else:
        parts = slug.rsplit("-", 1)
        if len(parts) == 2:
            result["name_part"] = parts[0]
            result["category"] = parts[1]
        else:
            result["name_part"] = slug

    return result


def format_public_integration_response(integration: IntegrationWithCreator) -> dict:
    """Format an integration (with joined creator) into a response dict.

    Returns a dict that can be unpacked into PublicIntegrationDetailResponse.
    """
    mcp_config = None
    if integration.mcp_config:
        mcp_config = {
            "server_url": integration.mcp_config.server_url,
            "requires_auth": integration.mcp_config.requires_auth,
            "auth_type": integration.mcp_config.auth_type,
        }

    creator = None
    if integration.creator:
        creator = {"name": integration.creator.name, "picture": integration.creator.picture}

    slug = integration.slug or generate_integration_slug(
        name=integration.name,
        category=integration.category,
    )

    return {
        "integration_id": integration.integration_id,
        "slug": slug,
        "name": integration.name,
        "description": integration.description,
        "category": integration.category,
        "icon_url": integration.icon_url,
        "creator": creator,
        "mcp_config": mcp_config,
        "tools": [{"name": t.name, "description": t.description} for t in integration.tools],
        "clone_count": integration.clone_count,
        "tool_count": len(integration.tools),
        "published_at": integration.published_at,
        "source": "custom",  # MongoDB integrations are always custom
        "content": integration.content,  # LLM-generated; None until published/backfilled
    }
