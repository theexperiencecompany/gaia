"""
Tools API router for retrieving available tools and their metadata.
"""

from typing import Dict
from fastapi import APIRouter, HTTPException, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators.caching import Cacheable
from app.models.tools_models import ToolsListResponse, ToolsCategoryResponse
from app.services.tools_service import (
    get_available_tools,
    get_tools_by_category,
    get_tool_categories,
)

router = APIRouter()


@router.get("/tools", response_model=ToolsListResponse)
async def list_available_tools(
    user: dict = Depends(get_current_user),
) -> ToolsListResponse:
    """
    Get a list of all available tools with their metadata.

    Returns:
        ToolsListResponse: List of tools with descriptions, parameters, and categories
    """
    try:
        return await get_available_tools()
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
