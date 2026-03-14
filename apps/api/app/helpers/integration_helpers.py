"""Integration-specific helper functions."""

from typing import Any

from app.helpers.slug_helpers import slugify


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


def _creator_lookup_stages() -> list:
    """Return the shared $lookup, $addFields, and $project stages for creator info."""
    return [
        {
            "$lookup": {
                "from": "users",
                "let": {
                    "creator_id": {
                        "$convert": {
                            "input": "$created_by",
                            "to": "objectId",
                            "onError": None,
                            "onNull": None,
                        }
                    }
                },
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$_id", "$$creator_id"]}}},
                    {"$project": {"name": 1, "picture": 1}},
                ],
                "as": "creator_info",
            }
        },
        {
            "$addFields": {
                "creator": {
                    "$cond": {
                        "if": {"$gt": [{"$size": "$creator_info"}, 0]},
                        "then": {"$arrayElemAt": ["$creator_info", 0]},
                        "else": None,
                    }
                }
            }
        },
        {"$project": {"creator_info": 0}},
    ]


def build_public_integration_pipeline(short_id: str) -> list:
    """Build MongoDB pipeline for fetching public integration with creator lookup."""
    return [
        {
            "$match": {
                "integration_id": {"$regex": f"^{short_id}", "$options": "i"},
                "is_public": True,
            }
        },
        *_creator_lookup_stages(),
    ]


def build_slug_lookup_pipeline(slug: str) -> list:
    """Build MongoDB pipeline for slug-based integration lookup."""
    return [
        {"$match": {"slug": slug, "is_public": True}},
        *_creator_lookup_stages(),
    ]


def format_public_integration_response(doc: dict) -> dict:
    """Format MongoDB integration doc to response dict.

    Returns a dict that can be unpacked into PublicIntegrationDetailResponse.
    """
    mcp_config_doc = doc.get("mcp_config", {})
    mcp_config = None
    if mcp_config_doc:
        mcp_config = {
            "server_url": mcp_config_doc.get("server_url"),
            "requires_auth": mcp_config_doc.get("requires_auth", False),
            "auth_type": mcp_config_doc.get("auth_type"),
        }

    creator = None
    creator_data = doc.get("creator")
    if creator_data:
        creator = {
            "name": creator_data.get("name"),
            "picture": creator_data.get("picture"),
        }

    tools = doc.get("tools", [])
    slug = doc.get("slug") or generate_integration_slug(
        name=doc.get("name", ""),
        category=doc.get("category", "custom"),
        integration_id=doc["integration_id"],
    )

    return {
        "integration_id": doc["integration_id"],
        "slug": slug,
        "name": doc["name"],
        "description": doc.get("description", ""),
        "category": doc.get("category", "custom"),
        "icon_url": doc.get("icon_url"),
        "creator": creator,
        "mcp_config": mcp_config,
        "tools": [
            {"name": t.get("name", ""), "description": t.get("description")}
            for t in tools
        ],
        "clone_count": doc.get("clone_count", 0),
        "tool_count": len(tools),
        "published_at": doc.get("published_at"),
        "source": "custom",  # MongoDB integrations are always custom
    }
