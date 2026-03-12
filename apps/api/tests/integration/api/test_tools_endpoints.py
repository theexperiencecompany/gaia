"""Integration tests for tools/skills API endpoints.

Tests the /api/v1/tools endpoints with mocked service layer to verify
routing, auth enforcement, and response structure.

Crucially, the MCP tool merge logic is tested here: when a cache hit occurs
and the user has connected MCP integrations, get_user_mcp_tools() is called
and the result is merged into the cached global tools via merge_tools_responses().
Tests in TestMCPToolMerge verify this path so that removing the merge logic
causes test failures.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse

# ---------------------------------------------------------------------------
# Cache isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cacheable_redis_cache():
    """Prevent @Cacheable(smart_hash=True) on list_tool_categories from leaking
    cached Redis values across tests.

    The Cacheable decorator delegates entirely to get_cache / set_cache (Redis),
    so we patch both at the decorator's import site to no-ops for every test.
    This ensures the @Cacheable wrapper on list_tool_categories never reads a
    stale cached value left by a previous test in the same session.
    """
    with (
        patch(
            "app.decorators.caching.get_cache", new_callable=AsyncMock
        ) as mock_dec_get,
        patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
    ):
        mock_dec_get.return_value = None  # always a cache miss inside @Cacheable
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOLS_URL = "/api/v1/tools"
_CATEGORIES_URL = "/api/v1/tools/categories"
_CATEGORY_URL = "/api/v1/tools/category"


def _make_tool_info(**overrides) -> ToolInfo:
    defaults = {
        "name": "send_email",
        "category": "gmail",
        "display_name": "Gmail",
        "icon_url": None,
        "requires_integration": True,
    }
    defaults.update(overrides)
    return ToolInfo(**defaults)


def _make_tools_list_response(tools: list[ToolInfo] | None = None) -> ToolsListResponse:
    tools = tools or [_make_tool_info()]
    return ToolsListResponse(
        tools=tools,
        total_count=len(tools),
        categories=list({t.category for t in tools}),
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolsEndpoints:
    """Test tools REST endpoints."""

    # ------------------------------------------------------------------
    # GET /tools
    # ------------------------------------------------------------------

    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    async def test_list_tools_returns_200(
        self, mock_get_tools, mock_cache, test_client
    ):
        """GET /tools should return 200 with tools response structure."""
        mock_cache.return_value = None  # Cache miss
        mock_get_tools.return_value = _make_tools_list_response()

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "total_count" in data
        assert "categories" in data

    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    async def test_list_tools_returns_tool_metadata(
        self, mock_get_tools, mock_cache, test_client
    ):
        """GET /tools should include tool name, category, and display_name fields."""
        mock_cache.return_value = None
        tools = [
            _make_tool_info(
                name="send_email",
                category="gmail",
                display_name="Gmail",
                requires_integration=True,
            ),
            _make_tool_info(
                name="create_event",
                category="googlecalendar",
                display_name="Google Calendar",
                requires_integration=True,
            ),
            _make_tool_info(
                name="web_search",
                category="general",
                display_name="General",
                requires_integration=False,
            ),
        ]
        mock_get_tools.return_value = _make_tools_list_response(tools)

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 3
        assert len(data["tools"]) == 3

        tool_names = {t["name"] for t in data["tools"]}
        assert "send_email" in tool_names
        assert "create_event" in tool_names

    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    async def test_list_tools_empty_returns_200(
        self, mock_get_tools, mock_cache, test_client
    ):
        """GET /tools with no tools in registry should return 200 with empty list."""
        mock_cache.return_value = None
        mock_get_tools.return_value = ToolsListResponse(
            tools=[], total_count=0, categories=[]
        )

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []
        assert data["total_count"] == 0
        assert data["categories"] == []

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_list_tools_uses_cache_on_hit(
        self, mock_cache, mock_get_tools, mock_get_user_mcp_tools, test_client
    ):
        """GET /tools should return cached response when cache is available.

        On a cache hit the endpoint skips get_available_tools entirely and
        overlays user MCP tools via get_user_mcp_tools.  Both must be mocked
        to keep the test hermetic (no real DB/Redis access).
        """
        cached = _make_tools_list_response(
            [
                _make_tool_info(
                    name="cached_tool", category="general", display_name="General"
                )
            ]
        )
        mock_cache.return_value = cached
        # No user-specific MCP tools — response should come straight from cache.
        mock_get_user_mcp_tools.return_value = []

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        # Cached data is returned as-is when there are no user MCP tools.
        assert data["total_count"] == 1
        assert data["tools"][0]["name"] == "cached_tool"
        # get_available_tools must NOT have been called on a cache hit.
        mock_get_tools.assert_not_called()
        # get_cache IS called to check the global cache key.
        mock_cache.assert_called_once()

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_list_tools_merges_cache_and_mcp_tools(
        self, mock_cache, mock_get_user_mcp_tools, test_client
    ):
        """GET /tools should merge cached global tools with user MCP tools.

        When the global cache holds tool set A and get_user_mcp_tools returns
        tool set B, merge_tools_responses must combine them so both appear in
        the response (user MCP tools take precedence and are listed first).
        """
        cached_tool = _make_tool_info(
            name="cached_tool", category="general", display_name="General"
        )
        cached = _make_tools_list_response([cached_tool])
        mock_cache.return_value = cached

        mcp_tool = _make_tool_info(
            name="mcp_tool",
            category="my_mcp_server",
            display_name="My MCP Server",
            requires_integration=True,
        )
        mock_get_user_mcp_tools.return_value = [mcp_tool]

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        # Both the cached global tool and the user's MCP tool must be present.
        assert "cached_tool" in tool_names
        assert "mcp_tool" in tool_names
        assert data["total_count"] == 2
        # User MCP tools are prepended by merge_tools_responses.
        assert data["tools"][0]["name"] == "mcp_tool"

    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    async def test_list_tools_service_error_returns_500(
        self, mock_get_tools, mock_cache, test_client
    ):
        """GET /tools should return 500 when service raises."""
        mock_cache.return_value = None
        mock_get_tools.side_effect = RuntimeError("Registry unavailable")

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 500
        assert "Failed to retrieve tools" in response.json()["detail"]

    async def test_list_tools_requires_auth(self, unauthenticated_client):
        """GET /tools without auth should return 401."""
        response = await unauthenticated_client.get(_TOOLS_URL)
        assert response.status_code == 401

    # ------------------------------------------------------------------
    # GET /tools/categories
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.tools.get_tool_categories",
        new_callable=AsyncMock,
    )
    async def test_list_categories_returns_200(self, mock_categories, test_client):
        """GET /tools/categories should return 200 with category map."""
        mock_categories.return_value = {
            "gmail": 12,
            "googlecalendar": 8,
            "general": 5,
        }

        response = await test_client.get(_CATEGORIES_URL)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "gmail" in data
        assert data["gmail"] == 12

    @patch(
        "app.api.v1.endpoints.tools.get_tool_categories",
        new_callable=AsyncMock,
    )
    async def test_list_categories_empty_returns_200(
        self, mock_categories, test_client
    ):
        """GET /tools/categories with no categories returns 200 and empty dict."""
        mock_categories.return_value = {}

        response = await test_client.get(_CATEGORIES_URL)

        assert response.status_code == 200
        assert response.json() == {}

    @patch(
        "app.api.v1.endpoints.tools.get_tool_categories",
        new_callable=AsyncMock,
    )
    async def test_list_categories_service_error_returns_500(
        self, mock_categories, test_client
    ):
        """GET /tools/categories should return 500 when service raises."""
        mock_categories.side_effect = RuntimeError("Registry error")

        response = await test_client.get(_CATEGORIES_URL)

        assert response.status_code == 500
        assert "Failed to retrieve tool categories" in response.json()["detail"]

    async def test_list_categories_requires_auth(self, unauthenticated_client):
        """GET /tools/categories without auth should return 401."""
        response = await unauthenticated_client.get(_CATEGORIES_URL)
        assert response.status_code == 401

    # ------------------------------------------------------------------
    # GET /tools/category/{category_name}
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.tools.get_tools_by_category",
        new_callable=AsyncMock,
    )
    async def test_get_tools_in_category_returns_200(self, mock_by_cat, test_client):
        """GET /tools/category/{name} should return 200 with tools in category."""
        mock_by_cat.return_value = ToolsCategoryResponse(
            category="gmail",
            tools=[
                _make_tool_info(
                    name="send_email", category="gmail", display_name="Gmail"
                )
            ],
            count=1,
        )

        response = await test_client.get(f"{_CATEGORY_URL}/gmail")

        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "gmail"
        assert data["count"] == 1
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "send_email"

    @patch(
        "app.api.v1.endpoints.tools.get_tools_by_category",
        new_callable=AsyncMock,
    )
    async def test_get_tools_in_category_not_found_returns_404(
        self, mock_by_cat, test_client
    ):
        """GET /tools/category/{name} with unknown category returns 404."""
        mock_by_cat.return_value = ToolsCategoryResponse(
            category="nonexistent",
            tools=[],
            count=0,
        )

        response = await test_client.get(f"{_CATEGORY_URL}/nonexistent")

        assert response.status_code == 404
        assert "No tools found in category" in response.json()["detail"]

    @patch(
        "app.api.v1.endpoints.tools.get_tools_by_category",
        new_callable=AsyncMock,
    )
    async def test_get_tools_in_category_service_error_returns_500(
        self, mock_by_cat, test_client
    ):
        """GET /tools/category/{name} should return 500 when service raises."""
        mock_by_cat.side_effect = RuntimeError("Registry unavailable")

        response = await test_client.get(f"{_CATEGORY_URL}/gmail")

        assert response.status_code == 500
        assert "Failed to retrieve tools for category" in response.json()["detail"]

    async def test_get_tools_in_category_requires_auth(self, unauthenticated_client):
        """GET /tools/category/{name} without auth should return 401."""
        response = await unauthenticated_client.get(f"{_CATEGORY_URL}/gmail")
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.tools.get_tools_by_category",
        new_callable=AsyncMock,
    )
    async def test_get_tools_in_category_multiple_tools(self, mock_by_cat, test_client):
        """GET /tools/category/{name} should return all tools in the category."""
        tools = [
            _make_tool_info(name="send_email", category="gmail", display_name="Gmail"),
            _make_tool_info(name="read_email", category="gmail", display_name="Gmail"),
            _make_tool_info(
                name="delete_email", category="gmail", display_name="Gmail"
            ),
        ]
        mock_by_cat.return_value = ToolsCategoryResponse(
            category="gmail",
            tools=tools,
            count=3,
        )

        response = await test_client.get(f"{_CATEGORY_URL}/gmail")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["tools"]) == 3

    @patch(
        "app.api.v1.endpoints.tools.get_tools_by_category",
        new_callable=AsyncMock,
    )
    async def test_get_tools_in_category_response_fields(
        self, mock_by_cat, test_client
    ):
        """GET /tools/category/{name} tools should include required metadata fields."""
        mock_by_cat.return_value = ToolsCategoryResponse(
            category="googlecalendar",
            tools=[
                _make_tool_info(
                    name="create_event",
                    category="googlecalendar",
                    display_name="Google Calendar",
                    requires_integration=True,
                )
            ],
            count=1,
        )

        response = await test_client.get(f"{_CATEGORY_URL}/googlecalendar")

        data = response.json()
        tool = data["tools"][0]
        assert "name" in tool
        assert "category" in tool
        assert "display_name" in tool
        assert "requires_integration" in tool
        assert tool["requires_integration"] is True


# ---------------------------------------------------------------------------
# MCP merge logic tests
# These tests verify the merge path in list_available_tools:
#   cache hit → get_user_mcp_tools() → merge_tools_responses()
# If the merge logic is removed the assertions on tool counts will fail.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPToolMerge:
    """Test user MCP tool merge logic in GET /tools.

    The endpoint has two code paths for the cache-hit case:
      1. User has MCP tools → merge into cached global tools
      2. User has no MCP tools → return cached global tools unchanged

    Both paths are tested here by mocking at the function level that the
    endpoint directly calls (get_cache, get_user_mcp_tools).
    """

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_with_mcp_tools_merges_both(
        self, mock_cache, mock_get_mcp_tools, test_client
    ):
        """Cache hit + user MCP tools → response must include both system and MCP tools.

        This test fails if the merge branch (get_user_mcp_tools / merge_tools_responses)
        is removed from the endpoint, because only the system tools would be returned.
        """
        system_tool = _make_tool_info(
            name="send_email",
            category="gmail",
            display_name="Gmail",
            requires_integration=True,
        )
        cached_global = _make_tools_list_response([system_tool])
        mock_cache.return_value = cached_global

        mcp_tool = ToolInfo(
            name="my_custom_action",
            category="my-mcp-server",
            display_name="My MCP Server",
            requires_integration=True,
        )
        mock_get_mcp_tools.return_value = [mcp_tool]

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}

        # Both the system tool and the MCP tool must be present
        assert "send_email" in tool_names, (
            "System tool missing from merged response – merge logic may have been removed"
        )
        assert "my_custom_action" in tool_names, (
            "MCP tool missing from merged response – merge logic may have been removed"
        )
        assert data["total_count"] == 2

        # The MCP tool's category must appear in the categories list
        assert "my-mcp-server" in data["categories"]

        # get_user_mcp_tools must have been called (proves merge path was exercised)
        mock_get_mcp_tools.assert_awaited_once()

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_cache_hit_without_mcp_tools_returns_only_system_tools(
        self, mock_cache, mock_get_mcp_tools, test_client
    ):
        """Cache hit + no user MCP tools → only the cached system tools are returned.

        This test ensures that users without MCP integrations receive the standard
        global tool list without any extra tools being injected.
        """
        system_tools = [
            _make_tool_info(name="send_email", category="gmail", display_name="Gmail"),
            _make_tool_info(
                name="create_event",
                category="googlecalendar",
                display_name="Google Calendar",
            ),
        ]
        cached_global = _make_tools_list_response(system_tools)
        mock_cache.return_value = cached_global

        # No MCP tools for this user
        mock_get_mcp_tools.return_value = []

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}

        assert "send_email" in tool_names
        assert "create_event" in tool_names
        assert data["total_count"] == 2

        # No MCP categories should appear beyond what was in the cache
        assert "gmail" in data["categories"]
        assert "googlecalendar" in data["categories"]

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_mcp_tool_overrides_system_tool_with_same_name(
        self, mock_cache, mock_get_mcp_tools, test_client
    ):
        """MCP tool with a name matching a system tool takes precedence in merge.

        merge_tools_responses() deduplicates by name and puts custom tools first,
        so the merged result must not double-count a tool whose name appears in both.
        """
        overlapping_name = "shared_tool_name"
        system_tool = _make_tool_info(
            name=overlapping_name,
            category="system_category",
            display_name="System",
        )
        cached_global = _make_tools_list_response([system_tool])
        mock_cache.return_value = cached_global

        mcp_tool = ToolInfo(
            name=overlapping_name,
            category="mcp_category",
            display_name="MCP Override",
        )
        mock_get_mcp_tools.return_value = [mcp_tool]

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()

        # The name must appear exactly once (no duplication)
        names = [t["name"] for t in data["tools"]]
        assert names.count(overlapping_name) == 1, (
            "Duplicate tool name found – merge deduplication logic may be broken"
        )
        assert data["total_count"] == 1

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.tools.get_available_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_cache_miss_does_not_call_get_user_mcp_tools(
        self, mock_cache, mock_get_tools, mock_get_mcp_tools, test_client
    ):
        """When the cache misses, get_user_mcp_tools is NOT called by the endpoint directly.

        On a cache miss the endpoint delegates entirely to get_available_tools(),
        which handles its own MCP fetching. The endpoint-level merge path
        (get_user_mcp_tools + merge_tools_responses) only runs on a cache hit.

        If someone accidentally calls the merge path on cache miss, this test
        will detect the extra call to get_user_mcp_tools.
        """
        mock_cache.return_value = None  # Cache miss
        mock_get_tools.return_value = _make_tools_list_response()

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        # On cache miss the endpoint must NOT call get_user_mcp_tools at all
        mock_get_mcp_tools.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.tools.get_user_mcp_tools",
        new_callable=AsyncMock,
    )
    @patch("app.api.v1.endpoints.tools.get_cache", new_callable=AsyncMock)
    async def test_mcp_tools_categories_added_to_response(
        self, mock_cache, mock_get_mcp_tools, test_client
    ):
        """Categories from merged MCP tools must appear in the response categories list."""
        cached_global = ToolsListResponse(
            tools=[
                _make_tool_info(
                    name="web_search", category="general", display_name="General"
                )
            ],
            total_count=1,
            categories=["general"],
        )
        mock_cache.return_value = cached_global

        mcp_tools = [
            ToolInfo(
                name="read_file",
                category="filesystem-mcp",
                display_name="Filesystem MCP",
            ),
            ToolInfo(
                name="write_file",
                category="filesystem-mcp",
                display_name="Filesystem MCP",
            ),
        ]
        mock_get_mcp_tools.return_value = mcp_tools

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()

        assert "filesystem-mcp" in data["categories"]
        assert "general" in data["categories"]
        assert data["total_count"] == 3
