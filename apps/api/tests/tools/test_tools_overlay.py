"""
Tests for tools endpoint overlay behavior.

Verifies that user's custom MCP tools are properly overlaid
on top of cached global tools.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.tools_models import ToolInfo, ToolsListResponse
from app.services.tools.tools_service import (
    get_user_custom_tools,
    merge_tools_responses,
)


class TestMergeToolsResponses:
    """Tests for merge_tools_responses function."""

    def test_returns_global_when_no_custom_tools(self):
        """Should return global tools unchanged when no custom tools."""
        global_tools = ToolsListResponse(
            tools=[
                ToolInfo(name="search_web", category="search"),
                ToolInfo(name="send_email", category="email"),
            ],
            total_count=2,
            categories=["search", "email"],
        )

        result = merge_tools_responses(global_tools, [])

        assert result == global_tools
        assert result.total_count == 2

    def test_prepends_custom_tools(self):
        """Custom tools should appear before global tools."""
        global_tools = ToolsListResponse(
            tools=[
                ToolInfo(name="search_web", category="search"),
            ],
            total_count=1,
            categories=["search"],
        )

        custom_tools = [
            ToolInfo(
                name="my_custom_tool",
                category="custom_integration_123",
                integration_name="My Custom MCP",
            ),
        ]

        result = merge_tools_responses(global_tools, custom_tools)

        assert result.tools[0].name == "my_custom_tool"
        assert result.tools[1].name == "search_web"
        assert result.total_count == 2

    def test_deduplicates_by_name(self):
        """Custom tools should override global tools with same name."""
        global_tools = ToolsListResponse(
            tools=[
                ToolInfo(name="duplicate_tool", category="global_cat"),
                ToolInfo(name="unique_global", category="global_cat"),
            ],
            total_count=2,
            categories=["global_cat"],
        )

        custom_tools = [
            ToolInfo(
                name="duplicate_tool",
                category="custom_cat",
                integration_name="Custom Version",
            ),
        ]

        result = merge_tools_responses(global_tools, custom_tools)

        # Should have 2 tools total (1 custom + 1 unique global)
        assert result.total_count == 2
        assert len(result.tools) == 2

        # Custom tool should be first and override global
        duplicate = result.tools[0]
        assert duplicate.name == "duplicate_tool"
        assert duplicate.category == "custom_cat"
        assert duplicate.integration_name == "Custom Version"

    def test_adds_custom_categories(self):
        """Should add custom tool categories to the response."""
        global_tools = ToolsListResponse(
            tools=[ToolInfo(name="search_web", category="search")],
            total_count=1,
            categories=["search"],
        )

        custom_tools = [
            ToolInfo(name="my_tool", category="custom_mcp_user123"),
        ]

        result = merge_tools_responses(global_tools, custom_tools)

        assert "custom_mcp_user123" in result.categories
        assert "search" in result.categories
        assert len(result.categories) == 2


class TestGetUserCustomTools:
    """Tests for get_user_custom_tools function."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_user_id(self):
        """Should return empty list when user_id is None."""
        result = await get_user_custom_tools(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_user_id(self):
        """Should return empty list when user_id is empty string."""
        result = await get_user_custom_tools("")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetches_custom_tools_for_user(self):
        """Should fetch custom tools for a valid user."""
        mock_custom_integrations = [
            {
                "integration_id": "custom_my_mcp_user123",
                "name": "My Custom MCP",
                "icon_url": "https://example.com/icon.png",
            }
        ]

        mock_tools = [
            {"name": "custom_tool_1", "description": "A custom tool"},
            {"name": "custom_tool_2", "description": "Another custom tool"},
        ]

        with (
            patch(
                "app.services.tools.tools_service.user_integrations_collection"
            ) as mock_collection,
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store"
            ) as mock_store_fn,
        ):
            # Mock aggregation pipeline - needs to return an object with async to_list
            class MockAggCursor:
                async def to_list(self, _):
                    return mock_custom_integrations

            mock_collection.aggregate = lambda _: MockAggCursor()

            # Mock MCP tools store
            mock_store = AsyncMock()
            mock_store.get_tools = AsyncMock(return_value=mock_tools)
            mock_store_fn.return_value = mock_store

            result = await get_user_custom_tools("user123")

            assert len(result) == 2
            assert result[0].name == "custom_tool_1"
            assert result[0].category == "custom_my_mcp_user123"
            assert result[0].integration_name == "My Custom MCP"
            assert result[0].icon_url == "https://example.com/icon.png"


class TestToolsEndpointOverlay:
    """Tests for /tools endpoint overlay behavior."""

    @pytest.mark.asyncio
    async def test_overlays_custom_tools_on_cache_hit(self):
        """Should overlay custom tools when global cache exists."""
        from app.api.v1.endpoints.tools import list_available_tools

        cached_response = ToolsListResponse(
            tools=[ToolInfo(name="global_tool", category="global")],
            total_count=1,
            categories=["global"],
        )

        custom_tools = [
            ToolInfo(
                name="custom_tool",
                category="custom_mcp",
                integration_name="My Custom MCP",
            ),
        ]

        mock_user = {"user_id": "test_user"}

        with (
            patch(
                "app.api.v1.endpoints.tools.get_cache",
                new_callable=AsyncMock,
                return_value=cached_response,
            ),
            patch(
                "app.api.v1.endpoints.tools.get_user_custom_tools",
                new_callable=AsyncMock,
                return_value=custom_tools,
            ),
        ):
            result = await list_available_tools(user=mock_user)

            # Should have both tools
            assert result.total_count == 2
            # Custom tool should be first
            assert result.tools[0].name == "custom_tool"
            assert result.tools[1].name == "global_tool"

    @pytest.mark.asyncio
    async def test_returns_cache_directly_when_no_custom_tools(self):
        """Should return cached response when user has no custom tools."""
        from app.api.v1.endpoints.tools import list_available_tools

        cached_response = ToolsListResponse(
            tools=[ToolInfo(name="global_tool", category="global")],
            total_count=1,
            categories=["global"],
        )

        mock_user = {"user_id": "test_user"}

        with (
            patch(
                "app.api.v1.endpoints.tools.get_cache",
                new_callable=AsyncMock,
                return_value=cached_response,
            ),
            patch(
                "app.api.v1.endpoints.tools.get_user_custom_tools",
                new_callable=AsyncMock,
                return_value=[],  # No custom tools
            ),
        ):
            result = await list_available_tools(user=mock_user)

            assert result == cached_response
            assert result.total_count == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_full_build_on_cache_miss(self):
        """Should call get_available_tools on cache miss."""
        from app.api.v1.endpoints.tools import list_available_tools

        fresh_response = ToolsListResponse(
            tools=[ToolInfo(name="fresh_tool", category="fresh")],
            total_count=1,
            categories=["fresh"],
        )

        mock_user = {"user_id": "test_user"}

        with (
            patch(
                "app.api.v1.endpoints.tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,  # Cache miss
            ),
            patch(
                "app.api.v1.endpoints.tools.get_available_tools",
                new_callable=AsyncMock,
                return_value=fresh_response,
            ) as mock_get_tools,
        ):
            result = await list_available_tools(user=mock_user)

            mock_get_tools.assert_called_once_with(user_id="test_user")
            assert result == fresh_response
