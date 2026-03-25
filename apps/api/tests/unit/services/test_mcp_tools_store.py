"""Tests for app/services/mcp/mcp_tools_store.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.mcp_tools_store import (
    MCPToolsStore,
    _format_tools,
    get_mcp_tools_store,
)


# ---------------------------------------------------------------------------
# _format_tools
# ---------------------------------------------------------------------------


class TestFormatTools:
    def test_strips_whitespace(self):
        tools = [{"name": "  my_tool  ", "description": "  desc  "}]
        result = _format_tools(tools)
        assert result == [{"name": "my_tool", "description": "desc"}]

    def test_drops_entries_without_name(self):
        tools = [
            {"name": "", "description": "no name"},
            {"description": "missing key"},
            {"name": "  ", "description": "whitespace only"},
        ]
        result = _format_tools(tools)
        assert result == []

    def test_keeps_valid_entries(self):
        tools = [
            {"name": "a", "description": "desc a"},
            {"name": "b", "description": ""},
        ]
        result = _format_tools(tools)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"

    def test_empty_list(self):
        assert _format_tools([]) == []

    def test_mixed(self):
        tools = [
            {"name": "good", "description": "ok"},
            {"name": "", "description": "bad"},
            {"name": "also_good", "description": "fine"},
        ]
        result = _format_tools(tools)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# MCPToolsStore.store_tools
# ---------------------------------------------------------------------------


class TestStoreTools:
    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_store_tools_empty_list_returns_early(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        await store.store_tools("int-1", [])
        mock_coll.update_one.assert_not_called()

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_store_tools_all_filtered_returns_early(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        await store.store_tools("int-1", [{"name": "", "description": "x"}])
        mock_coll.update_one.assert_not_called()

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_store_tools_writes_and_invalidates_cache(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        mock_coll.update_one = AsyncMock()
        store = MCPToolsStore()
        # Mock _refresh_cache to avoid real DB call
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        await store.store_tools("int-1", [{"name": "tool_a", "description": "d"}])

        mock_coll.update_one.assert_awaited_once()
        call_args = mock_coll.update_one.call_args
        assert call_args[0][0] == {"integration_id": "int-1"}
        mock_del.assert_awaited_once()

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_store_tools_raises_on_db_error(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        mock_coll.update_one = AsyncMock(side_effect=RuntimeError("db error"))
        store = MCPToolsStore()

        with pytest.raises(RuntimeError, match="db error"):
            await store.store_tools("int-1", [{"name": "t", "description": "d"}])


# ---------------------------------------------------------------------------
# MCPToolsStore.store_tools_batch
# ---------------------------------------------------------------------------


class TestStoreToolsBatch:
    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_batch_empty_after_formatting_returns_early(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        await store.store_tools_batch([("int-1", [{"name": "", "description": "x"}])])
        mock_coll.bulk_write.assert_not_called()

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_batch_writes_and_invalidates(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        mock_coll.bulk_write = AsyncMock()
        store = MCPToolsStore()
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        items = [
            ("int-1", [{"name": "t1", "description": "d1"}]),
            ("int-2", [{"name": "t2", "description": "d2"}]),
        ]
        await store.store_tools_batch(items)

        mock_coll.bulk_write.assert_awaited_once()
        ops = mock_coll.bulk_write.call_args[0][0]
        assert len(ops) == 2
        mock_del.assert_awaited_once()

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_batch_raises_on_db_error(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        mock_coll.bulk_write = AsyncMock(side_effect=RuntimeError("bulk error"))
        store = MCPToolsStore()

        with pytest.raises(RuntimeError, match="bulk error"):
            await store.store_tools_batch(
                [("int-1", [{"name": "t", "description": "d"}])]
            )

    @patch("app.services.mcp.mcp_tools_store.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_batch_skips_empty_formatted(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        mock_coll.bulk_write = AsyncMock()
        store = MCPToolsStore()
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        items = [
            ("int-1", [{"name": "t1", "description": "d1"}]),
            ("int-2", [{"name": "", "description": "bad"}]),  # filtered out
        ]
        await store.store_tools_batch(items)
        ops = mock_coll.bulk_write.call_args[0][0]
        assert len(ops) == 1


# ---------------------------------------------------------------------------
# MCPToolsStore.get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_get_tools_found(self, mock_coll: MagicMock):
        mock_coll.find_one = AsyncMock(
            return_value={"tools": [{"name": "t1", "description": "d1"}]}
        )
        store = MCPToolsStore()
        result = await store.get_tools("int-1")
        assert result == [{"name": "t1", "description": "d1"}]

    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_get_tools_not_found(self, mock_coll: MagicMock):
        mock_coll.find_one = AsyncMock(return_value=None)
        store = MCPToolsStore()
        result = await store.get_tools("int-missing")
        assert result is None

    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_get_tools_exception_returns_none(self, mock_coll: MagicMock):
        mock_coll.find_one = AsyncMock(side_effect=RuntimeError("err"))
        store = MCPToolsStore()
        result = await store.get_tools("int-1")
        assert result is None


# ---------------------------------------------------------------------------
# MCPToolsStore.get_all_mcp_tools
# ---------------------------------------------------------------------------


class TestGetAllMcpTools:
    @patch("app.services.mcp.mcp_tools_store.set_cache", new_callable=AsyncMock)
    @patch("app.services.mcp.mcp_tools_store.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_returns_cached(
        self, mock_coll: MagicMock, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock
    ):
        cached_data = {
            "int-1": {"tools": [{"name": "t"}], "name": "n", "icon_url": "u"}
        }
        mock_get_cache.return_value = cached_data
        store = MCPToolsStore()
        result = await store.get_all_mcp_tools()
        assert result == cached_data
        mock_coll.find.assert_not_called()

    @patch("app.services.mcp.mcp_tools_store.set_cache", new_callable=AsyncMock)
    @patch("app.services.mcp.mcp_tools_store.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_queries_db_when_no_cache(
        self, mock_coll: MagicMock, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock
    ):
        mock_get_cache.return_value = None

        # Simulate async cursor iteration
        docs = [
            {
                "integration_id": "int-1",
                "tools": [{"name": "t1"}],
                "name": "Integration 1",
                "icon_url": "https://icon.png",
            },
            {
                "integration_id": "int-2",
                "tools": [{"name": "t2"}],
                "name": "Integration 2",
                "icon_url": None,
            },
        ]

        async def _async_iter():
            for d in docs:
                yield d

        mock_cursor = _async_iter()
        mock_coll.find.return_value = mock_cursor

        store = MCPToolsStore()
        result = await store.get_all_mcp_tools()

        assert "int-1" in result
        assert "int-2" in result
        assert result["int-1"]["name"] == "Integration 1"
        mock_set_cache.assert_awaited_once()

    @patch("app.services.mcp.mcp_tools_store.set_cache", new_callable=AsyncMock)
    @patch("app.services.mcp.mcp_tools_store.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_skips_docs_without_integration_id(
        self, mock_coll: MagicMock, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock
    ):
        mock_get_cache.return_value = None

        async def _async_iter():
            yield {"integration_id": None, "tools": [{"name": "t"}], "name": "n"}
            yield {
                "tools": [{"name": "t"}],
                "name": "n",
            }  # no integration_id key at all

        mock_coll.find.return_value = _async_iter()
        store = MCPToolsStore()
        result = await store.get_all_mcp_tools()
        assert result == {}

    @patch("app.services.mcp.mcp_tools_store.set_cache", new_callable=AsyncMock)
    @patch("app.services.mcp.mcp_tools_store.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_skips_docs_with_empty_tools(
        self, mock_coll: MagicMock, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock
    ):
        mock_get_cache.return_value = None

        async def _async_iter():
            yield {"integration_id": "int-1", "tools": [], "name": "n"}

        mock_coll.find.return_value = _async_iter()
        store = MCPToolsStore()
        result = await store.get_all_mcp_tools()
        assert result == {}

    @patch("app.services.mcp.mcp_tools_store.set_cache", new_callable=AsyncMock)
    @patch("app.services.mcp.mcp_tools_store.get_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_tools_store.integrations_collection",
        new_callable=MagicMock,
    )
    async def test_exception_returns_empty_dict(
        self, mock_coll: MagicMock, mock_get_cache: AsyncMock, mock_set_cache: AsyncMock
    ):
        mock_get_cache.return_value = None
        mock_coll.find.side_effect = RuntimeError("db error")

        store = MCPToolsStore()
        result = await store.get_all_mcp_tools()
        assert result == {}


# ---------------------------------------------------------------------------
# MCPToolsStore._refresh_cache
# ---------------------------------------------------------------------------


class TestRefreshCache:
    async def test_refresh_calls_get_all(self):
        store = MCPToolsStore()
        store.get_all_mcp_tools = AsyncMock(return_value={"int-1": {}})
        await store._refresh_cache()
        store.get_all_mcp_tools.assert_awaited_once()

    async def test_refresh_swallows_exception(self):
        store = MCPToolsStore()
        store.get_all_mcp_tools = AsyncMock(side_effect=RuntimeError("boom"))
        # Should not raise
        await store._refresh_cache()


# ---------------------------------------------------------------------------
# get_mcp_tools_store
# ---------------------------------------------------------------------------


class TestGetMcpToolsStore:
    def test_returns_instance(self):
        store = get_mcp_tools_store()
        assert isinstance(store, MCPToolsStore)

    def test_returns_new_instance_each_call(self):
        s1 = get_mcp_tools_store()
        s2 = get_mcp_tools_store()
        assert s1 is not s2
