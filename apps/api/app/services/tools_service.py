"""
Service for managing and retrieving tool information.
"""

import asyncio
from typing import Dict, Optional

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.services.mcp.mcp_tools_store import get_mcp_tools_store


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

    # Load provider and MCP tools in parallel
    await asyncio.gather(
        tool_registry.load_all_provider_tools(),
        tool_registry.load_all_mcp_tools(),
    )

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
                required_integration=category_obj.integration_name,
            )
            tool_infos.append(tool_info)
            categories.add(category)

    # Fetch global MCP tools from MongoDB
    # These are stored when the first user connects to an MCP integration
    mcp_store = get_mcp_tools_store()
    try:
        global_mcp_tools = await mcp_store.get_all_mcp_tools()
    except Exception as e:
        logger.warning(f"Failed to fetch global MCP tools: {e}")
        global_mcp_tools = {}

    # Process global MCP tools
    if global_mcp_tools:
        logger.info(f"MCP global tools from DB: {list(global_mcp_tools.keys())}")

        for integration_id, tools in global_mcp_tools.items():
            if integration_id in seen_integrations:
                logger.debug(f"Skipping {integration_id} - already in registry")
                continue

            for tool in tools:
                tool_info = ToolInfo(
                    name=tool["name"],
                    category=integration_id,
                    required_integration=integration_id,
                )
                tool_infos.append(tool_info)
                categories.add(integration_id)

            logger.info(f"Added {len(tools)} tools from MCP {integration_id}")
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

    # Load in parallel
    await asyncio.gather(
        tool_registry.load_all_provider_tools(),
        tool_registry.load_all_mcp_tools(),
    )

    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts
