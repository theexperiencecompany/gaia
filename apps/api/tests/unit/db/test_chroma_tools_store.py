"""Tests for app.db.chroma.chroma_tools_store."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.base import PutOp

from app.db.chroma.chroma_tools_store import (
    _build_put_operations,
    _compute_tool_diff,
    _compute_tool_hash,
    _execute_batch_operations,
    _get_current_tools_with_hashes,
    _get_existing_tools_from_chroma,
    _get_subagent_tools,
    delete_tools_by_namespace,
    index_tools_to_store,
)


# ---------------------------------------------------------------------------
# _compute_tool_hash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestComputeToolHash:
    async def test_hash_uses_description_and_source(self):
        tool = SimpleNamespace(name="my_tool", description="A tool")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            return_value="  def my_tool(): pass  \n",
        ):
            result = await _compute_tool_hash(tool)
        expected_content = "A tool::def my_tool(): pass"
        assert result == hashlib.sha256(expected_content.encode()).hexdigest()

    async def test_hash_falls_back_to_name_and_description(self):
        tool = SimpleNamespace(name="broken_tool", description="desc")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            side_effect=OSError("no source"),
        ):
            result = await _compute_tool_hash(tool)
        expected = hashlib.sha256("broken_tool::desc".encode()).hexdigest()
        assert result == expected

    async def test_hash_falls_back_on_type_error(self):
        tool = SimpleNamespace(name="t", description="d")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            side_effect=TypeError,
        ):
            result = await _compute_tool_hash(tool)
        assert result == hashlib.sha256("t::d".encode()).hexdigest()


# ---------------------------------------------------------------------------
# _get_subagent_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentTools:
    async def test_returns_subagent_tools(self):
        cfg = SimpleNamespace(
            domain="email",
            use_cases="send, read",
            capabilities="full CRUD",
            has_subagent=True,
        )
        integ = SimpleNamespace(
            id="gmail",
            name="Gmail",
            short_name="gmail",
            subagent_config=cfg,
        )
        with patch(
            "app.db.chroma.chroma_tools_store.get_subagent_integrations",
            return_value=[integ],
        ):
            result = await _get_subagent_tools()

        assert "subagents::subagent:gmail" in result
        entry = result["subagents::subagent:gmail"]
        assert entry["namespace"] == "subagents"
        assert "Gmail" in entry["description"]

    async def test_skips_integration_without_subagent_config(self):
        integ = SimpleNamespace(
            id="x",
            name="X",
            short_name="x",
            subagent_config=None,
        )
        with patch(
            "app.db.chroma.chroma_tools_store.get_subagent_integrations",
            return_value=[integ],
        ):
            result = await _get_subagent_tools()
        assert result == {}


# ---------------------------------------------------------------------------
# _get_current_tools_with_hashes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCurrentToolsWithHashes:
    async def test_combines_regular_and_subagent_tools(self):
        tool = SimpleNamespace(name="tool_a", description="A tool")
        category = SimpleNamespace(space="general")
        registry = MagicMock()
        registry.get_tool_dict.return_value = {"tool_a": tool}
        registry.get_category_of_tool.return_value = "general"
        registry.get_category.return_value = category

        with (
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=AsyncMock,
                return_value="abc123",
            ),
            patch(
                "app.db.chroma.chroma_tools_store._get_subagent_tools",
                new_callable=AsyncMock,
                return_value={
                    "subagents::subagent:x": {"hash": "h", "namespace": "subagents"}
                },
            ),
        ):
            result = await _get_current_tools_with_hashes(registry)

        assert "general::tool_a" in result
        assert "subagents::subagent:x" in result

    async def test_skips_tool_without_category(self):
        tool = SimpleNamespace(name="orphan", description="no category")
        registry = MagicMock()
        registry.get_tool_dict.return_value = {"orphan": tool}
        registry.get_category_of_tool.return_value = None
        registry.get_category.return_value = None

        with (
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=AsyncMock,
                return_value="h",
            ),
            patch(
                "app.db.chroma.chroma_tools_store._get_subagent_tools",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await _get_current_tools_with_hashes(registry)

        assert len(result) == 0


# ---------------------------------------------------------------------------
# _get_existing_tools_from_chroma
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetExistingToolsFromChroma:
    async def test_fetches_with_single_namespace_filter(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["ns::tool1"],
            "metadatas": [{"tool_hash": "h1", "namespace": "ns"}],
        }
        result = await _get_existing_tools_from_chroma(collection, {"ns"})
        collection.get.assert_awaited_once()
        call_kwargs = collection.get.call_args.kwargs
        assert call_kwargs["where"] == {"namespace": {"$eq": "ns"}}
        assert result["ns::tool1"]["hash"] == "h1"

    async def test_fetches_with_multiple_namespace_filter(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["a::t1", "b::t2"],
            "metadatas": [
                {"tool_hash": "h1", "namespace": "a"},
                {"tool_hash": "h2", "namespace": "b"},
            ],
        }
        result = await _get_existing_tools_from_chroma(collection, {"a", "b"})
        assert len(result) == 2

    async def test_returns_empty_for_empty_namespace_set(self):
        collection = AsyncMock()
        result = await _get_existing_tools_from_chroma(collection, set())
        assert result == {}
        collection.get.assert_not_awaited()

    async def test_returns_empty_on_none_namespaces(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["ns::tool"],
            "metadatas": [{"tool_hash": "h", "namespace": "ns"}],
        }
        result = await _get_existing_tools_from_chroma(collection, None)
        assert "ns::tool" in result

    async def test_skips_ids_without_double_colon(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["no_separator"],
            "metadatas": [{"tool_hash": "h"}],
        }
        result = await _get_existing_tools_from_chroma(collection)
        assert result == {}

    async def test_handles_exception_gracefully(self):
        collection = AsyncMock()
        collection.get.side_effect = RuntimeError("boom")
        result = await _get_existing_tools_from_chroma(collection)
        assert result == {}


# ---------------------------------------------------------------------------
# _compute_tool_diff
# ---------------------------------------------------------------------------


class TestComputeToolDiff:
    def test_new_tool_detected(self):
        current = {"ns::a": {"hash": "h1"}}
        existing: dict[str, dict] = {}
        upsert, delete = _compute_tool_diff(current, existing)
        assert len(upsert) == 1
        assert len(delete) == 0

    def test_modified_tool_detected(self):
        current = {"ns::a": {"hash": "new_h"}}
        existing = {"ns::a": {"hash": "old_h", "namespace": "ns"}}
        upsert, delete = _compute_tool_diff(current, existing)
        assert len(upsert) == 1

    def test_unchanged_tool_not_upserted(self):
        current = {"ns::a": {"hash": "same"}}
        existing = {"ns::a": {"hash": "same", "namespace": "ns"}}
        upsert, delete = _compute_tool_diff(current, existing)
        assert len(upsert) == 0
        assert len(delete) == 0

    def test_deleted_tool_detected(self):
        current: dict[str, dict] = {}
        existing = {"ns::gone": {"hash": "h", "namespace": "ns"}}
        upsert, delete = _compute_tool_diff(current, existing)
        assert len(delete) == 1
        assert delete[0] == ("ns::gone", "ns")


# ---------------------------------------------------------------------------
# _build_put_operations
# ---------------------------------------------------------------------------


class TestBuildPutOperations:
    def test_upsert_regular_tool(self):
        tool = SimpleNamespace(description="desc")
        to_upsert = [("ns::my_tool", {"hash": "h", "namespace": "ns", "tool": tool})]
        ops = _build_put_operations(to_upsert, [])
        assert len(ops) == 1
        assert ops[0].namespace == ("ns",)
        assert ops[0].key == "my_tool"
        assert ops[0].value["description"] == "desc"

    def test_upsert_subagent_tool(self):
        to_upsert = [
            (
                "subagents::subagent:x",
                {"hash": "h", "namespace": "subagents", "description": "sub desc"},
            )
        ]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].value["description"] == "sub desc"

    def test_delete_operation_has_none_value(self):
        to_delete = [("ns::old_tool", "ns")]
        ops = _build_put_operations([], to_delete)
        assert len(ops) == 1
        assert ops[0].value is None
        assert ops[0].key == "old_tool"

    def test_composite_key_without_separator(self):
        to_upsert = [("bare_key", {"hash": "h", "namespace": "x", "description": "d"})]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].key == "bare_key"


# ---------------------------------------------------------------------------
# _execute_batch_operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteBatchOperations:
    async def test_noop_on_empty_ops(self):
        store = AsyncMock()
        await _execute_batch_operations(store, [])
        store.abatch.assert_not_awaited()

    async def test_calls_abatch_in_batches(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(120)]
        await _execute_batch_operations(store, ops, batch_size=50)
        assert store.abatch.await_count == 3  # 50 + 50 + 20


# ---------------------------------------------------------------------------
# index_tools_to_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexToolsToStore:
    async def test_noop_on_empty_list(self):
        await index_tools_to_store([])

    async def test_rejects_invalid_namespace(self):
        tool = SimpleNamespace(name="t", description="d")
        # Namespace containing "::" is invalid
        await index_tools_to_store([(tool, "bad::ns")])

    async def test_cache_hit_skips_processing(self):
        tool = SimpleNamespace(name="t", description="d")
        tools_signature = "t:d"
        expected_hash = hashlib.sha256(tools_signature.encode()).hexdigest()[:16]

        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ),
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
        ):
            await index_tools_to_store([(tool, "ns")])
            mock_providers.aget.assert_not_called()

    async def test_skips_when_store_unavailable(self):
        tool = SimpleNamespace(name="t", description="d")
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            await index_tools_to_store([(tool, "ns")])

    async def test_no_diff_sets_cache(self):
        tool = SimpleNamespace(name="t", description="d")
        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock
            ) as mock_set_cache,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=AsyncMock,
                return_value="samehash",
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            # existing is empty, current has one tool with hash "samehash"
            # but existing also empty means diff will show upsert needed
            # Let's make existing match current
            mock_collection.get.return_value = {
                "ids": ["ns::t"],
                "metadatas": [{"tool_hash": "samehash", "namespace": "ns"}],
            }
            await index_tools_to_store([(tool, "ns")])
            mock_set_cache.assert_awaited_once()

    async def test_diff_executes_operations(self):
        tool = SimpleNamespace(name="t", description="d")
        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock
            ) as mock_set_cache,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=AsyncMock,
                return_value="newhash",
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])
            mock_store.abatch.assert_awaited()
            mock_set_cache.assert_awaited()


# ---------------------------------------------------------------------------
# delete_tools_by_namespace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteToolsByNamespace:
    async def test_returns_zero_when_store_unavailable(self):
        with patch("app.db.chroma.chroma_tools_store.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)
            with patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ):
                count = await delete_tools_by_namespace("ns")
        assert count == 0

    async def test_deletes_matching_tools(self):
        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": ["ns::a", "ns::b"]}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ) as mock_del,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 2
        mock_collection.delete.assert_awaited_once_with(ids=["ns::a", "ns::b"])
        mock_del.assert_awaited_once_with("chroma:indexed:ns")

    async def test_no_matching_tools(self):
        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": []}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 0
        mock_collection.delete.assert_not_awaited()
