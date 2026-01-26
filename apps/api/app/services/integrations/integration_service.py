"""
Integration Service Utilities.

Utility functions for integration management.
For main functions, import directly from:
- app.services.integrations.marketplace
- app.services.integrations.user_integrations
- app.services.integrations.custom_crud
"""

from typing import Any, Dict, List, Set

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.schemas.integrations.responses import (
    CommunityIntegrationCreator,
    CommunityIntegrationItem,
    IntegrationTool,
)
from app.services.oauth.oauth_service import get_all_integrations_status
from app.helpers.integration_helpers import generate_integration_slug


async def get_user_available_tool_namespaces(user_id: str) -> Set[str]:
    """Get the set of integration namespaces (tool spaces) that user has connected."""
    namespaces: Set[str] = set()

    # Add core namespaces that are always available
    namespaces.update({"general", "subagents"})

    # Internal integrations (like todos, goals, reminders) are core platform features
    # They're NOT integrations that need connecting via UI
    internal_integrations = [
        integration.id
        for integration in OAUTH_INTEGRATIONS
        if integration.managed_by == "internal" and integration.available
    ]
    namespaces.update(internal_integrations)

    # Get connected integrations from unified status
    status = await get_all_integrations_status(user_id)
    connected = {
        integration_id
        for integration_id, is_connected in status.items()
        if is_connected
    }
    namespaces.update(connected)

    return namespaces


def build_creator_lookup_stages() -> List[Dict[str, Any]]:
    """Build aggregation stages to join creator info from users collection."""
    return [
        {
            "$addFields": {
                "created_by_oid": {
                    "$cond": {
                        "if": {
                            "$and": [
                                {"$ne": ["$created_by", None]},
                                {
                                    "$regexMatch": {
                                        "input": "$created_by",
                                        "regex": "^[0-9a-fA-F]{24}$",
                                    }
                                },
                            ]
                        },
                        "then": {"$toObjectId": "$created_by"},
                        "else": None,
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "users",
                "localField": "created_by_oid",
                "foreignField": "_id",
                "as": "creator_info",
            }
        },
        {"$unwind": {"path": "$creator_info", "preserveNullAndEmptyArrays": True}},
        {
            "$addFields": {
                "creator": {
                    "$cond": {
                        "if": {"$ne": ["$creator_info", None]},
                        "then": {
                            "name": "$creator_info.name",
                            "picture": "$creator_info.picture",
                        },
                        "else": None,
                    }
                }
            }
        },
        {"$project": {"creator_info": 0, "created_by_oid": 0}},
    ]


def format_community_integrations(docs: list) -> list:
    """Format MongoDB documents into CommunityIntegrationItem responses."""
    result = []
    for doc in docs:
        tools = doc.get("tools", [])
        tool_items = [
            IntegrationTool(
                name=t.get("name", ""),
                description=t.get("description"),
            )
            for t in tools[:10]
        ]

        creator = None
        creator_data = doc.get("creator")
        if creator_data:
            creator = CommunityIntegrationCreator(
                name=creator_data.get("name"),
                picture=creator_data.get("picture"),
            )

        # Compute slug from name + category + integration_id
        slug = generate_integration_slug(
            name=doc.get("name", ""),
            category=doc.get("category", "custom"),
            integration_id=doc["integration_id"],
        )

        result.append(
            CommunityIntegrationItem(
                integration_id=doc["integration_id"],
                slug=slug,
                name=doc["name"],
                description=doc.get("description", ""),
                category=doc.get("category", "custom"),
                icon_url=doc.get("icon_url"),
                clone_count=doc.get("clone_count", 0),
                tool_count=len(tools),
                tools=tool_items,
                published_at=doc.get("published_at"),
                creator=creator,
            )
        )
    return result


__all__ = [
    "get_user_available_tool_namespaces",
    "build_creator_lookup_stages",
    "format_community_integrations",
]
