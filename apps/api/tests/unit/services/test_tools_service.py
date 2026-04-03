"""Comprehensive unit tests for tools_service (app/services/tools/tools_service.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.services.tools.tools_service import (
    _build_tools_response,
    _fetch_user_mcp_integrations,
    get_available_tools,
    get_integration_name,
    get_tool_categories,
    get_tools_by_category,
    get_user_mcp_tools,
    merge_tools_responses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tool(name: str = "tool_1"):
    t = MagicMock()
    t.name = name
    return t


def _mock_category(
    tools: list | None = None,
    integration_name: str | None = None,
    require_integration: bool = False,
    space: str = "default",
):
    cat = MagicMock()
    cat.tools = tools or [_mock_tool()]
    cat.integration_name = integration_name
    cat.require_integration = require_integration
    cat.space = space
    return cat


# ---------------------------------------------------------------------------
# get_integration_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetIntegrationName:
    def test_returns_name_for_known_integration(self):
        # _INTEGRATION_NAME_MAP is built from OAUTH_INTEGRATIONS at module load
        # We verify the function works by patching the map
        with patch(
            "app.services.tools.tools_service._INTEGRATION_NAME_MAP",
            {"gmail": "Gmail"},
        ):
            assert get_integration_name("gmail") == "Gmail"
            assert get_integration_name("Gmail") == "Gmail"

    def test_returns_none_for_unknown(self):
        with patch("app.services.tools.tools_service._INTEGRATION_NAME_MAP", {}):
            assert get_integration_name("unknown") is None


# ---------------------------------------------------------------------------
# get_available_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAvailableTools:
    async def test_coalesces_when_no_user(self):
        fake_response = ToolsListResponse(tools=[], total_count=0, categories=[])
        with patch(
            "app.services.tools.tools_service.coalesce_request",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_coalesce:
            result = await get_available_tools(user_id=None)
            mock_coalesce.assert_called_once_with("global_tools", _build_tools_response)
            assert result == fake_response

    async def test_calls_build_directly_with_user(self):
        fake_response = ToolsListResponse(tools=[], total_count=0, categories=[])
        with patch(
            "app.services.tools.tools_service._build_tools_response",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_build:
            result = await get_available_tools(user_id="user_123")
            mock_build.assert_called_once_with("user_123")
            assert result == fake_response


# ---------------------------------------------------------------------------
# _fetch_user_mcp_integrations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchUserMcpIntegrations:
    async def test_returns_empty_for_no_user(self):
        result = await _fetch_user_mcp_integrations(None)
        assert result == []

    async def test_returns_empty_for_empty_user(self):
        result = await _fetch_user_mcp_integrations("")
        assert result == []

    async def test_returns_results_from_pipeline(self):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"integration_id": "custom_1", "name": "My MCP"}]
        )
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.tools.tools_service.user_integrations_collection",
            mock_col,
        ):
            result = await _fetch_user_mcp_integrations("user_123")
            assert len(result) == 1
            assert result[0]["integration_id"] == "custom_1"

    async def test_returns_empty_on_exception(self):
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(side_effect=Exception("db error"))

        with patch(
            "app.services.tools.tools_service.user_integrations_collection",
            mock_col,
        ):
            result = await _fetch_user_mcp_integrations("user_123")
            assert result == []


# ---------------------------------------------------------------------------
# _build_tools_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildToolsResponse:
    async def test_builds_from_registry_tools(self):
        tool = _mock_tool("my_tool")
        cat = _mock_category(tools=[tool], integration_name=None)
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(
            return_value={"general": cat}
        )

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.tools.tools_service.get_integration_name",
                return_value=None,
            ),
        ):
            result = await _build_tools_response()

        assert isinstance(result, ToolsListResponse)
        assert result.total_count == 1
        assert result.tools[0].name == "my_tool"
        assert "general" in result.categories

    async def test_skips_duplicate_tools_from_registry(self):
        tool = _mock_tool("dup_tool")
        cat = _mock_category(tools=[tool, tool])
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={"cat1": cat})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.tools.tools_service.get_integration_name",
                return_value=None,
            ),
        ):
            result = await _build_tools_response()

        assert result.total_count == 1

    async def test_includes_custom_mcp_tools(self):
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})
        mock_mcp_store.get_tools = AsyncMock(return_value=[{"name": "custom_tool_1"}])

        custom_integrations = [
            {
                "integration_id": "custom_abc",
                "name": "My Custom MCP",
                "icon_url": "https://example.com/icon.png",
            }
        ]

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=custom_integrations,
            ),
        ):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].name == "custom_tool_1"
        assert result.tools[0].icon_url == "https://example.com/icon.png"

    async def test_includes_global_mcp_tools(self):
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        global_mcp = {
            "deepwiki": {
                "name": "DeepWiki",
                "icon_url": None,
                "tools": [{"name": "search_wiki"}],
            }
        }
        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value=global_mcp)

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await _build_tools_response()

        assert result.total_count == 1
        assert result.tools[0].name == "search_wiki"
        assert result.tools[0].display_name == "DeepWiki"

    async def test_mcp_fetch_failure_graceful(self):
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(side_effect=Exception("mcp fail"))

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await _build_tools_response()

        assert result.total_count == 0

    async def test_custom_mcp_skips_seen_integrations(self):
        """Custom integrations that are already seen from registry are skipped."""
        tool = _mock_tool("reg_tool")
        cat = _mock_category(tools=[tool], integration_name="my_int")
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={"my_int": cat})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})

        custom_integrations = [
            {"integration_id": "my_int", "name": "My Int", "icon_url": None}
        ]

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=custom_integrations,
            ),
            patch(
                "app.services.tools.tools_service.get_integration_name",
                return_value=None,
            ),
        ):
            result = await _build_tools_response("user_123")

        # Only registry tool, custom skipped
        assert result.total_count == 1

    async def test_custom_mcp_skips_empty_tools(self):
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})
        mock_mcp_store.get_tools = AsyncMock(return_value=[])

        custom_integrations = [
            {"integration_id": "empty_int", "name": "Empty", "icon_url": None}
        ]

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=custom_integrations,
            ),
        ):
            result = await _build_tools_response("user_123")

        assert result.total_count == 0

    async def test_custom_mcp_skips_tool_without_name(self):
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value={})
        mock_mcp_store.get_tools = AsyncMock(
            return_value=[{"name": None}, {"name": "valid_tool"}]
        )

        custom_integrations = [
            {"integration_id": "cust_1", "name": "Cust", "icon_url": None}
        ]

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=custom_integrations,
            ),
        ):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].name == "valid_tool"

    async def test_global_mcp_skips_duplicate_tool_names(self):
        tool = _mock_tool("shared_tool")
        cat = _mock_category(tools=[tool])
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={"cat1": cat})

        global_mcp = {
            "other_int": {
                "tools": [{"name": "shared_tool"}, {"name": "unique_tool"}],
            }
        }
        mock_mcp_store = MagicMock()
        mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value=global_mcp)

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
            patch(
                "app.services.tools.tools_service._fetch_user_mcp_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.tools.tools_service.get_integration_name",
                return_value=None,
            ),
        ):
            result = await _build_tools_response()

        names = [t.name for t in result.tools]
        assert names.count("shared_tool") == 1
        assert "unique_tool" in names


# ---------------------------------------------------------------------------
# get_tools_by_category
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetToolsByCategory:
    async def test_returns_tools_for_category(self):
        tool = _mock_tool("my_tool")
        cat = _mock_category(tools=[tool])
        mock_registry = AsyncMock()
        mock_registry.get_category = MagicMock(return_value=cat)

        with (
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.services.tools.tools_service.get_integration_name",
                return_value="My Cat",
            ),
        ):
            result = await get_tools_by_category("my_cat")

        assert isinstance(result, ToolsCategoryResponse)
        assert result.count == 1
        assert result.tools[0].name == "my_tool"
        assert result.tools[0].display_name == "My Cat"

    async def test_returns_empty_for_unknown_category(self):
        mock_registry = AsyncMock()
        mock_registry.get_category = MagicMock(return_value=None)

        with patch(
            "app.services.tools.tools_service.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await get_tools_by_category("unknown")

        assert result.count == 0
        assert result.tools == []


# ---------------------------------------------------------------------------
# get_tool_categories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetToolCategories:
    async def test_returns_category_counts(self):
        cat1 = _mock_category(tools=[_mock_tool("t1"), _mock_tool("t2")])
        cat2 = _mock_category(tools=[_mock_tool("t3")])
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(
            return_value={"c1": cat1, "c2": cat2}
        )

        with patch(
            "app.services.tools.tools_service.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await get_tool_categories()

        assert result == {"c1": 2, "c2": 1}


# ---------------------------------------------------------------------------
# get_user_mcp_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserMcpTools:
    async def test_returns_empty_for_no_user(self):
        result = await get_user_mcp_tools("")
        assert result == []

    async def test_returns_tools_from_integrations(self):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "integration_id": "mcp_1",
                    "name": "MCP One",
                    "icon_url": "https://example.com/icon.png",
                }
            ]
        )
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(return_value=mock_cursor)

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_tools = AsyncMock(
            return_value=[{"name": "tool_a"}, {"name": "tool_b"}]
        )

        with (
            patch(
                "app.services.tools.tools_service.user_integrations_collection",
                mock_col,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
        ):
            result = await get_user_mcp_tools("user_123")

        assert len(result) == 2
        assert all(isinstance(t, ToolInfo) for t in result)
        assert result[0].icon_url == "https://example.com/icon.png"

    async def test_skips_empty_integration_tools(self):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"integration_id": "mcp_1", "name": "MCP", "icon_url": None}]
        )
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(return_value=mock_cursor)

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_tools = AsyncMock(return_value=[])

        with (
            patch(
                "app.services.tools.tools_service.user_integrations_collection",
                mock_col,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
        ):
            result = await get_user_mcp_tools("user_123")

        assert result == []

    async def test_skips_duplicate_tool_names(self):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"integration_id": "m1", "name": "M1", "icon_url": None},
                {"integration_id": "m2", "name": "M2", "icon_url": None},
            ]
        )
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(return_value=mock_cursor)

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_tools = AsyncMock(return_value=[{"name": "same_tool"}])

        with (
            patch(
                "app.services.tools.tools_service.user_integrations_collection",
                mock_col,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
        ):
            result = await get_user_mcp_tools("user_123")

        assert len(result) == 1

    async def test_returns_empty_on_exception(self):
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(side_effect=Exception("db fail"))

        with patch(
            "app.services.tools.tools_service.user_integrations_collection",
            mock_col,
        ):
            result = await get_user_mcp_tools("user_123")

        assert result == []

    async def test_skips_tool_with_no_name(self):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"integration_id": "m1", "name": "M1", "icon_url": None}]
        )
        mock_col = MagicMock()
        mock_col.aggregate = MagicMock(return_value=mock_cursor)

        mock_mcp_store = MagicMock()
        mock_mcp_store.get_tools = AsyncMock(
            return_value=[{"name": None}, {"name": "valid"}]
        )

        with (
            patch(
                "app.services.tools.tools_service.user_integrations_collection",
                mock_col,
            ),
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            ),
        ):
            result = await get_user_mcp_tools("user_123")

        assert len(result) == 1
        assert result[0].name == "valid"


# ---------------------------------------------------------------------------
# merge_tools_responses
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeToolsResponses:
    def test_returns_global_when_no_custom(self):
        global_tools = ToolsListResponse(
            tools=[ToolInfo(name="t1", category="c1", display_name="C1")],
            total_count=1,
            categories=["c1"],
        )
        result = merge_tools_responses(global_tools, [])
        assert result is global_tools

    def test_custom_overrides_global(self):
        global_tools = ToolsListResponse(
            tools=[
                ToolInfo(name="t1", category="c1", display_name="C1"),
                ToolInfo(name="t2", category="c1", display_name="C1"),
            ],
            total_count=2,
            categories=["c1"],
        )
        custom = [ToolInfo(name="t1", category="custom", display_name="Custom")]
        result = merge_tools_responses(global_tools, custom)

        assert result.total_count == 2
        names = {t.name for t in result.tools}
        assert names == {"t1", "t2"}
        # t1 should come from custom (first in list)
        assert result.tools[0].category == "custom"

    def test_adds_new_categories(self):
        global_tools = ToolsListResponse(tools=[], total_count=0, categories=["c1"])
        custom = [ToolInfo(name="t1", category="new_cat", display_name="New")]
        result = merge_tools_responses(global_tools, custom)
        assert "new_cat" in result.categories
        assert "c1" in result.categories
