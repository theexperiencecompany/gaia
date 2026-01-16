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
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.utils.request_coalescing import coalesce_request


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

    Performance: Uses request coalescing to prevent thundering herd on cache miss.
    """
    # For global tools (no user_id), use request coalescing to prevent
    # multiple concurrent requests from doing redundant work
    if user_id is None:
        return await coalesce_request("global_tools", _build_tools_response)

    # User-specific tools - build directly (per-user, no coalescing needed)
    return await _build_tools_response(user_id)


async def _build_tools_response(user_id: Optional[str] = None) -> ToolsListResponse:
    """Internal function to build the tools response.

    Separated from get_available_tools to enable request coalescing.
    """
    _ = user_id  # Reserved for future use (e.g., user-specific tool filtering)

    tool_infos: list[ToolInfo] = []
    categories: set[str] = set()
    seen_integrations: set[str] = set()
    seen_tool_names: set[str] = set()  # Track tool names for deduplication

    # Load tool registry
    tool_registry = await get_tool_registry()

    # Provider tools are loaded at application startup via lifespan
    # (see app/core/provider_registration.py - init_tool_registry and auto_initialize)

    # Get category-based tools from registry
    _categories = tool_registry.get_all_category_objects(
        ignore_categories=["delegation"]
    )

    for category, category_obj in _categories.items():
        if category_obj.integration_name:
            seen_integrations.add(category_obj.integration_name)
        for tool in category_obj.tools:
            # Skip duplicate tool names
            if tool.name in seen_tool_names:
                logger.debug(f"Skipping duplicate tool from registry: {tool.name}")
                continue
            seen_tool_names.add(tool.name)

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
        """Fetch user's custom integrations with single aggregation query.

        Optimized: Uses MongoDB aggregation pipeline instead of two separate queries.
        """
        if not user_id:
            return []
        try:
            # Single aggregation pipeline: join user_integrations with integrations
            pipeline = [
                # Match user's connected integrations
                {"$match": {"user_id": user_id, "status": "connected"}},
                # Lookup integration details
                {
                    "$lookup": {
                        "from": "integrations",
                        "localField": "integration_id",
                        "foreignField": "integration_id",
                        "as": "integration",
                    }
                },
                {"$unwind": "$integration"},
                # Filter to custom source only
                {"$match": {"integration.source": "custom"}},
                # Project needed fields
                {
                    "$project": {
                        "integration_id": 1,
                        "name": "$integration.name",
                        "icon_url": "$integration.icon_url",
                    }
                },
            ]

            return await user_integrations_collection.aggregate(pipeline).to_list(None)
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

    # Process user's custom MCP tools FIRST (to get proper metadata like name, icon)
    # This must happen before global MCP tools, otherwise custom integrations get
    # overwritten with incomplete metadata (null integration_name, category_display_name)
    for custom in custom_integrations:
        integration_id = custom.get("integration_id")
        if integration_id in seen_integrations:
            continue

        # Get cached tools from MCP tools store
        custom_tools = await mcp_store.get_tools(integration_id)
        icon_url = custom.get("icon_url")
        custom_name = custom.get("name")

        if not custom_tools:
            continue

        for tool_dict in custom_tools:
            tool_name = tool_dict["name"]
            # Skip duplicate tool names
            if tool_name in seen_tool_names:
                logger.debug(
                    f"Skipping duplicate tool from custom MCP {integration_id}: {tool_name}"
                )
                continue
            seen_tool_names.add(tool_name)

            tool_infos.append(
                ToolInfo(
                    name=tool_name,
                    category=integration_id,
                    category_display_name=custom_name,
                    integration_name=custom_name,
                    required_integration=integration_id,
                    icon_url=icon_url,
                )
            )
            categories.add(integration_id)

        logger.info(f"Added {len(custom_tools)} tools from custom MCP {integration_id}")
        seen_integrations.add(integration_id)

    # Process global MCP tools (platform integrations like Linear, Notion, etc.)
    # Custom integrations are already processed above with proper metadata
    if global_mcp_tools:
        for integration_id, tools in global_mcp_tools.items():
            if integration_id in seen_integrations:
                continue

            for tool in tools:
                tool_name = tool["name"]
                # Skip duplicate tool names
                if tool_name in seen_tool_names:
                    logger.debug(
                        f"Skipping duplicate tool from MCP {integration_id}: {tool_name}"
                    )
                    continue
                seen_tool_names.add(tool_name)

                tool_info = ToolInfo(
                    name=tool_name,
                    category=integration_id,
                    integration_name=get_integration_name(integration_id),
                    required_integration=integration_id,
                )
                tool_infos.append(tool_info)
                categories.add(integration_id)

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

    # Provider tools are loaded at application startup via lifespan
    # (see app/core/provider_registration.py - init_tool_registry and auto_initialize)

    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts


async def get_user_custom_tools(user_id: str) -> list[ToolInfo]:
    """Fetch only user's custom MCP integration tools.

    Fast query - only fetches custom integrations, not global/platform tools.
    Used to overlay user's custom tools on top of cached global tools.

    Args:
        user_id: The user's ID

    Returns:
        List of ToolInfo for user's connected custom MCP integrations
    """
    if not user_id:
        return []

    mcp_store = get_mcp_tools_store()
    tool_infos: list[ToolInfo] = []
    seen_tool_names: set[str] = set()

    try:
        # Single aggregation pipeline: join user_integrations with integrations
        pipeline = [
            # Match user's connected integrations
            {"$match": {"user_id": user_id, "status": "connected"}},
            # Lookup integration details
            {
                "$lookup": {
                    "from": "integrations",
                    "localField": "integration_id",
                    "foreignField": "integration_id",
                    "as": "integration",
                }
            },
            {"$unwind": "$integration"},
            # Filter to custom source only
            {"$match": {"integration.source": "custom"}},
            # Project needed fields
            {
                "$project": {
                    "integration_id": 1,
                    "name": "$integration.name",
                    "icon_url": "$integration.icon_url",
                }
            },
        ]

        custom_integrations = await user_integrations_collection.aggregate(
            pipeline
        ).to_list(None)

        for custom in custom_integrations:
            integration_id = custom.get("integration_id")
            icon_url = custom.get("icon_url")
            custom_name = custom.get("name")

            # Get cached tools from MCP tools store
            custom_tools = await mcp_store.get_tools(integration_id)
            if not custom_tools:
                continue

            for tool_dict in custom_tools:
                tool_name = tool_dict["name"]
                # Skip duplicate tool names
                if tool_name in seen_tool_names:
                    continue
                seen_tool_names.add(tool_name)

                tool_infos.append(
                    ToolInfo(
                        name=tool_name,
                        category=integration_id,
                        category_display_name=custom_name,
                        integration_name=custom_name,
                        required_integration=integration_id,
                        icon_url=icon_url,
                    )
                )

            logger.debug(
                f"Fetched {len(custom_tools)} tools from custom MCP {integration_id}"
            )

    except Exception as e:
        logger.warning(f"Failed to fetch user custom tools: {e}")

    return tool_infos


def merge_tools_responses(
    global_tools: ToolsListResponse,
    custom_tools: list[ToolInfo],
) -> ToolsListResponse:
    """Merge user's custom tools into global tools response.

    Handles deduplication by tool name - custom tools take precedence
    over global tools with the same name (user's tools first).

    Args:
        global_tools: Cached global tools response
        custom_tools: User's custom MCP tools to overlay

    Returns:
        Merged ToolsListResponse with both global and custom tools
    """
    if not custom_tools:
        return global_tools

    # Build set of custom tool names for deduplication
    custom_tool_names = {tool.name for tool in custom_tools}

    # Filter global tools to exclude duplicates, then prepend custom tools
    filtered_global = [
        tool for tool in global_tools.tools if tool.name not in custom_tool_names
    ]

    # Custom tools first, then global tools
    merged_tools = custom_tools + filtered_global

    # Update categories to include custom integration categories
    categories = set(global_tools.categories)
    for tool in custom_tools:
        categories.add(tool.category)

    return ToolsListResponse(
        tools=merged_tools,
        total_count=len(merged_tools),
        categories=sorted(list(categories)),
    )
