"""Marketplace integration functions - get_all_integrations, get_integration_details."""

import asyncio

from bson import ObjectId

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import integrations_collection, users_collection
from app.models.integration_models import (
    Integration,
    IntegrationResponse,
    IntegrationTool,
    MarketplaceResponse,
)
from app.models.oauth_models import OAuthIntegration
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from shared.py.wide_events import log


async def get_all_integrations(
    category: str | None = None,
    include_custom_public: bool = True,
) -> MarketplaceResponse:
    """Get all available integrations for the marketplace."""
    log.set(integration={"provider": category or "all", "action": "get_all_integrations"})
    tools_store = get_mcp_tools_store()

    async def fetch_mcp_tools() -> dict[str, dict]:
        return await tools_store.get_all_mcp_tools()

    async def fetch_custom_integrations() -> list[IntegrationResponse]:
        if not include_custom_public:
            return []

        custom_integrations = []
        query = {"source": "custom", "is_public": True}
        if category and category != "all":
            query["category"] = category

        cursor = integrations_collection.find(query).sort("created_at", -1)
        async for doc in cursor:
            try:
                integration = Integration(**doc)
                custom_integrations.append(IntegrationResponse.from_integration(integration))
            except Exception as e:
                log.warning(f"{LogTag.INTEGRATION} Failed to parse custom integration: {e}")

        return custom_integrations

    all_mcp_tools, custom_integrations = await asyncio.gather(
        fetch_mcp_tools(),
        fetch_custom_integrations(),
    )

    platform_integrations = []
    for oauth_int in OAUTH_INTEGRATIONS:
        if not oauth_int.available:
            continue
        if category and category != "all" and oauth_int.category != category:
            continue

        response = IntegrationResponse.from_oauth_integration(oauth_int)

        # Hydrate tools from global store (SSoT format: {"tools": [...], "name": ..., "icon_url": ...})
        stored_data = all_mcp_tools.get(oauth_int.id, {})
        stored_tools = (
            stored_data.get("tools", []) if isinstance(stored_data, dict) else stored_data
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


def assemble_integration_response(
    platform_integration: OAuthIntegration | None,
    custom_doc: dict | None,
    stored_tools: list[dict] | None,
    creator_doc: dict | None,
) -> IntegrationResponse | None:
    """Assemble an IntegrationResponse from already-resolved pieces.

    Shared by the single-fetch (get_integration_details) and batch-prefetched
    (get_user_integrations) paths so the two can't drift. Platform metadata comes
    from the catalog ``OAuthIntegration``; custom metadata from the stored doc;
    stored MCP tools and creator info are overlaid when present.
    """
    if platform_integration:
        response = IntegrationResponse.from_oauth_integration(platform_integration)
    elif custom_doc:
        try:
            response = IntegrationResponse.from_integration(Integration(**custom_doc))
        except Exception as e:
            log.error(f"{LogTag.INTEGRATION} Failed to parse integration: {e}")
            return None
    else:
        return None

    if stored_tools and not response.tools:
        response.tools = [
            IntegrationTool(name=t["name"], description=t.get("description")) for t in stored_tools
        ]

    if creator_doc:
        response.creator = {
            "name": creator_doc.get("name"),
            "picture": creator_doc.get("picture"),
        }

    return response


async def get_integration_details(integration_id: str) -> IntegrationResponse | None:
    """Get single integration details by ID."""
    log.set(integration={"provider": integration_id, "action": "get_integration_details"})
    tools_store = get_mcp_tools_store()
    stored_tools = await tools_store.get_tools(integration_id)

    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        return None

    # Creator lives only on custom integration docs; platform entries have none.
    creator_doc = None
    created_by = resolved.custom_doc.get("created_by") if resolved.custom_doc else None
    if created_by:
        try:
            creator_doc = await users_collection.find_one(
                {"_id": ObjectId(created_by)},
                {"name": 1, "picture": 1},
            )
        except Exception as e:
            log.debug(f"{LogTag.INTEGRATION} Failed to fetch creator info for {created_by}: {e}")

    return assemble_integration_response(
        resolved.platform_integration, resolved.custom_doc, stored_tools, creator_doc
    )
