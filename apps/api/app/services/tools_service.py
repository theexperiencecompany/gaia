"""
Service for managing and retrieving tool information.
"""

from typing import Dict

from app.agents.tools.core.registry import get_tool_registry
from app.decorators.caching import Cacheable
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse


@Cacheable(smart_hash=True, ttl=21600, model=ToolsListResponse)  # 6 hours
async def get_available_tools() -> ToolsListResponse:
    """Get list of all available tools with their metadata."""
    tool_infos = []
    categories = set()

    tool_registry = await get_tool_registry()
    await tool_registry.load_all_provider_tools()

    # Use category-based approach for better performance and integration info
    _categories = tool_registry.get_all_category_objects(
        ignore_categories=["delegation"]
    )

    for category, category_obj in _categories.items():
        for tool in category_obj.tools:
            tool_info = ToolInfo(
                name=tool.name,
                category=category,
                required_integration=category_obj.integration_name,
            )
            tool_infos.append(tool_info)
            categories.add(category)

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

    # Use the new category-based approach for better performance
    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        category_counts[category_name] = len(category_obj.tools)

    return category_counts
