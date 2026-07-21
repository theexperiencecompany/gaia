"""Integration-specific helper functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.helpers.slug_helpers import slugify

if TYPE_CHECKING:
    # Import under TYPE_CHECKING only: integration_models imports this module for
    # generate_integration_slug, so a runtime import back would be circular.
    from app.models.integration_models import IntegrationWithCreator


def generate_integration_slug(
    name: str,
    category: str,
    integration_id: str,
    max_length: int = 80,
) -> str:
    """Generate canonical slug: {name}-mcp-{category}.

    No longer appends a hash suffix — the slug is human-readable and
    stored/indexed in MongoDB for direct lookup.
    """
    name_slug = slugify(name, max_length=40)
    category_slug = slugify(category, max_length=20)

    slug = f"{name_slug}-mcp-{category_slug}"

    if len(slug) > max_length:
        truncated = slug[:max_length]
        last_hyphen = truncated.rfind("-")
        if last_hyphen > 0:
            slug = truncated[:last_hyphen]
        else:
            slug = truncated

    return slug.rstrip("-")


async def generate_unique_integration_slug(
    name: str,
    category: str,
    integration_id: str,
    collection: Any,
) -> str:
    """Generate a slug that is unique across published integrations.

    If the base slug is already taken by a different integration,
    appends -2, -3, etc. until a free slug is found.
    """
    base_slug = generate_integration_slug(name, category, integration_id)

    existing = await collection.find_one(
        {"slug": base_slug, "integration_id": {"$ne": integration_id}}
    )
    if not existing:
        return base_slug

    suffix = 2
    while suffix <= 100:
        candidate = f"{base_slug}-{suffix}"
        existing = await collection.find_one(
            {"slug": candidate, "integration_id": {"$ne": integration_id}}
        )
        if not existing:
            return candidate
        suffix += 1

    return f"{base_slug}-{integration_id[:6]}"


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
        integration_id=integration.integration_id,
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
