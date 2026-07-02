"""Integration tests for tools/skills API endpoints.

Tests the /api/v1/tools endpoints with mocked service layer to verify
routing, auth enforcement, and response structure.

The cache and MCP merge logic that previously lived in the endpoint layer
has moved entirely into get_available_tools() (the service layer). The
endpoint's job is now simpler:
  1. extract user_id from auth
  2. call get_available_tools(user_id=user_id)
  3. call filter_tools_response on the result
  4. return

TestMCPToolMerge verifies that the endpoint correctly passes user_id to the
service (which is what enables per-user MCP tool fetching inside the service)
and that the full tool catalog — including user-specific MCP tools — flows
back through the endpoint unchanged.
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
        patch("app.decorators.caching.get_cache", new_callable=AsyncMock) as mock_dec_get,
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

_PATCH_GET_AVAILABLE_TOOLS = "app.api.v1.endpoints.tools.get_available_tools"


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
        categories=sorted({t.category for t in tools}),
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

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_returns_200(self, mock_get_tools, test_client):
        """GET /tools should return 200 with tools response structure."""
        mock_get_tools.return_value = _make_tools_list_response()

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "total_count" in data
        assert "categories" in data

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_returns_tool_metadata(self, mock_get_tools, test_client):
        """GET /tools should include tool name, category, and display_name fields."""
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

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_empty_returns_200(self, mock_get_tools, test_client):
        """GET /tools with no tools in registry should return 200 with empty list."""
        mock_get_tools.return_value = ToolsListResponse(tools=[], total_count=0, categories=[])

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []
        assert data["total_count"] == 0
        assert data["categories"] == []

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_passes_user_id_to_service(
        self, mock_get_tools, test_client, test_user
    ):
        """GET /tools must forward the authenticated user_id to get_available_tools.

        The service uses user_id to fetch the user's workspace integrations and
        any personal MCP tools. Passing None or omitting user_id would mean the
        user's custom tools are silently excluded from the response.
        """
        mock_get_tools.return_value = _make_tools_list_response(
            [_make_tool_info(name="cached_tool", category="general", display_name="General")]
        )

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        # Verify the service was called with the test user's ID (not None or empty)
        mock_get_tools.assert_awaited_once()
        call_kwargs = mock_get_tools.call_args
        assert call_kwargs.kwargs.get("user_id") == str(test_user["user_id"])

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_returns_full_service_result(self, mock_get_tools, test_client):
        """GET /tools should return the full tool catalog returned by get_available_tools.

        The service now owns caching and MCP merging. The endpoint must return
        the complete result without silently dropping tools.
        """
        system_tool = _make_tool_info(name="send_email", category="gmail", display_name="Gmail")
        mcp_tool = _make_tool_info(
            name="mcp_tool",
            category="my_mcp_server",
            display_name="My MCP Server",
            requires_integration=True,
        )
        mock_get_tools.return_value = _make_tools_list_response([system_tool, mcp_tool])

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "send_email" in tool_names
        assert "mcp_tool" in tool_names
        assert data["total_count"] == 2

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_list_tools_service_error_returns_500(self, mock_get_tools, test_client):
        """GET /tools should return 500 when service raises."""
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
    async def test_list_categories_empty_returns_200(self, mock_categories, test_client):
        """GET /tools/categories with no categories returns 200 and empty dict."""
        mock_categories.return_value = {}

        response = await test_client.get(_CATEGORIES_URL)

        assert response.status_code == 200
        assert response.json() == {}

    @patch(
        "app.api.v1.endpoints.tools.get_tool_categories",
        new_callable=AsyncMock,
    )
    async def test_list_categories_service_error_returns_500(self, mock_categories, test_client):
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
            tools=[_make_tool_info(name="send_email", category="gmail", display_name="Gmail")],
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
    async def test_get_tools_in_category_not_found_returns_404(self, mock_by_cat, test_client):
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
    async def test_get_tools_in_category_service_error_returns_500(self, mock_by_cat, test_client):
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
            _make_tool_info(name="delete_email", category="gmail", display_name="Gmail"),
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
    async def test_get_tools_in_category_response_fields(self, mock_by_cat, test_client):
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
# MCP tool pass-through tests
# The cache and MCP merge logic moved from the endpoint into get_available_tools
# (the service layer). The endpoint's job is to call get_available_tools with
# the correct user_id so the service can fetch per-user MCP tools. These tests
# verify the endpoint correctly passes user_id and returns the full catalog.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPToolMerge:
    """Test that GET /tools passes user_id to the service and returns the full catalog.

    The service (get_available_tools) now owns the cache + MCP merge. The endpoint
    must pass user_id so the service can include the user's MCP tools in the result.
    These tests verify:
      1. The endpoint always calls get_available_tools(user_id=<authenticated_user>)
      2. The endpoint returns the complete catalog the service produces — including
         MCP tools that the service merged internally
      3. Tool deduplication (which now lives in the service) is reflected in responses
    """

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_service_result_with_mcp_tools_is_returned_in_full(
        self, mock_get_tools, test_client
    ):
        """GET /tools returns all tools from get_available_tools, including user MCP tools.

        The service produces a catalog that already includes merged MCP tools.
        The endpoint must not drop any tools from that catalog.
        If the endpoint were to ignore the service result, both assertions would fail.
        """
        system_tool = _make_tool_info(
            name="send_email",
            category="gmail",
            display_name="Gmail",
            requires_integration=True,
        )
        mcp_tool = ToolInfo(
            name="my_custom_action",
            category="my-mcp-server",
            display_name="My MCP Server",
            requires_integration=True,
        )
        mock_get_tools.return_value = _make_tools_list_response([system_tool, mcp_tool])

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}

        assert "send_email" in tool_names, (
            "System tool missing — endpoint may be ignoring the service result"
        )
        assert "my_custom_action" in tool_names, (
            "MCP tool missing — service result not fully returned by endpoint"
        )
        assert data["total_count"] == 2
        assert "my-mcp-server" in data["categories"]
        mock_get_tools.assert_awaited_once()

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_service_result_without_mcp_tools_is_returned_unchanged(
        self, mock_get_tools, test_client
    ):
        """GET /tools returns the catalog as-is when the service produces no MCP tools.

        When the user has no MCP integrations the service returns only the global
        system tools. The endpoint must still return the full catalog unchanged.
        """
        system_tools = [
            _make_tool_info(name="send_email", category="gmail", display_name="Gmail"),
            _make_tool_info(
                name="create_event",
                category="googlecalendar",
                display_name="Google Calendar",
            ),
        ]
        mock_get_tools.return_value = _make_tools_list_response(system_tools)

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}

        assert "send_email" in tool_names
        assert "create_event" in tool_names
        assert data["total_count"] == 2
        assert "gmail" in data["categories"]
        assert "googlecalendar" in data["categories"]

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_service_deduplication_respected(self, mock_get_tools, test_client):
        """GET /tools does not re-introduce duplicate tools if the service already deduped.

        The service deduplicates by tool name. The endpoint receives the already-deduped
        catalog and must return it verbatim — total_count must equal len(tools).
        """
        # The service would have deduped a name clash between system and MCP tools.
        # The endpoint receives the already-deduped single entry.
        deduped_tool = ToolInfo(
            name="shared_tool_name",
            category="mcp_category",
            display_name="MCP Override",
        )
        mock_get_tools.return_value = _make_tools_list_response([deduped_tool])

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()
        names = [t["name"] for t in data["tools"]]
        assert names.count("shared_tool_name") == 1, (
            "Duplicate tool name in endpoint response — endpoint may be adding extra tools"
        )
        assert data["total_count"] == 1

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_user_id_passed_to_service_on_cache_miss(
        self, mock_get_tools, test_client, test_user
    ):
        """GET /tools always calls get_available_tools with the authenticated user_id.

        The service uses user_id to load per-user workspace tools (including MCP tools).
        If the endpoint passes None or omits user_id the service cannot fetch user tools.
        This test fails if the endpoint stops forwarding user_id to the service.
        """
        mock_get_tools.return_value = _make_tools_list_response()

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        mock_get_tools.assert_awaited_once()
        call_kwargs = mock_get_tools.call_args
        assert call_kwargs.kwargs.get("user_id") == str(test_user["user_id"]), (
            "user_id not forwarded to get_available_tools — user-specific MCP tools won't be fetched"
        )

    @patch(_PATCH_GET_AVAILABLE_TOOLS, new_callable=AsyncMock)
    async def test_mcp_tool_categories_appear_in_response(self, mock_get_tools, test_client):
        """Categories from MCP tools in the service result must appear in the response categories list."""
        service_tools = [
            ToolInfo(
                name="web_search",
                category="general",
                display_name="General",
            ),
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
        mock_get_tools.return_value = _make_tools_list_response(service_tools)

        response = await test_client.get(_TOOLS_URL)

        assert response.status_code == 200
        data = response.json()

        assert "filesystem-mcp" in data["categories"]
        assert "general" in data["categories"]
        assert data["total_count"] == 3
