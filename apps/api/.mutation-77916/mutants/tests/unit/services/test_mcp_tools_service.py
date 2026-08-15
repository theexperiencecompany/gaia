"""Unit tests for the global MCP tools service (cache + shaping over the repository)."""

from unittest.mock import AsyncMock, patch

from app.models.integration_models import IntegrationTool, IntegrationToolsRecord
from app.services.mcp import mcp_tools_service

_MOD = "app.services.mcp.mcp_tools_service"


class TestFormatTools:
    def test_strips_and_keeps_named(self):
        result = mcp_tools_service._format_tools(
            [{"name": "  t1  ", "description": "  d1  "}, {"name": "t2", "description": "d2"}]
        )
        assert [t.name for t in result] == ["t1", "t2"]
        assert result[0].description == "d1"

    def test_drops_nameless(self):
        result = mcp_tools_service._format_tools(
            [{"name": "", "description": "x"}, {"name": "  ", "description": "y"}, {"name": "ok"}]
        )
        assert [t.name for t in result] == ["ok"]
        assert result[0].description == ""

    def test_drops_entries_without_a_name_key(self):
        assert mcp_tools_service._format_tools([{"description": "no name key"}, {}]) == []

    def test_empty_input(self):
        assert mcp_tools_service._format_tools([]) == []


class TestStoreMcpTools:
    async def test_stores_and_busts_cache(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock) as mock_del,
            patch(f"{_MOD}._schedule_refresh"),
        ):
            mock_repo.store_tools = AsyncMock()
            await mcp_tools_service.store_mcp_tools("int1", [{"name": "t1", "description": "d"}])

        mock_repo.store_tools.assert_awaited_once()
        stored = mock_repo.store_tools.call_args[0][1]
        assert [t.name for t in stored] == ["t1"]
        mock_del.assert_awaited_once()

    async def test_skips_when_no_valid_tools(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock) as mock_del,
        ):
            mock_repo.store_tools = AsyncMock()
            await mcp_tools_service.store_mcp_tools("int1", [{"name": "", "description": "d"}])

        mock_repo.store_tools.assert_not_awaited()
        mock_del.assert_not_awaited()

    async def test_skips_when_tool_list_is_empty(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock) as mock_del,
        ):
            mock_repo.store_tools = AsyncMock()
            await mcp_tools_service.store_mcp_tools("int1", [])

        mock_repo.store_tools.assert_not_awaited()
        mock_del.assert_not_awaited()


class TestStoreMcpToolsBatch:
    async def test_stores_every_integration_with_valid_tools(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock) as mock_del,
            patch(f"{_MOD}._schedule_refresh"),
        ):
            mock_repo.store_tools_batch = AsyncMock()
            await mcp_tools_service.store_mcp_tools_batch(
                [
                    ("i1", [{"name": "t1", "description": "d1"}]),
                    ("i2", [{"name": "t2", "description": "d2"}]),
                ]
            )

        mock_repo.store_tools_batch.assert_awaited_once()
        (items,) = mock_repo.store_tools_batch.await_args.args
        assert [(iid, [t.name for t in tools]) for iid, tools in items] == [
            ("i1", ["t1"]),
            ("i2", ["t2"]),
        ]
        mock_del.assert_awaited_once()

    async def test_drops_integrations_whose_tools_are_all_invalid(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock),
            patch(f"{_MOD}._schedule_refresh"),
        ):
            mock_repo.store_tools_batch = AsyncMock()
            await mcp_tools_service.store_mcp_tools_batch(
                [("i1", []), ("i2", [{"name": "", "description": "bad"}]), ("i3", [{"name": "t3"}])]
            )

        (items,) = mock_repo.store_tools_batch.await_args.args
        assert [iid for iid, _ in items] == ["i3"]

    async def test_skips_write_when_nothing_valid_remains(self):
        with (
            patch(f"{_MOD}.integration_repository") as mock_repo,
            patch(f"{_MOD}.delete_cache", new_callable=AsyncMock) as mock_del,
        ):
            mock_repo.store_tools_batch = AsyncMock()
            await mcp_tools_service.store_mcp_tools_batch(
                [("i1", []), ("i2", [{"name": "", "description": "bad"}])]
            )

        mock_repo.store_tools_batch.assert_not_awaited()
        mock_del.assert_not_awaited()


class TestGetIntegrationTools:
    async def test_dumps_to_dicts(self):
        with patch(f"{_MOD}.integration_repository") as mock_repo:
            mock_repo.get_tools = AsyncMock(
                return_value=[IntegrationTool(name="t1", description="d1")]
            )
            result = await mcp_tools_service.get_integration_tools("int1")

        assert result == [{"name": "t1", "description": "d1"}]

    async def test_returns_empty_when_the_repository_fails(self):
        with patch(f"{_MOD}.integration_repository") as mock_repo:
            mock_repo.get_tools = AsyncMock(side_effect=Exception("DB error"))
            assert await mcp_tools_service.get_integration_tools("int1") == []


class TestGetAllMcpTools:
    async def test_returns_cached(self):
        cached = {"int1": {"tools": [{"name": "t1"}], "name": "One", "icon_url": None}}
        with patch(f"{_MOD}.get_cache", new_callable=AsyncMock, return_value=cached):
            result = await mcp_tools_service.get_all_mcp_tools()
        assert result == cached

    async def test_builds_and_caches_from_repo(self):
        record = IntegrationToolsRecord(
            integration_id="int1",
            name="Integration 1",
            icon_url="https://ex.com/icon.png",
            tools=[IntegrationTool(name="t1", description="d")],
        )
        with (
            patch(f"{_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{_MOD}.set_cache", new_callable=AsyncMock) as mock_set,
            patch(f"{_MOD}.integration_repository") as mock_repo,
        ):
            mock_repo.all_with_tools = AsyncMock(return_value=[record])
            result = await mcp_tools_service.get_all_mcp_tools()

        assert result["int1"]["name"] == "Integration 1"
        assert result["int1"]["icon_url"] == "https://ex.com/icon.png"
        assert result["int1"]["tools"] == [{"name": "t1", "description": "d"}]
        mock_set.assert_awaited_once()

    async def test_returns_empty_when_the_repository_fails(self):
        with (
            patch(f"{_MOD}.get_cache", new_callable=AsyncMock, return_value=None),
            patch(f"{_MOD}.set_cache", new_callable=AsyncMock) as mock_set,
            patch(f"{_MOD}.integration_repository") as mock_repo,
        ):
            mock_repo.all_with_tools = AsyncMock(side_effect=Exception("DB error"))
            result = await mcp_tools_service.get_all_mcp_tools()

        assert result == {}
        mock_set.assert_not_awaited()
