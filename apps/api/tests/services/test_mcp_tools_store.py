"""Unit tests for MCPToolsStore."""

from unittest.mock import AsyncMock, MagicMock, patch


from app.services.mcp.mcp_tools_store import MCPToolsStore, _format_tools


INTEGRATION_ID = "mcp-test-001"


class TestFormatTools:
    def test_formats_valid_tools(self):
        tools = [
            {"name": "read_file", "description": "Reads a file"},
            {"name": "write_file", "description": "Writes a file"},
        ]
        result = _format_tools(tools)
        assert len(result) == 2
        assert result[0] == {
            "name": "read_file",
            "description": "Reads a file",
        }

    def test_strips_whitespace(self):
        tools = [{"name": "  tool  ", "description": "  desc  "}]
        result = _format_tools(tools)
        assert result[0]["name"] == "tool"
        assert result[0]["description"] == "desc"

    def test_filters_empty_names(self):
        tools = [
            {"name": "", "description": "no name"},
            {"name": "valid", "description": "ok"},
        ]
        result = _format_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "valid"

    def test_handles_missing_keys(self):
        tools = [{"description": "no name key"}, {}]
        result = _format_tools(tools)
        assert len(result) == 0

    def test_empty_input(self):
        assert _format_tools([]) == []


class TestStoreTools:
    async def test_stores_tools_to_mongodb(self):
        store = MCPToolsStore()
        tools = [{"name": "tool_a", "description": "does A"}]

        with (
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_coll,
            patch(
                "app.services.mcp.mcp_tools_store.delete_cache",
                new_callable=AsyncMock,
            ) as mock_delete,
            patch(
                "app.services.mcp.mcp_tools_store.asyncio.create_task",
                side_effect=lambda coro: (coro.close(), MagicMock())[1],
            ),
        ):
            mock_coll.update_one = AsyncMock()

            await store.store_tools(INTEGRATION_ID, tools)

            mock_coll.update_one.assert_awaited_once()
            call_args = mock_coll.update_one.call_args
            assert call_args[0][0] == {"integration_id": INTEGRATION_ID}
            assert call_args[1].get("upsert") is True
            mock_delete.assert_awaited_once()

    async def test_skips_empty_tools(self):
        store = MCPToolsStore()

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.update_one = AsyncMock()

            await store.store_tools(INTEGRATION_ID, [])

            mock_coll.update_one.assert_not_awaited()

    async def test_skips_tools_with_no_valid_names(self):
        store = MCPToolsStore()
        tools = [{"name": "", "description": "empty name"}]

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.update_one = AsyncMock()

            await store.store_tools(INTEGRATION_ID, tools)

            mock_coll.update_one.assert_not_awaited()


class TestGetTools:
    async def test_returns_tools_when_found(self):
        store = MCPToolsStore()
        doc = {"tools": [{"name": "t1", "description": "d1"}]}

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.find_one = AsyncMock(return_value=doc)

            result = await store.get_tools(INTEGRATION_ID)

        assert result == doc["tools"]

    async def test_returns_none_when_not_found(self):
        store = MCPToolsStore()

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.find_one = AsyncMock(return_value=None)

            result = await store.get_tools(INTEGRATION_ID)

        assert result is None

    async def test_returns_none_on_error(self):
        store = MCPToolsStore()

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.find_one = AsyncMock(side_effect=Exception("DB error"))

            result = await store.get_tools(INTEGRATION_ID)

        assert result is None


class TestGetAllMcpTools:
    async def test_returns_cached_value(self):
        store = MCPToolsStore()
        cached = {"integ-1": {"tools": [{"name": "t"}]}}

        with patch(
            "app.services.mcp.mcp_tools_store.get_cache",
            new_callable=AsyncMock,
            return_value=cached,
        ):
            result = await store.get_all_mcp_tools()

        assert result == cached

    async def test_queries_db_on_cache_miss(self):
        store = MCPToolsStore()

        async def _async_iter():
            docs = [
                {
                    "integration_id": "i1",
                    "tools": [{"name": "t1"}],
                    "name": "Int 1",
                    "icon_url": None,
                }
            ]
            for doc in docs:
                yield doc

        mock_cursor = _async_iter()

        with (
            patch(
                "app.services.mcp.mcp_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.mcp.mcp_tools_store.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_coll,
        ):
            mock_coll.find = MagicMock(return_value=mock_cursor)

            result = await store.get_all_mcp_tools()

        assert "i1" in result
        assert result["i1"]["tools"] == [{"name": "t1"}]
        mock_set.assert_awaited_once()

    async def test_returns_empty_on_error(self):
        store = MCPToolsStore()

        with (
            patch(
                "app.services.mcp.mcp_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_coll,
        ):
            mock_coll.find = MagicMock(side_effect=Exception("DB error"))

            result = await store.get_all_mcp_tools()

        assert result == {}


class TestStoreBatch:
    async def test_batch_stores_multiple(self):
        store = MCPToolsStore()
        items = [
            ("i1", [{"name": "t1", "description": "d1"}]),
            ("i2", [{"name": "t2", "description": "d2"}]),
        ]

        with (
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_coll,
            patch(
                "app.services.mcp.mcp_tools_store.delete_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.mcp.mcp_tools_store.asyncio.create_task",
                side_effect=lambda coro: (coro.close(), MagicMock())[1],
            ),
        ):
            mock_coll.bulk_write = AsyncMock()

            await store.store_tools_batch(items)

            mock_coll.bulk_write.assert_awaited_once()
            ops = mock_coll.bulk_write.call_args[0][0]
            assert len(ops) == 2

    async def test_batch_skips_empty_tools(self):
        store = MCPToolsStore()
        items = [
            ("i1", []),
            ("i2", [{"name": "", "description": "bad"}]),
        ]

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_coll:
            mock_coll.bulk_write = AsyncMock()

            await store.store_tools_batch(items)

            mock_coll.bulk_write.assert_not_awaited()
