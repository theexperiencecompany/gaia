"""Integration-specific helper functions."""

from collections.abc import Callable
from dataclasses import dataclass
import re
from urllib.parse import urlsplit, urlunsplit

from app.helpers.slug_helpers import generate_integration_slug
from app.models.integration_models import IntegrationWithCreator
from app.schemas.integrations.responses import (
    CommunityIntegrationCreator,
    IntegrationTool,
    MCPConfigDetail,
    PublicIntegrationDetailResponse,
)

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


def normalize_server_url(url: str) -> str:
    """Canonicalize an MCP server URL for duplicate detection.

    Lowercases the scheme and host, drops the fragment, and strips a trailing
    slash. Path and query case are preserved — some MCP servers use
    case-sensitive paths, so touching them would break the connection.
    """
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def dedup_server_url_key(url: str | None) -> str | None:
    """Return a normalized dedup key for a custom MCP server URL, or None when unusable.

    None (rather than raising) means "no dedup protection": the caller still
    persists and connects with the original URL, which fails loudly on its own
    if the URL is genuinely bad. Empty keys are also None — a blank key would
    collide across every unusable URL under the per-creator unique index.
    """
    if not url or not url.strip():
        return None
    try:
        key = normalize_server_url(url)
    except ValueError:
        return None
    return key or None


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


@dataclass(slots=True, frozen=True)
class ParsedIntegrationSlug:
    """The parts of an integration slug: {name_part}-mcp-{category}[-{shortid}]."""

    name_part: str
    category: str | None
    shortid: str | None


def parse_integration_slug(slug: str) -> ParsedIntegrationSlug:
    """Parse slug to extract: name_part, category, shortid.

    Handles both new format (no hash) and legacy format (with 6-char hash).
    """
    shortid: str | None = None
    category: str | None = None

    # Check for legacy 6-char hash suffix
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 6 and parts[1].isalnum():
        shortid = parts[1]
        slug = parts[0]

    mcp_marker = "-mcp-"
    if mcp_marker in slug:
        name_part, category = slug.split(mcp_marker, 1)
    else:
        parts = slug.rsplit("-", 1)
        if len(parts) == 2:
            name_part, category = parts
        else:
            name_part = slug

    return ParsedIntegrationSlug(name_part=name_part, category=category, shortid=shortid)


def format_public_integration_response(
    integration: IntegrationWithCreator,
) -> PublicIntegrationDetailResponse:
    """Format an integration (with joined creator) into its public detail response."""
    mcp_config = None
    if integration.mcp_config:
        mcp_config = MCPConfigDetail(
            server_url=integration.mcp_config.server_url,
            requires_auth=integration.mcp_config.requires_auth,
            auth_type=integration.mcp_config.auth_type,
        )

    creator = None
    if integration.creator:
        creator = CommunityIntegrationCreator(
            name=integration.creator.name, picture=integration.creator.picture
        )

    slug = integration.slug or generate_integration_slug(
        name=integration.name,
        category=integration.category,
    )

    return PublicIntegrationDetailResponse(
        integration_id=integration.integration_id,
        slug=slug,
        name=integration.name,
        description=integration.description,
        category=integration.category,
        icon_url=integration.icon_url,
        creator=creator,
        mcp_config=mcp_config,
        tools=[IntegrationTool(name=t.name, description=t.description) for t in integration.tools],
        clone_count=integration.clone_count,
        tool_count=len(integration.tools),
        published_at=integration.published_at,
        source="custom",  # MongoDB integrations are always custom
        content=integration.content,  # LLM-generated; None until published/backfilled
    )
