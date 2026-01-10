"""
Service for managing and retrieving tool information.
"""

import asyncio
from typing import Dict, Optional

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.db.mongodb.collections import integrations_collection


# Build a lookup map for integration names
_INTEGRATION_NAME_MAP: Dict[str, str] = {
    integration.id.lower(): integration.name for integration in OAUTH_INTEGRATIONS
}


def get_integration_name(integration_id: str) -> Optional[str]:
    """Get human-readable integration name from integration ID."""
    return _INTEGRATION_NAME_MAP.get(integration_id.lower())


async def get_available_tools(user_id: Optional[str] = None) -> ToolsListResponse:
    """Get list of all available tools with their metadata.

    Fetches tools from multiple sources in parallel:
    1. Tool registry (provider tools)
    2. Global MCP tools store (MongoDB) - sufficient for frontend visibility

    Note: We only fetch global MCP tools here, not user-specific tools.
    User-specific tool loading (via get_all_connected_tools) is slow because
    it establishes websocket connections. For frontend visibility, global
    tools are sufficient - they're stored when the first user connects.

    The user_id parameter is kept for future use but currently not used
    for tool fetching (only global tools are shown).
    """
    _ = user_id  # Reserved for future use (e.g., user-specific tool filtering)

    tool_infos: list[ToolInfo] = []
    categories: set[str] = set()
    seen_integrations: set[str] = set()

    # Load tool registry
    tool_registry = await get_tool_registry()

    # Load provider tools (load_all_mcp_tools is a no-op, removed for performance)
    await tool_registry.load_all_provider_tools()

    # Get category-based tools from registry
    _categories = tool_registry.get_all_category_objects(
        ignore_categories=["delegation"]
    )

    for category, category_obj in _categories.items():
        if category_obj.integration_name:
            seen_integrations.add(category_obj.integration_name)
        for tool in category_obj.tools:
            tool_info = ToolInfo(
                name=tool.name,
                category=category,
                integration_name=get_integration_name(category),
                required_integration=category_obj.integration_name,
            )
            tool_infos.append(tool_info)
            categories.add(category)

    # Fetch global MCP tools from MongoDB (parallelized with custom integrations below)
    # These are stored when the first user connects to an MCP integration
    mcp_store = get_mcp_tools_store()

    # Prepare custom integrations query (if user_id provided)
    async def fetch_custom_integrations():
        if not user_id:
            return []
        try:
            return await integrations_collection.find(
                {"source": "custom", "created_by": user_id, "status": "connected"},
                {
                    "integration_id": 1,
                    "name": 1,
                    "icon_url": 1,
                },  # Projection for efficiency
            ).to_list(None)
        except Exception as e:
            logger.warning(f"Failed to fetch custom integrations: {e}")
            return []

    # Fetch global MCP tools and custom integrations in parallel
    try:
        global_mcp_tools, custom_integrations = await asyncio.gather(
            mcp_store.get_all_mcp_tools(),
            fetch_custom_integrations(),
        )
    except Exception as e:
        logger.warning(f"Failed to fetch MCP tools: {e}")
        global_mcp_tools = {}
        custom_integrations = []

    # Process global MCP tools
    if global_mcp_tools:
        for integration_id, tools in global_mcp_tools.items():
            if integration_id in seen_integrations:
                continue

            for tool in tools:
                tool_info = ToolInfo(
                    name=tool["name"],
                    category=integration_id,
                    integration_name=get_integration_name(integration_id),
                    required_integration=integration_id,
                )
                tool_infos.append(tool_info)
                categories.add(integration_id)

            seen_integrations.add(integration_id)

    # Process user's custom MCP tools (already fetched in parallel above)
    for custom in custom_integrations:
        integration_id = custom.get("integration_id")
        if integration_id in seen_integrations:
            continue

        # Get cached tools from MCP tools store
        custom_tools = await mcp_store.get_tools(integration_id)
        icon_url = custom.get("icon_url")
        custom_name = custom.get("name")

        for tool in custom_tools:
            tool_infos.append(
                ToolInfo(
                    name=tool["name"],
                    category=integration_id,
                    category_display_name=custom_name,
                    integration_name=custom_name,
                    required_integration=integration_id,
                    icon_url=icon_url,
                )
            )
            categories.add(integration_id)

        if custom_tools:
            logger.info(
                f"Added {len(custom_tools)} tools from custom MCP {integration_id}"
            )
            seen_integrations.add(integration_id)

    return ToolsListResponse(
        tools=tool_infos,
        total_count=len(tool_infos),
        categories=sorted(list(categories)),
    )


async def get_tools_by_category(category: str) -> ToolsCategoryResponse:
    """Get tools filtered by category."""
    tool_registry = await get_tool_registry()
    category_obj = tool_registry.get_category(category)

    if not category_obj:
        return ToolsCategoryResponse(category=category, tools=[], count=0)

    tool_infos = []
    for tool in category_obj.tools:
        tool_info = ToolInfo(
            name=tool.name,
            category=category,
            required_integration=category_obj.integration_name,
        )
        tool_infos.append(tool_info)

    return ToolsCategoryResponse(
        category=category, tools=tool_infos, count=len(tool_infos)
    )


async def get_tool_categories() -> Dict[str, int]:
    """Get all tool categories with their counts."""
    category_counts: Dict[str, int] = {}
    tool_registry = await get_tool_registry()

    # Load provider tools (load_all_mcp_tools is a no-op, removed for performance)
    await tool_registry.load_all_provider_tools()

    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts
