"""Integration-specific helper functions."""

import re


def _slugify(text: str, max_length: int = 50) -> str:
    """Convert text to URL-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-+", "-", slug)

    if len(slug) > max_length:
        parts = slug[:max_length].rsplit("-", 1)
        slug = parts[0] if parts else slug[:max_length]

    return slug


def generate_integration_slug(
    name: str,
    category: str,
    integration_id: str,
    max_length: int = 80,
) -> str:
    """Generate canonical slug: {name}-mcp-{category}-{shortid}."""
    name_slug = _slugify(name, max_length=40)
    category_slug = _slugify(category, max_length=20)
    shortid = integration_id[:6].lower() if integration_id else "000000"

    slug = f"{name_slug}-mcp-{category_slug}-{shortid}"

    if len(slug) > max_length:
        suffix_len = 7
        available_len = max_length - suffix_len

        base_slug = slug[:-(suffix_len)]
        if len(base_slug) > available_len:
            truncated = base_slug[:available_len]
            last_hyphen = truncated.rfind("-")
            if last_hyphen > 0:
                base_slug = truncated[:last_hyphen]
            else:
                base_slug = truncated

        slug = f"{base_slug}-{shortid}"

    slug = slug.rstrip("-")

    return slug


def parse_integration_slug(slug: str) -> dict:
    """Parse slug to extract: name_part, category, shortid."""
    result: dict = {
        "name_part": slug,
        "category": None,
        "shortid": None,
    }

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


def build_public_integration_pipeline(short_id: str) -> list:
    """Build MongoDB pipeline for fetching public integration with creator lookup."""
    return [
        {
            "$match": {
                "integration_id": {"$regex": f"^{short_id}", "$options": "i"},
                "is_public": True,
            }
        },
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
    slug = generate_integration_slug(
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
    }
