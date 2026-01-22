"""Marketplace integration functions - get_all_integrations, get_integration_details."""

import asyncio
from typing import Optional

from app.config.loggers import app_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.mongodb.collections import integrations_collection, users_collection
from app.models.integration_models import (
    Integration,
    IntegrationResponse,
    IntegrationTool,
    MarketplaceResponse,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from bson import ObjectId


async def get_all_integrations(
    category: Optional[str] = None,
    include_custom_public: bool = True,
) -> MarketplaceResponse:
    """Get all available integrations for the marketplace."""
    tools_store = get_mcp_tools_store()

    async def fetch_mcp_tools() -> dict[str, dict]:
        return await tools_store.get_all_mcp_tools()

    async def fetch_custom_integrations() -> list[IntegrationResponse]:
        if not include_custom_public:
            return []

        custom_integrations = []
        query = {"source": "custom", "is_public": True}
        if category:
            query["category"] = category

        cursor = integrations_collection.find(query).sort("created_at", -1)
        async for doc in cursor:
            try:
                integration = Integration(**doc)
                custom_integrations.append(
                    IntegrationResponse.from_integration(integration)
                )
            except Exception as e:
                logger.warning(f"Failed to parse custom integration: {e}")

        return custom_integrations

    all_mcp_tools, custom_integrations = await asyncio.gather(
        fetch_mcp_tools(),
        fetch_custom_integrations(),
    )

    platform_integrations = []
    for oauth_int in OAUTH_INTEGRATIONS:
        if not oauth_int.available:
            continue
        if category and oauth_int.category != category:
            continue

        response = IntegrationResponse.from_oauth_integration(oauth_int)

        # Hydrate tools from global store (SSoT format: {"tools": [...], "name": ..., "icon_url": ...})
        stored_data = all_mcp_tools.get(oauth_int.id, {})
        stored_tools = (
            stored_data.get("tools", [])
            if isinstance(stored_data, dict)
            else stored_data
        )
        if stored_tools:
            response.tools = [
                IntegrationTool(name=t["name"], description=t.get("description"))
                for t in stored_tools
            ]

        platform_integrations.append(response)

    all_integrations = platform_integrations + custom_integrations
    featured = [i for i in all_integrations if i.is_featured]
    featured.sort(key=lambda x: (-x.display_priority, x.name))
    all_integrations.sort(key=lambda x: (-x.display_priority, x.name))

    return MarketplaceResponse(
        featured=featured,
        integrations=all_integrations,
        total=len(all_integrations),
    )


async def get_integration_details(integration_id: str) -> Optional[IntegrationResponse]:
    """Get single integration details by ID."""
    tools_store = get_mcp_tools_store()
    stored_tools = await tools_store.get_tools(integration_id)

    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        return None

    if resolved.platform_integration:
        response = IntegrationResponse.from_oauth_integration(
            resolved.platform_integration
        )
    elif resolved.custom_doc:
        try:
            integration = Integration(**resolved.custom_doc)
            response = IntegrationResponse.from_integration(integration)
        except Exception as e:
            logger.error(f"Failed to parse integration {integration_id}: {e}")
            return None
    else:
        return None

    if stored_tools and not response.tools:
        response.tools = [
            IntegrationTool(name=t["name"], description=t.get("description"))
            for t in stored_tools
        ]

    if response.created_by:
        try:
            creator_oid = ObjectId(response.created_by)
            creator_doc = await users_collection.find_one(
                {"_id": creator_oid},
                {"name": 1, "picture": 1},
            )
            if creator_doc:
                response.creator = {
                    "name": creator_doc.get("name"),
                    "picture": creator_doc.get("picture"),
                }
        except Exception:
            pass

    return response
