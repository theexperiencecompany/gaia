"""
Tools API router for retrieving available tools and their metadata.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators.caching import Cacheable
from app.models.chat_models import ConversationSource
from app.models.tools_models import ToolsCategoryResponse, ToolsListResponse
from app.services.tools.tools_service import (
    filter_tools_response,
    get_available_tools,
    get_tool_categories,
    get_tools_by_category,
)
from shared.py.wide_events import log

router = APIRouter()

_CLIENT_TYPE_HEADER = "X-Client-Type"


@router.get("/tools", response_model=ToolsListResponse)
async def list_available_tools(
    request: Request,
    user: dict = Depends(get_current_user),
) -> ToolsListResponse:
    """Tools the current user can use: core tools plus the tools of integrations
    in their workspace, each tagged with server-computed `locked` (added but not
    connected). Leak-safe — never another user's integrations. Desktop-only tools
    are included only for the desktop client (`X-Client-Type: desktop`)."""
    log.set(operation="list_tools")
    try:
        user_id = user.get("user_id")
        include_desktop = (
            request.headers.get(_CLIENT_TYPE_HEADER, "").strip().lower()
            == ConversationSource.DESKTOP.value
        )

        catalog = await get_available_tools(user_id=user_id)
        result = filter_tools_response(catalog, include_desktop=include_desktop)
        log.set(result_count=result.total_count, outcome="success")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tools: {e!s}")


@router.get("/tools/categories")
@Cacheable(smart_hash=True, ttl=21600)  # 6 hours
async def list_tool_categories(
    user: dict = Depends(get_current_user),
) -> dict[str, int]:
    """
    Get all tool categories with their counts.

    Returns:
        Dict[str, int]: Category names mapped to tool counts
    """
    log.set(operation="list_tool_categories")
    try:
        result = await get_tool_categories()
        log.set(result_count=len(result))
        log.set(outcome="success")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tool categories: {e!s}")


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
    log.set(operation="get_tools_by_category", tool_name=category_name)
    try:
        result = await get_tools_by_category(category_name)
        if result.count == 0:
            raise HTTPException(
                status_code=404, detail=f"No tools found in category '{category_name}'"
            )
        log.set(result_count=result.count)
        log.set(outcome="success")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve tools for category '{category_name}': {e!s}",
        )
