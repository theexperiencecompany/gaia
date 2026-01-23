"""Tools service for managing and retrieving tool information."""

import asyncio
from typing import Dict, Optional

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.mongodb.collections import user_integrations_collection
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.utils.request_coalescing import coalesce_request

_INTEGRATION_NAME_MAP: Dict[str, str] = {
    integration.id.lower(): integration.name for integration in OAUTH_INTEGRATIONS
}


def get_integration_name(integration_id: str) -> Optional[str]:
    return _INTEGRATION_NAME_MAP.get(integration_id.lower())


async def get_available_tools(user_id: Optional[str] = None) -> ToolsListResponse:
    """Get list of all available tools with their metadata.

    Uses request coalescing for global tools to prevent thundering herd.
    """
    if user_id is None:
        return await coalesce_request("global_tools", _build_tools_response)
    return await _build_tools_response(user_id)


async def _fetch_user_mcp_integrations(user_id: Optional[str]) -> list[dict]:
    """Fetch all MCP integrations connected by user that have tools stored.

    Includes both custom MCP integrations (source='custom') and platform
    MCP integrations (managed_by='mcp') - any integration with stored tools.
    """
    if not user_id:
        return []
    try:
        pipeline = [
            {"$match": {"user_id": user_id, "status": "connected"}},
            {
                "$lookup": {
                    "from": "integrations",
                    "localField": "integration_id",
                    "foreignField": "integration_id",
                    "as": "integration",
                }
            },
            {"$unwind": "$integration"},
            # Include any integration with stored tools (custom + platform MCP)
            {"$match": {"integration.tools": {"$exists": True, "$ne": []}}},
            {
                "$project": {
                    "integration_id": 1,
                    "name": "$integration.name",
                    "icon_url": "$integration.icon_url",
                    "source": "$integration.source",
                }
            },
        ]
        return await user_integrations_collection.aggregate(pipeline).to_list(None)
    except Exception as e:
        logger.warning(f"Failed to fetch user MCP integrations: {e}")
        return []


async def _build_tools_response(user_id: Optional[str] = None) -> ToolsListResponse:
    tool_infos: list[ToolInfo] = []
    categories: set[str] = set()
    seen_integrations: set[str] = set()
    seen_tool_names: set[str] = set()

    tool_registry = await get_tool_registry()
    _categories = tool_registry.get_all_category_objects(
        ignore_categories=["delegation"]
    )

    for category, category_obj in _categories.items():
        if category_obj.integration_name:
            seen_integrations.add(category_obj.integration_name)
        for tool in category_obj.tools:
            if tool.name in seen_tool_names:
                logger.debug(f"Skipping duplicate tool from registry: {tool.name}")
                continue
            seen_tool_names.add(tool.name)

            integration_display_name = get_integration_name(category)

            tool_info = ToolInfo(
                name=tool.name,
                category=category,
                display_name=integration_display_name
                or category.replace("_", " ").title(),
                icon_url=None,
            )
            tool_infos.append(tool_info)
            categories.add(category)

    mcp_store = get_mcp_tools_store()

    global_mcp_tools: dict[str, list[dict]] = {}
    custom_integrations: list[dict] = []
    try:
        global_mcp_tools, custom_integrations = await asyncio.gather(
            mcp_store.get_all_mcp_tools(),
            _fetch_user_mcp_integrations(user_id),
        )
    except Exception as e:
        logger.warning(f"Failed to fetch MCP tools: {e}")

    # Process custom integrations first for proper metadata
    for custom in custom_integrations:
        integration_id = custom.get("integration_id")
        if not integration_id or integration_id in seen_integrations:
            continue

        custom_tools = await mcp_store.get_tools(integration_id)
        icon_url = custom.get("icon_url")
        custom_name = custom.get("name")

        if not custom_tools:
            continue

        for tool_dict in custom_tools:
            tool_name = tool_dict.get("name")
            if not tool_name:
                logger.warning(
                    f"Skipping tool with missing 'name' from custom MCP {integration_id}"
                )
                continue
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
                    display_name=custom_name
                    or integration_id.replace("_", " ").title(),
                    icon_url=icon_url,
                )
            )
            categories.add(integration_id)

        logger.info(f"Added {len(custom_tools)} tools from custom MCP {integration_id}")
        seen_integrations.add(integration_id)

    if global_mcp_tools:
        for integration_id, data in global_mcp_tools.items():
            if integration_id in seen_integrations:
                continue

            display_name = (
                data.get("name")
                or get_integration_name(integration_id)
                or integration_id.replace("_", " ").title()
            )
            icon_url = data.get("icon_url")
            tools = data.get("tools", [])

            for tool_dict in tools:
                tool_name = tool_dict.get("name")
                if not tool_name or tool_name in seen_tool_names:
                    continue
                seen_tool_names.add(tool_name)

                tool_infos.append(
                    ToolInfo(
                        name=tool_name,
                        category=integration_id,
                        display_name=display_name,
                        icon_url=icon_url,
                    )
                )
                categories.add(integration_id)

            seen_integrations.add(integration_id)

    return ToolsListResponse(
        tools=tool_infos,
        total_count=len(tool_infos),
        categories=sorted(list(categories)),
    )


async def get_tools_by_category(category: str) -> ToolsCategoryResponse:
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
    category_counts: Dict[str, int] = {}
    tool_registry = await get_tool_registry()
    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts


async def get_user_mcp_tools(user_id: str) -> list[ToolInfo]:
    """Fetch user's connected MCP integration tools (custom + platform).

    Returns tools from all MCP integrations the user has connected that
    have stored tools in MongoDB. This overlays on top of cached global tools.
    """
    if not user_id:
        return []

    mcp_store = get_mcp_tools_store()
    tool_infos: list[ToolInfo] = []
    seen_tool_names: set[str] = set()

    try:
        pipeline = [
            {"$match": {"user_id": user_id, "status": "connected"}},
            {
                "$lookup": {
                    "from": "integrations",
                    "localField": "integration_id",
                    "foreignField": "integration_id",
                    "as": "integration",
                }
            },
            {"$unwind": "$integration"},
            # Include any integration with stored tools (custom + platform MCP)
            {"$match": {"integration.tools": {"$exists": True, "$ne": []}}},
            {
                "$project": {
                    "integration_id": 1,
                    "name": "$integration.name",
                    "icon_url": "$integration.icon_url",
                }
            },
        ]

        mcp_integrations = await user_integrations_collection.aggregate(
            pipeline
        ).to_list(None)

        for mcp_integration in mcp_integrations:
            integration_id = mcp_integration.get("integration_id")
            icon_url = mcp_integration.get("icon_url")
            display_name = mcp_integration.get("name")

            integration_tools = await mcp_store.get_tools(integration_id)
            if not integration_tools:
                continue

            for tool_dict in integration_tools:
                tool_name = tool_dict.get("name")
                if not tool_name or tool_name in seen_tool_names:
                    continue
                seen_tool_names.add(tool_name)

                tool_infos.append(
                    ToolInfo(
                        name=tool_name,
                        category=integration_id,
                        display_name=display_name
                        or integration_id.replace("_", " ").title(),
                        icon_url=icon_url,
                    )
                )

            logger.debug(
                f"Fetched {len(integration_tools)} tools from MCP {integration_id}"
            )

    except Exception as e:
        logger.warning(f"Failed to fetch user MCP tools: {e}")

    return tool_infos


def merge_tools_responses(
    global_tools: ToolsListResponse,
    custom_tools: list[ToolInfo],
) -> ToolsListResponse:
    """Merge user's custom tools into global tools response (custom tools take precedence)."""
    if not custom_tools:
        return global_tools

    custom_tool_names = {tool.name for tool in custom_tools}
    filtered_global = [
        tool for tool in global_tools.tools if tool.name not in custom_tool_names
    ]
    merged_tools = custom_tools + filtered_global

    categories = set(global_tools.categories)
    for tool in custom_tools:
        categories.add(tool.category)

    return ToolsListResponse(
        tools=merged_tools,
        total_count=len(merged_tools),
        categories=sorted(list(categories)),
    )
