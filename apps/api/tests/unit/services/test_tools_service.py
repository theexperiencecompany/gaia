"""Comprehensive unit tests for tools_service (app/services/tools/tools_service.py)."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.tools_models import ToolsCategoryResponse, ToolsListResponse
from app.services.tools.tools_service import (
    _build_tools_response,
    get_available_tools,
    get_integration_name,
    get_tool_categories,
    get_tools_by_category,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tool(name: str = "tool_1") -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


def _mock_category(
    tools: list | None = None,
    integration_name: str | None = None,
    require_integration: bool = False,
    space: str = "default",
    internal: bool = False,
) -> MagicMock:
    cat = MagicMock()
    cat.tools = tools or [_mock_tool()]
    cat.integration_name = integration_name
    cat.require_integration = require_integration
    cat.space = space
    cat.internal = internal
    return cat


# ---------------------------------------------------------------------------
# get_integration_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetIntegrationName:
    def test_returns_name_for_known_integration(self) -> None:
        # _INTEGRATION_NAME_MAP is built from OAUTH_INTEGRATIONS at module load
        # We verify the function works by patching the map
        with patch(
            "app.services.tools.tools_service._INTEGRATION_NAME_MAP",
            {"gmail": "Gmail"},
        ):
            assert get_integration_name("gmail") == "Gmail"
            assert get_integration_name("Gmail") == "Gmail"

    def test_returns_none_for_unknown(self) -> None:
        with patch("app.services.tools.tools_service._INTEGRATION_NAME_MAP", {}):
            assert get_integration_name("unknown") is None


# ---------------------------------------------------------------------------
# get_available_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAvailableTools:
    async def test_coalesces_when_no_user(self) -> None:
        fake_response = ToolsListResponse(tools=[], total_count=0, categories=[])
        with patch(
            "app.services.tools.tools_service.coalesce_request",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_coalesce:
            result = await get_available_tools(user_id=None)
            mock_coalesce.assert_called_once_with("global_tools", _build_tools_response)
            assert result == fake_response

    async def test_calls_user_catalog_with_user(self) -> None:
        """With a user_id, get_available_tools delegates to the caching layer."""
        fake_response = ToolsListResponse(tools=[], total_count=0, categories=[])
        with patch(
            "app.services.tools.tools_service._get_user_tools_catalog",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_catalog:
            result = await get_available_tools(user_id="user_123")
            mock_catalog.assert_called_once_with("user_123")
            assert result == fake_response


# ---------------------------------------------------------------------------
# Workspace scoping via get_user_integration_records
# (replaces the old _fetch_user_mcp_integrations tests)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkspaceScoping:
    """_build_tools_response scopes all MCP tool visibility to the user's
    workspace using get_user_integration_records. These tests verify that
    scoping contract at the _build_tools_response boundary."""

    async def test_no_user_means_no_mcp_tools(self) -> None:
        """Anonymous call: get_user_integration_records is never called;
        `added` stays empty so all MCP tools are filtered out."""
        global_mcp = {"my_mcp": {"name": "X", "icon_url": None, "tools": [{"name": "t"}]}}
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
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
        ):
            result = await _build_tools_response(None)

        assert result.total_count == 0

    async def test_user_with_added_integration_sees_tools(self) -> None:
        global_mcp = {
            "custom_1": {
                "name": "My MCP",
                "icon_url": None,
                "tools": [{"name": "tool_a"}, {"name": "tool_b"}],
            }
        }
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
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
                "app.services.tools.tools_service.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[{"integration_id": "custom_1", "status": "connected"}],
            ),
        ):
            result = await _build_tools_response("user_123")

        assert result.total_count == 2
        names = {t.name for t in result.tools}
        assert names == {"tool_a", "tool_b"}

    async def test_user_without_integration_sees_nothing(self) -> None:
        global_mcp = {
            "custom_1": {"name": "My MCP", "icon_url": None, "tools": [{"name": "tool_a"}]}
        }
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
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
                "app.services.tools.tools_service.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[],  # user has no integrations
            ),
        ):
            result = await _build_tools_response("user_123")

        assert result.total_count == 0


# ---------------------------------------------------------------------------
# _build_tools_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildToolsResponse:
    """Tests for the unified _build_tools_response which handles both registry tools
    and MCP tools, scoped to the user's workspace via get_user_integration_records."""

    def _patch_deps(
        self,
        registry_cats: dict,
        global_mcp: dict,
        user_records: list | None = None,
        mcp_raises: bool = False,
    ) -> ExitStack:
        """Context manager factory that patches the three external dependencies."""
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value=registry_cats)
        mock_mcp_store = MagicMock()
        if mcp_raises:
            mock_mcp_store.get_all_mcp_tools = AsyncMock(side_effect=Exception("mcp fail"))
        else:
            mock_mcp_store.get_all_mcp_tools = AsyncMock(return_value=global_mcp)

        stack = ExitStack()
        stack.enter_context(
            patch(
                "app.services.tools.tools_service.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            )
        )
        stack.enter_context(
            patch(
                "app.services.tools.tools_service.get_mcp_tools_store",
                return_value=mock_mcp_store,
            )
        )
        if user_records is not None:
            stack.enter_context(
                patch(
                    "app.services.tools.tools_service.get_user_integration_records",
                    new_callable=AsyncMock,
                    return_value=user_records,
                )
            )
        return stack

    async def test_builds_from_registry_tools(self) -> None:
        tool = _mock_tool("my_tool")
        cat = _mock_category(tools=[tool], integration_name=None)

        with self._patch_deps({"general": cat}, {}, user_records=[]):
            with patch("app.services.tools.tools_service.get_integration_name", return_value=None):
                result = await _build_tools_response("user_a")

        assert isinstance(result, ToolsListResponse)
        assert result.total_count == 1
        assert result.tools[0].name == "my_tool"
        assert "general" in result.categories

    async def test_skips_duplicate_tools_from_registry(self) -> None:
        tool = _mock_tool("dup_tool")
        cat = _mock_category(tools=[tool, tool])

        with self._patch_deps({"cat1": cat}, {}, user_records=[]):
            with patch("app.services.tools.tools_service.get_integration_name", return_value=None):
                result = await _build_tools_response()

        assert result.total_count == 1

    async def test_includes_mcp_tools_for_workspace_user(self) -> None:
        """Tools from MCP integrations appear when the user has that integration added."""
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})

        global_mcp = {
            "custom_abc": {
                "name": "My Custom MCP",
                "icon_url": "https://example.com/icon.png",
                "tools": [{"name": "custom_tool_1"}],
            }
        }
        # User has custom_abc added and connected
        user_records = [{"integration_id": "custom_abc", "status": "connected"}]

        with self._patch_deps({}, global_mcp, user_records=user_records):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].name == "custom_tool_1"
        assert result.tools[0].icon_url == "https://example.com/icon.png"

    async def test_excludes_mcp_tools_not_in_workspace(self) -> None:
        """MCP tools are not shown when the user hasn't added that integration."""
        global_mcp = {
            "deepwiki": {
                "name": "DeepWiki",
                "icon_url": None,
                "tools": [{"name": "search_wiki"}],
            }
        }
        # User has no integrations added
        with self._patch_deps({}, global_mcp, user_records=[]):
            result = await _build_tools_response("user_123")

        assert result.total_count == 0

    async def test_includes_global_mcp_tools_when_in_workspace(self) -> None:
        """Platform MCP tools appear when the user has that integration added."""
        global_mcp = {
            "deepwiki": {
                "name": "DeepWiki",
                "icon_url": None,
                "tools": [{"name": "search_wiki"}],
            }
        }
        user_records = [{"integration_id": "deepwiki", "status": "connected"}]

        with self._patch_deps({}, global_mcp, user_records=user_records):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].name == "search_wiki"
        assert result.tools[0].display_name == "DeepWiki"

    async def test_anonymous_user_gets_no_mcp_tools(self) -> None:
        """Anonymous callers (user_id=None) get no MCP tools — workspace is empty."""
        global_mcp = {
            "deepwiki": {
                "name": "DeepWiki",
                "icon_url": None,
                "tools": [{"name": "search_wiki"}],
            }
        }
        with self._patch_deps({}, global_mcp):
            result = await _build_tools_response()

        assert result.total_count == 0

    async def test_mcp_fetch_failure_graceful(self) -> None:
        with self._patch_deps({}, {}, mcp_raises=True, user_records=[]):
            result = await _build_tools_response("user_a")

        assert result.total_count == 0

    async def test_mcp_skips_empty_tools_list(self) -> None:
        global_mcp = {"my_int": {"name": "My Int", "icon_url": None, "tools": []}}
        user_records = [{"integration_id": "my_int", "status": "connected"}]

        with self._patch_deps({}, global_mcp, user_records=user_records):
            result = await _build_tools_response("user_123")

        assert result.total_count == 0

    async def test_mcp_skips_tool_without_name(self) -> None:
        global_mcp = {
            "cust_1": {
                "name": "Cust",
                "icon_url": None,
                "tools": [{"name": None}, {"name": "valid_tool"}],
            }
        }
        user_records = [{"integration_id": "cust_1", "status": "connected"}]

        with self._patch_deps({}, global_mcp, user_records=user_records):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].name == "valid_tool"

    async def test_mcp_skips_duplicate_tool_names(self) -> None:
        tool = _mock_tool("shared_tool")
        cat = _mock_category(tools=[tool])
        global_mcp = {
            "other_int": {
                "tools": [{"name": "shared_tool"}, {"name": "unique_tool"}],
            }
        }
        user_records = [{"integration_id": "other_int", "status": "connected"}]

        with self._patch_deps({"cat1": cat}, global_mcp, user_records=user_records):
            with patch("app.services.tools.tools_service.get_integration_name", return_value=None):
                result = await _build_tools_response("user_123")

        names = [t.name for t in result.tools]
        assert names.count("shared_tool") == 1
        assert "unique_tool" in names

    async def test_added_but_not_connected_is_locked(self) -> None:
        """Tools for integrations in `added` but not `connected` are marked locked=True."""
        global_mcp = {
            "my_mcp": {
                "name": "My MCP",
                "icon_url": None,
                "tools": [{"name": "a_tool"}],
            }
        }
        # added but not connected
        user_records = [{"integration_id": "my_mcp", "status": "added"}]

        with self._patch_deps({}, global_mcp, user_records=user_records):
            result = await _build_tools_response("user_123")

        assert result.total_count == 1
        assert result.tools[0].locked is True


# ---------------------------------------------------------------------------
# get_tools_by_category
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetToolsByCategory:
    async def test_returns_tools_for_category(self) -> None:
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

    async def test_returns_empty_for_unknown_category(self) -> None:
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
    async def test_returns_category_counts(self) -> None:
        cat1 = _mock_category(tools=[_mock_tool("t1"), _mock_tool("t2")])
        cat2 = _mock_category(tools=[_mock_tool("t3")])
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={"c1": cat1, "c2": cat2})

        with patch(
            "app.services.tools.tools_service.get_tool_registry",
            new_callable=AsyncMock,
            return_value=mock_registry,
        ):
            result = await get_tool_categories()

        assert result == {"c1": 2, "c2": 1}


# ---------------------------------------------------------------------------
# Locked state and workspace filtering
# (replaces the old get_user_mcp_tools and merge_tools_responses tests)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLockedAndFilteredTools:
    """Verifies workspace-scoping and locked/unlocked state in _build_tools_response.
    This replaces the old get_user_mcp_tools / merge_tools_responses test classes;
    that merging is now handled inside _build_tools_response."""

    async def _build(self, user_records: list, global_mcp: dict) -> ToolsListResponse:
        mock_registry = AsyncMock()
        mock_registry.get_all_category_objects = MagicMock(return_value={})
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
                "app.services.tools.tools_service.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=user_records,
            ),
        ):
            return await _build_tools_response("user_123")

    async def test_connected_integration_tools_not_locked(self) -> None:
        global_mcp = {"m1": {"name": "M1", "icon_url": None, "tools": [{"name": "t1"}]}}
        result = await self._build([{"integration_id": "m1", "status": "connected"}], global_mcp)
        assert result.total_count == 1
        assert result.tools[0].locked is False

    async def test_added_not_connected_tools_are_locked(self) -> None:
        global_mcp = {"m1": {"name": "M1", "icon_url": None, "tools": [{"name": "t1"}]}}
        result = await self._build([{"integration_id": "m1", "status": "added"}], global_mcp)
        assert result.total_count == 1
        assert result.tools[0].locked is True

    async def test_unadded_integration_filtered_out(self) -> None:
        global_mcp = {"m1": {"name": "M1", "icon_url": None, "tools": [{"name": "t1"}]}}
        result = await self._build([], global_mcp)
        assert result.total_count == 0

    async def test_icon_url_forwarded_from_mcp_store(self) -> None:
        global_mcp = {
            "m1": {
                "name": "MCP One",
                "icon_url": "https://example.com/icon.png",
                "tools": [{"name": "tool_a"}, {"name": "tool_b"}],
            }
        }
        result = await self._build([{"integration_id": "m1", "status": "connected"}], global_mcp)
        assert result.total_count == 2
        assert all(t.icon_url == "https://example.com/icon.png" for t in result.tools)

    async def test_duplicate_tool_names_deduplicated(self) -> None:
        """The same tool name from two different MCPs counts only once."""
        global_mcp = {
            "m1": {"name": "M1", "icon_url": None, "tools": [{"name": "same_tool"}]},
            "m2": {"name": "M2", "icon_url": None, "tools": [{"name": "same_tool"}]},
        }
        result = await self._build(
            [
                {"integration_id": "m1", "status": "connected"},
                {"integration_id": "m2", "status": "connected"},
            ],
            global_mcp,
        )
        assert result.total_count == 1

    async def test_empty_tools_list_skipped(self) -> None:
        global_mcp = {"m1": {"name": "M1", "icon_url": None, "tools": []}}
        result = await self._build([{"integration_id": "m1", "status": "connected"}], global_mcp)
        assert result.total_count == 0

    async def test_tool_with_no_name_skipped(self) -> None:
        global_mcp = {
            "m1": {
                "name": "M1",
                "icon_url": None,
                "tools": [{"name": None}, {"name": "valid"}],
            }
        }
        result = await self._build([{"integration_id": "m1", "status": "connected"}], global_mcp)
        assert result.total_count == 1
        assert result.tools[0].name == "valid"
