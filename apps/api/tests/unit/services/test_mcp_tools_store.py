"""Tests for app/services/mcp/mcp_tools_store.py.

UNIT: app/services/mcp/mcp_tools_store.py

================================ BEHAVIOR SPEC ================================

_format_tools(tools)
  EXPECTED: normalize each tool to {"name", "description"} with both stripped,
            dropping any entry whose stripped name is empty/missing.
  MECHANISM: list comprehension; t.get("name", "").strip() guards inclusion;
             name and description are independently stripped.
  MUST-CATCH:
    - whitespace is stripped from BOTH name and description (not just one)
    - the guard uses stripped name: "  ", "", and missing-key entries are dropped
    - valid entries are kept even when description is empty
    - output keys are exactly "name" and "description"

MCPToolsStore.store_tools(integration_id, tools)
  EXPECTED: upsert the formatted tools for one integration, invalidate the
            shared cache, and schedule a background cache refresh. No-op for
            empty input or all-filtered input. DB errors propagate.
  MECHANISM: early-return on `not tools`; early-return on `not formatted_tools`;
             update_one(filter, {"$set": {"tools", "integration_id"}}, upsert=True);
             delete_cache(MCP_TOOLS_CACHE_KEY); create_task(_refresh_cache).
  MUST-CATCH:
    - empty tools list -> no DB write, no cache invalidation
    - all-filtered tools (no valid name) -> no DB write
    - filter is {"integration_id": id}; $set carries formatted tools + id; upsert=True
    - cache invalidated with exactly MCP_TOOLS_CACHE_KEY
    - update_one error propagates (no silent swallow)

MCPToolsStore.store_tools_batch(items)
  EXPECTED: build one UpdateOne per integration that has at least one valid tool,
            bulk_write them, invalidate cache, schedule refresh. Skip integrations
            whose tools all filter out. No ops -> no write. DB errors propagate.
  MECHANISM: per-item _format_tools; skip empties; bulk_write(ops); delete_cache;
             create_task(_refresh_cache).
  MUST-CATCH:
    - all-filtered single item -> no bulk_write
    - mixed items -> only valid integrations produce ops (count + payload)
    - each UpdateOne carries the right filter, $set, upsert=True
    - cache invalidated with MCP_TOOLS_CACHE_KEY
    - bulk_write error propagates

MCPToolsStore.get_tools(integration_id)
  EXPECTED: return the stored tools list for an integration, None if missing or
            on error.
  MECHANISM: find_one(filter, projection); return doc.get("tools") if doc else None.
  MUST-CATCH:
    - found doc -> returns its "tools" value
    - no doc -> returns None
    - find_one called with the integration_id filter
    - exception -> returns None (swallowed)

MCPToolsStore.get_all_mcp_tools()
  EXPECTED: return cache hit verbatim; otherwise query non-empty-tools docs, group
            by integration_id into {"tools","name","icon_url"}, cache the result,
            and return it. Skip docs missing integration_id or tools. Error -> {}.
  MECHANISM: get_cache; if cached return it; find(filter, projection); async-iter
             grouping; set_cache(key, grouped, ttl); return grouped.
  MUST-CATCH:
    - cache hit short-circuits DB (find not called) and returns cached verbatim
    - cache miss queries with the non-empty-tools filter + projection
    - grouped value shape is exactly {"tools","name","icon_url"} from doc fields
    - docs without integration_id are skipped; docs with empty tools are skipped
    - set_cache called with MCP_TOOLS_CACHE_KEY, the grouped dict, and the TTL
    - exception -> returns {}

MCPToolsStore._refresh_cache()
  EXPECTED: re-warm cache by calling get_all_mcp_tools; swallow any error.
  MECHANISM: try get_all_mcp_tools(); except -> log.warning only.
  MUST-CATCH:
    - delegates to get_all_mcp_tools
    - exception is swallowed (does not raise)

get_mcp_tools_store()
  EXPECTED: return a fresh MCPToolsStore instance each call.
  MUST-CATCH: returns MCPToolsStore; not a shared singleton.

EQUIVALENT MUTANTS (allowed survivors, justified):
  - none expected: the projection passed to find()/find_one() is asserted exactly,
    so even projection-literal mutations are killed.
==============================================================================
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo import UpdateOne
import pytest

from app.constants.cache import MCP_TOOLS_CACHE_KEY, MCP_TOOLS_CACHE_TTL
from app.services.mcp.mcp_tools_store import (
    MCPToolsStore,
    _format_tools,
    get_mcp_tools_store,
)

MODULE = "app.services.mcp.mcp_tools_store"


def _make_collection() -> MagicMock:
    """Async-capable mock of the integrations Mongo collection."""
    coll = MagicMock()
    coll.update_one = AsyncMock()
    coll.bulk_write = AsyncMock()
    coll.find_one = AsyncMock()
    coll.find = MagicMock()
    return coll


def _async_cursor(docs: list[dict]):
    """Return an async iterator yielding the given docs, like a Motor cursor."""

    async def _gen():
        for d in docs:
            yield d

    return _gen()


# ---------------------------------------------------------------------------
# _format_tools
# ---------------------------------------------------------------------------


class TestFormatTools:
    def test_strips_whitespace_from_both_fields(self):
        result = _format_tools([{"name": "  my_tool  ", "description": "  desc  "}])
        assert result == [{"name": "my_tool", "description": "desc"}]

    def test_drops_entries_with_empty_missing_or_whitespace_name(self):
        tools = [
            {"name": "", "description": "empty"},
            {"description": "missing key"},
            {"name": "   ", "description": "whitespace only"},
        ]
        assert _format_tools(tools) == []

    def test_keeps_valid_entry_even_with_empty_description(self):
        # description missing -> defaults to "" then stripped to "".
        result = _format_tools([{"name": "b"}])
        assert result == [{"name": "b", "description": ""}]

    def test_filters_only_invalid_preserving_order(self):
        tools = [
            {"name": "good", "description": "ok"},
            {"name": "", "description": "bad"},
            {"name": "also_good", "description": "fine"},
        ]
        assert _format_tools(tools) == [
            {"name": "good", "description": "ok"},
            {"name": "also_good", "description": "fine"},
        ]

    def test_empty_input_returns_empty(self):
        assert _format_tools([]) == []


# ---------------------------------------------------------------------------
# MCPToolsStore.store_tools
# ---------------------------------------------------------------------------


class TestStoreTools:
    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_empty_tools_is_noop(self, mock_coll: MagicMock, mock_del: AsyncMock):
        await MCPToolsStore().store_tools("int-1", [])
        mock_coll.update_one.assert_not_called()
        mock_del.assert_not_awaited()

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_all_filtered_tools_is_noop(self, mock_coll: MagicMock, mock_del: AsyncMock):
        await MCPToolsStore().store_tools("int-1", [{"name": "  ", "description": "x"}])
        mock_coll.update_one.assert_not_called()
        mock_del.assert_not_awaited()

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_upserts_formatted_tools_and_invalidates_cache(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        await store.store_tools("int-1", [{"name": "  tool_a  ", "description": "  d  "}])

        mock_coll.update_one.assert_awaited_once()
        args, kwargs = mock_coll.update_one.call_args
        assert args[0] == {"integration_id": "int-1"}
        assert args[1] == {
            "$set": {
                "tools": [{"name": "tool_a", "description": "d"}],
                "integration_id": "int-1",
            }
        }
        assert kwargs == {"upsert": True}
        mock_del.assert_awaited_once_with(MCP_TOOLS_CACHE_KEY)

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_schedules_background_refresh(self, mock_coll: MagicMock, mock_del: AsyncMock):
        store = MCPToolsStore()
        refresh = AsyncMock()
        store._refresh_cache = refresh  # type: ignore[method-assign]

        await store.store_tools("int-1", [{"name": "t", "description": "d"}])

        # The background task is real: yield control so it runs to completion.
        await asyncio.sleep(0)
        refresh.assert_awaited_once_with()

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_db_error_propagates(self, mock_coll: MagicMock, mock_del: AsyncMock):
        mock_coll.update_one.side_effect = RuntimeError("db error")
        with pytest.raises(RuntimeError, match="db error"):
            await MCPToolsStore().store_tools("int-1", [{"name": "t", "description": "d"}])
        mock_del.assert_not_awaited()


# ---------------------------------------------------------------------------
# MCPToolsStore.store_tools_batch
# ---------------------------------------------------------------------------


class TestStoreToolsBatch:
    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_all_filtered_is_noop(self, mock_coll: MagicMock, mock_del: AsyncMock):
        await MCPToolsStore().store_tools_batch([("int-1", [{"name": "  ", "description": "x"}])])
        mock_coll.bulk_write.assert_not_called()
        mock_del.assert_not_awaited()

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_builds_one_updateone_per_valid_integration(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        items = [
            ("int-1", [{"name": "  t1  ", "description": "  d1  "}]),
            ("int-2", [{"name": "t2", "description": "d2"}]),
        ]
        await store.store_tools_batch(items)

        mock_coll.bulk_write.assert_awaited_once()
        ops = mock_coll.bulk_write.call_args[0][0]
        assert len(ops) == 2
        assert all(isinstance(op, UpdateOne) for op in ops)
        # pymongo UpdateOne stores filter under ._filter, the update doc under
        # ._doc, and the upsert flag under ._upsert.
        assert ops[0]._filter == {"integration_id": "int-1"}
        assert ops[0]._doc == {
            "$set": {
                "tools": [{"name": "t1", "description": "d1"}],
                "integration_id": "int-1",
            }
        }
        assert ops[0]._upsert is True
        assert ops[1]._filter == {"integration_id": "int-2"}
        mock_del.assert_awaited_once_with(MCP_TOOLS_CACHE_KEY)

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_skips_integration_whose_tools_all_filter_out(
        self, mock_coll: MagicMock, mock_del: AsyncMock
    ):
        store = MCPToolsStore()
        store._refresh_cache = AsyncMock()  # type: ignore[method-assign]

        items = [
            ("int-1", [{"name": "t1", "description": "d1"}]),
            ("int-2", [{"name": "", "description": "bad"}]),  # filtered out entirely
        ]
        await store.store_tools_batch(items)

        ops = mock_coll.bulk_write.call_args[0][0]
        assert len(ops) == 1
        assert ops[0]._filter == {"integration_id": "int-1"}

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_db_error_propagates(self, mock_coll: MagicMock, mock_del: AsyncMock):
        mock_coll.bulk_write.side_effect = RuntimeError("bulk error")
        with pytest.raises(RuntimeError, match="bulk error"):
            await MCPToolsStore().store_tools_batch(
                [("int-1", [{"name": "t", "description": "d"}])]
            )
        mock_del.assert_not_awaited()


# ---------------------------------------------------------------------------
# MCPToolsStore.get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_returns_stored_tools_with_correct_filter(self, mock_coll: MagicMock):
        stored = [{"name": "t1", "description": "d1"}]
        mock_coll.find_one.return_value = {"tools": stored}

        result = await MCPToolsStore().get_tools("int-1")

        assert result == stored
        # Filter selects the integration; projection fetches only the tools field.
        assert mock_coll.find_one.call_args[0] == (
            {"integration_id": "int-1"},
            {"tools": 1},
        )

    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_returns_none_when_no_doc(self, mock_coll: MagicMock):
        mock_coll.find_one.return_value = None
        assert await MCPToolsStore().get_tools("int-missing") is None

    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_returns_none_on_exception(self, mock_coll: MagicMock):
        mock_coll.find_one.side_effect = RuntimeError("err")
        assert await MCPToolsStore().get_tools("int-1") is None


# ---------------------------------------------------------------------------
# MCPToolsStore.get_all_mcp_tools
# ---------------------------------------------------------------------------


class TestGetAllMcpTools:
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_cache_hit_short_circuits_db(
        self, mock_coll: MagicMock, mock_get: AsyncMock, mock_set: AsyncMock
    ):
        cached = {"int-1": {"tools": [{"name": "t"}], "name": "n", "icon_url": "u"}}
        mock_get.return_value = cached

        result = await MCPToolsStore().get_all_mcp_tools()

        assert result == cached
        mock_get.assert_awaited_once_with(MCP_TOOLS_CACHE_KEY)
        mock_coll.find.assert_not_called()
        mock_set.assert_not_awaited()

    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_cache_miss_queries_groups_and_caches(
        self, mock_coll: MagicMock, mock_get: AsyncMock, mock_set: AsyncMock
    ):
        mock_get.return_value = None
        docs = [
            {
                "integration_id": "int-1",
                "tools": [{"name": "t1", "description": "d1"}],
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
        mock_coll.find.return_value = _async_cursor(docs)

        result = await MCPToolsStore().get_all_mcp_tools()

        # Exact filter + projection guard the literal mutations on the query.
        assert mock_coll.find.call_args[0] == (
            {"tools": {"$exists": True, "$ne": []}},
            {"integration_id": 1, "tools": 1, "name": 1, "icon_url": 1},
        )
        assert result == {
            "int-1": {
                "tools": [{"name": "t1", "description": "d1"}],
                "name": "Integration 1",
                "icon_url": "https://icon.png",
            },
            "int-2": {
                "tools": [{"name": "t2"}],
                "name": "Integration 2",
                "icon_url": None,
            },
        }
        mock_set.assert_awaited_once_with(MCP_TOOLS_CACHE_KEY, result, ttl=MCP_TOOLS_CACHE_TTL)

    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_skips_docs_missing_integration_id(
        self, mock_coll: MagicMock, mock_get: AsyncMock, mock_set: AsyncMock
    ):
        mock_get.return_value = None
        docs = [
            {"integration_id": None, "tools": [{"name": "t"}], "name": "n"},
            {"tools": [{"name": "t"}], "name": "n"},  # no integration_id key
            {"integration_id": "ok", "tools": [{"name": "t"}], "name": "n", "icon_url": "u"},
        ]
        mock_coll.find.return_value = _async_cursor(docs)

        result = await MCPToolsStore().get_all_mcp_tools()
        assert list(result.keys()) == ["ok"]

    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_skips_docs_with_empty_tools(
        self, mock_coll: MagicMock, mock_get: AsyncMock, mock_set: AsyncMock
    ):
        mock_get.return_value = None
        docs = [
            {"integration_id": "empty", "tools": [], "name": "n"},
            {"integration_id": "ok", "tools": [{"name": "t"}], "name": "n", "icon_url": "u"},
        ]
        mock_coll.find.return_value = _async_cursor(docs)

        result = await MCPToolsStore().get_all_mcp_tools()
        assert list(result.keys()) == ["ok"]

    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.integrations_collection", new_callable=_make_collection)
    async def test_exception_returns_empty_dict_and_skips_caching(
        self, mock_coll: MagicMock, mock_get: AsyncMock, mock_set: AsyncMock
    ):
        mock_get.return_value = None
        mock_coll.find.side_effect = RuntimeError("db error")

        result = await MCPToolsStore().get_all_mcp_tools()
        assert result == {}
        mock_set.assert_not_awaited()


# ---------------------------------------------------------------------------
# MCPToolsStore._refresh_cache
# ---------------------------------------------------------------------------


class TestRefreshCache:
    async def test_delegates_to_get_all_mcp_tools(self):
        store = MCPToolsStore()
        store.get_all_mcp_tools = AsyncMock(return_value={"int-1": {}})  # type: ignore[method-assign]
        await store._refresh_cache()
        store.get_all_mcp_tools.assert_awaited_once_with()

    async def test_swallows_exception(self):
        store = MCPToolsStore()
        store.get_all_mcp_tools = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        await store._refresh_cache()  # must not raise


# ---------------------------------------------------------------------------
# get_mcp_tools_store
# ---------------------------------------------------------------------------


class TestGetMcpToolsStore:
    def test_returns_fresh_instance_each_call(self):
        s1 = get_mcp_tools_store()
        s2 = get_mcp_tools_store()
        assert isinstance(s1, MCPToolsStore)
        assert isinstance(s2, MCPToolsStore)
        assert s1 is not s2
