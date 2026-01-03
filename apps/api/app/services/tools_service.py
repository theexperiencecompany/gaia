"""
Service for managing and retrieving tool information.
"""

from typing import Dict

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.decorators.caching import Cacheable
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse


@Cacheable(smart_hash=True, ttl=21600, model=ToolsListResponse)  # 6 hours
async def get_available_tools() -> ToolsListResponse:
    """Get list of all available tools with their metadata."""
    tool_infos = []
    categories = set()

    tool_registry = await get_tool_registry()
    await tool_registry.load_all_provider_tools()
    await tool_registry.load_all_mcp_tools()

    # Use category-based approach for better performance and integration info
    _categories = tool_registry.get_all_category_objects(
        ignore_categories=["delegation"]
    )

    # Track which integrations we've already added tools for
    seen_integrations: set[str] = set()

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

    # Include auth-required MCP tools from global storage
    # These are stored when first user connects and shared across all users
    from app.services.mcp.mcp_tools_store import get_mcp_tools_store

    try:
        mcp_store = get_mcp_tools_store()
        global_mcp_tools = await mcp_store.get_all_mcp_tools()

        logger.info(f"MCP global tools from DB: {list(global_mcp_tools.keys())}")

        for integration_id, tools in global_mcp_tools.items():
            # Skip if we already have tools for this integration from registry
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
    except Exception as e:
        logger.warning(f"Failed to fetch global MCP tools: {e}")

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
    await tool_registry.load_all_provider_tools()
    await tool_registry.load_all_mcp_tools()

    # Use the new category-based approach for better performance
    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts
