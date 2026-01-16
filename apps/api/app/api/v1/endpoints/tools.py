"""
Tools API router for retrieving available tools and their metadata.
"""

from typing import Dict
from fastapi import APIRouter, HTTPException, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators.caching import Cacheable
from app.db.redis import get_cache
from app.models.tools_models import ToolsListResponse, ToolsCategoryResponse
from app.services.tools.tools_service import (
    get_available_tools,
    get_tools_by_category,
    get_tool_categories,
    get_user_custom_tools,
    merge_tools_responses,
)
from app.services.tools.tools_warmup import GLOBAL_TOOLS_CACHE_KEY

router = APIRouter()


@router.get("/tools", response_model=ToolsListResponse)
async def list_available_tools(
    user: dict = Depends(get_current_user),
) -> ToolsListResponse:
    """
    Get a list of all available tools with their metadata.

    Includes:
    - Platform tools (always available)
    - Global MCP tools (stored when any user first connects to an MCP integration)

    Performance optimization:
    - Global tools are cached for 6 hours (shared across all users)
    - User-specific custom tools are fetched on-demand

    Note: This endpoint returns global tool metadata for fast frontend visibility.
    User-specific tool connections are validated separately via integration status.

    Returns:
        ToolsListResponse: List of tools with descriptions, parameters, and categories
    """
    try:
        user_id = user.get("user_id")

        # Try global cache first (warmed at startup, 6 hour TTL)
        cached_global = await get_cache(GLOBAL_TOOLS_CACHE_KEY, model=ToolsListResponse)
        if cached_global is not None:
            # Overlay user's custom MCP tools on top of cached global tools
            if user_id:
                custom_tools = await get_user_custom_tools(user_id)
                if custom_tools:
                    return merge_tools_responses(cached_global, custom_tools)
            return cached_global

        # Cache miss - build tools response (will also populate cache)
        return await get_available_tools(user_id=user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve tools: {str(e)}"
        )


@router.get("/tools/categories")
@Cacheable(smart_hash=True, ttl=21600)  # 6 hours
async def list_tool_categories(
    user: dict = Depends(get_current_user),
) -> Dict[str, int]:
    """
    Get all tool categories with their counts.

    Returns:
        Dict[str, int]: Category names mapped to tool counts
    """
    try:
        return await get_tool_categories()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve tool categories: {str(e)}"
        )


@router.get("/tools/category/{category_name}", response_model=ToolsCategoryResponse)
async def get_tools_in_category(
    category_name: str, user: dict = Depends(get_current_user)
) -> ToolsCategoryResponse:
    """
    Get tools filtered by category.

    Args:
        category_name: The category to filter by

    Returns:
        ToolsCategoryResponse: Tools in the specified category
    """
    try:
        result = await get_tools_by_category(category_name)
        if result.count == 0:
            raise HTTPException(
                status_code=404, detail=f"No tools found in category '{category_name}'"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve tools for category '{category_name}': {str(e)}",
        )
