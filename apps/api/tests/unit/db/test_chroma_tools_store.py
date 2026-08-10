"""Tests for app.db.chroma.chroma_tools_store."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.store.base import PutOp
import pytest

from app.constants.log_tags import LogTag
from app.db.chroma.chroma_tools_store import (
    _build_put_operations,
    _compute_tool_diff,
    _compute_tool_hash,
    _execute_batch_operations,
    _get_current_tools_with_hashes,
    _get_existing_tools_from_chroma,
    _get_subagent_tools,
    _namespace_equals,
    delete_tools_by_namespace,
    index_tools_to_store,
)
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent

MSG = {
    "hash_source_debug": f"{LogTag.CHROMA} Source unavailable for tool, using description hash",
    "existing_error": f"{LogTag.CHROMA} Error fetching existing tools, will register all tools",
    "processed_batch": f"{LogTag.CHROMA} Processed batch",
    "updated_store": f"{LogTag.CHROMA} Successfully updated tools in ChromaDB",
    "index_called": f"{LogTag.CHROMA} index_tools_to_store called",
    "index_empty": (
        f"{LogTag.CHROMA} index_tools_to_store called with EMPTY tools_with_space — caller "
        "passed [], no indexing will occur. Verify category.tools is populated."
    ),
    "index_mixed": (
        f"{LogTag.CHROMA} index_tools_to_store: mixed namespaces in single call; "
        "aborting to prevent partial indexing — caller must batch per-namespace"
    ),
    "index_invalid": (
        f"{LogTag.CHROMA} index_tools_to_store: invalid namespace "
        "(empty/too-long/contains-::), aborting"
    ),
    "index_cache_hit": (
        f"{LogTag.CHROMA} index_tools_to_store: namespace Redis cache HIT, skipping reindex of tools"
    ),
    "index_provider_none": (
        f"{LogTag.CHROMA} index_tools_to_store: provider returned None for namespace, skipping tools"
    ),
    "index_built": (
        f"{LogTag.CHROMA} index_tools_to_store: built current_tools dict of unique composite keys"
    ),
    "index_fetched": (f"{LogTag.CHROMA} index_tools_to_store: fetched existing docs for namespace"),
    "index_uptodate": (
        f"{LogTag.CHROMA} index_tools_to_store: namespace is up-to-date ( tools, no diff)"
    ),
    "index_updating": (
        f"{LogTag.CHROMA} index_tools_to_store: Updating namespace : to upsert, to delete"
    ),
    "index_completed": (
        f"{LogTag.CHROMA} index_tools_to_store: completed namespace, cache key set"
    ),
    "delete_unavailable": f"{LogTag.CHROMA} ChromaDB store not available for cleanup",
    "delete_deleted": f"{LogTag.CHROMA} Deleted tools from namespace",
}


def _log_call(mock_log: MagicMock, level: str, fragment: str) -> MagicMock:
    """Return the call to ``mock_log.<level>`` whose message or kwargs contain ``fragment``."""
    calls = getattr(mock_log, level).call_args_list
    for call in calls:
        if (call.args and fragment in call.args[0]) or (
            call.kwargs and fragment in str(call.kwargs)
        ):
            return call
    raise AssertionError(f"no log.{level} call containing {fragment!r}")


# ---------------------------------------------------------------------------
# _namespace_equals
# ---------------------------------------------------------------------------


class TestNamespaceEquals:
    def test_returns_exact_where_clause(self):
        assert _namespace_equals("ns") == {"namespace": {"$eq": "ns"}}


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
        ) as mock_getsource:
            result = _compute_tool_hash(tool)
        expected_content = "A tool::def my_tool(): pass"
        assert result == hashlib.sha256(expected_content.encode()).hexdigest()
        mock_getsource.assert_called_once_with(tool)

    async def test_hash_normalizes_multiline_source(self):
        tool = SimpleNamespace(name="my_tool", description="A tool")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            return_value="  def a(): pass  \n  def b(): pass  \n",
        ):
            result = _compute_tool_hash(tool)
        expected_content = "A tool::def a(): pass\n  def b(): pass"
        assert result == hashlib.sha256(expected_content.encode()).hexdigest()

    async def test_hash_falls_back_to_name_and_description(self):
        tool = SimpleNamespace(name="broken_tool", description="desc")
        with (
            patch(
                "app.db.chroma.chroma_tools_store.inspect.getsource",
                side_effect=OSError("no source"),
            ),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            result = _compute_tool_hash(tool)
        expected = hashlib.sha256(b"broken_tool::desc").hexdigest()
        assert result == expected
        call = _log_call(mock_log, "debug", "Source unavailable")
        assert call.kwargs == {"tool_name": "broken_tool"}

    async def test_hash_falls_back_on_type_error(self):
        tool = SimpleNamespace(name="t", description="d")
        with (
            patch(
                "app.db.chroma.chroma_tools_store.inspect.getsource",
                side_effect=TypeError,
            ),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            result = _compute_tool_hash(tool)
        assert result == hashlib.sha256(b"t::d").hexdigest()
        call = _log_call(mock_log, "debug", "Source unavailable")
        assert call.kwargs == {"tool_name": "t"}

    async def test_hash_falls_back_on_attribute_error(self):
        tool = SimpleNamespace(name="t", description="d")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            side_effect=AttributeError,
        ):
            result = _compute_tool_hash(tool)
        assert result == hashlib.sha256(b"t::d").hexdigest()

    async def test_fallback_without_tool_name_logs_unknown(self):
        tool = SimpleNamespace(description="d")
        with (
            patch(
                "app.db.chroma.chroma_tools_store.inspect.getsource",
                side_effect=OSError("no source"),
            ),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
            pytest.raises(AttributeError),
        ):
            _compute_tool_hash(tool)
        call = _log_call(mock_log, "debug", "Source unavailable")
        assert call.kwargs == {"tool_name": "unknown"}


# ---------------------------------------------------------------------------
# _get_subagent_tools
# ---------------------------------------------------------------------------


def _make_subagent(subagent_id: str, name: str, short_name: str | None) -> Subagent:
    cfg = SubAgentConfig(
        has_subagent=True,
        agent_name="gmail_agent",
        tool_space="gmail_space",
        handoff_tool_name="call_gmail",
        domain="email",
        use_cases="send, read",
        capabilities="full CRUD",
        system_prompt="You are gmail.",
    )
    return Subagent(
        id=subagent_id,
        name=name,
        provider="gmail",
        managed_by="composio",
        config=cfg,
        short_name=short_name,
    )


def _subagent_description(provider_name: str, short_name: str, cfg: SubAgentConfig) -> str:
    return (
        f"{provider_name} ({short_name}). "
        f"{provider_name} specializes in {cfg.domain}. "
        f"Use {provider_name} for: {cfg.use_cases}. "
        f"{provider_name} capabilities: {cfg.capabilities}"
    )


@pytest.mark.asyncio
class TestGetSubagentTools:
    async def test_returns_subagent_tools(self):
        subagent = _make_subagent("gmail", "Gmail", "gmail")
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(subagent,),
        ):
            result = _get_subagent_tools()

        expected_description = _subagent_description("Gmail", "gmail", subagent.config)
        expected_hash = hashlib.sha256(expected_description.encode()).hexdigest()
        assert result == {
            "subagents::subagent:gmail": {
                "hash": expected_hash,
                "namespace": "subagents",
                "description": expected_description,
            }
        }

    async def test_short_name_takes_precedence_over_id(self):
        subagent = _make_subagent("gmail", "Gmail", "short")
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(subagent,),
        ):
            result = _get_subagent_tools()

        description = result["subagents::subagent:gmail"]["description"]
        assert "Gmail (short)." in description
        expected = _subagent_description("Gmail", "short", subagent.config)
        assert description == expected
        assert (
            result["subagents::subagent:gmail"]["hash"]
            == hashlib.sha256(expected.encode()).hexdigest()
        )

    async def test_falls_back_to_id_when_short_name_falsy(self):
        subagent = _make_subagent("gmail", "Gmail", "")
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(subagent,),
        ):
            result = _get_subagent_tools()

        description = result["subagents::subagent:gmail"]["description"]
        assert "Gmail (gmail)." in description

    async def test_skips_when_registry_empty(self):
        # Registry never surfaces entries without a config; an empty registry
        # produces an empty result.
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(),
        ):
            result = _get_subagent_tools()
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
                new_callable=MagicMock,
                return_value="abc123",
            ) as mock_hash,
            patch(
                "app.db.chroma.chroma_tools_store._get_subagent_tools",
                new_callable=MagicMock,
                return_value={"subagents::subagent:x": {"hash": "h", "namespace": "subagents"}},
            ) as mock_subagents,
        ):
            result = _get_current_tools_with_hashes(registry)

        assert result == {
            "general::tool_a": {"hash": "abc123", "namespace": "general", "tool": tool},
            "subagents::subagent:x": {"hash": "h", "namespace": "subagents"},
        }
        mock_hash.assert_called_once_with(tool)
        mock_subagents.assert_called_once_with()
        registry.get_category_of_tool.assert_called_once_with("tool_a")
        registry.get_category.assert_called_once_with(name="general")

    async def test_skips_tool_without_category(self):
        tool = SimpleNamespace(name="orphan", description="no category")
        registry = MagicMock()
        registry.get_tool_dict.return_value = {"orphan": tool}
        registry.get_category_of_tool.return_value = None
        registry.get_category.return_value = None

        with (
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=MagicMock,
                return_value="h",
            ),
            patch(
                "app.db.chroma.chroma_tools_store._get_subagent_tools",
                new_callable=MagicMock,
                return_value={},
            ),
        ):
            result = _get_current_tools_with_hashes(registry)

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
        collection.get.assert_awaited_once_with(
            include=["metadatas"], where={"namespace": {"$eq": "ns"}}
        )
        assert result == {"ns::tool1": {"hash": "h1", "namespace": "ns"}}

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
        where = collection.get.await_args.kwargs["where"]
        assert list(where.keys()) == ["$or"]
        or_clauses = [d["namespace"]["$eq"] for d in where["$or"]]
        assert sorted(or_clauses) == ["a", "b"]
        assert collection.get.await_args.kwargs["include"] == ["metadatas"]
        assert result == {
            "a::t1": {"hash": "h1", "namespace": "a"},
            "b::t2": {"hash": "h2", "namespace": "b"},
        }

    async def test_returns_empty_for_empty_namespace_set(self):
        collection = AsyncMock()
        result = await _get_existing_tools_from_chroma(collection, set())
        assert result == {}
        collection.get.assert_not_awaited()

    async def test_fetches_all_when_namespaces_none(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["ns::tool"],
            "metadatas": [{"tool_hash": "h", "namespace": "ns"}],
        }
        result = await _get_existing_tools_from_chroma(collection, None)
        collection.get.assert_awaited_once_with(include=["metadatas"])
        assert "ns::tool" in result
        assert result["ns::tool"]["namespace"] == "ns"

    async def test_skips_ids_without_double_colon(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["no_separator"],
            "metadatas": [{"tool_hash": "h"}],
        }
        result = await _get_existing_tools_from_chroma(collection)
        assert result == {}

    async def test_skips_rows_missing_tool_hash(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["ns::tool"],
            "metadatas": [{"namespace": "ns"}],
        }
        result = await _get_existing_tools_from_chroma(collection, {"ns"})
        assert result["ns::tool"]["hash"] == ""

    async def test_stringifies_non_str_tool_hash(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["ns::tool"],
            "metadatas": [{"tool_hash": 123, "namespace": "ns"}],
        }
        result = await _get_existing_tools_from_chroma(collection, {"ns"})
        assert result["ns::tool"]["hash"] == "123"

    async def test_returns_empty_when_get_returns_none(self):
        collection = AsyncMock()
        collection.get.return_value = None
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            result = await _get_existing_tools_from_chroma(collection)
        assert result == {}
        mock_log.warning.assert_not_called()

    async def test_returns_empty_when_ids_is_none(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": None,
            "metadatas": [{"tool_hash": "h", "namespace": "ns"}],
        }
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            result = await _get_existing_tools_from_chroma(collection)
        assert result == {}
        mock_log.warning.assert_not_called()

    async def test_handles_exception_gracefully(self):
        collection = AsyncMock()
        collection.get.side_effect = RuntimeError("boom")
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            result = await _get_existing_tools_from_chroma(collection)
        assert result == {}
        call = _log_call(mock_log, "warning", "Error fetching existing tools")
        assert call.kwargs == {"error": "boom", "error_type": "RuntimeError"}


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
        assert ops == [
            PutOp(
                namespace=("ns",),
                key="my_tool",
                value={"description": "desc", "tool_hash": "h"},
                index=["description"],
            )
        ]

    def test_upsert_subagent_tool(self):
        to_upsert = [
            (
                "subagents::subagent:x",
                {"hash": "h", "namespace": "subagents", "description": "sub desc"},
            )
        ]
        ops = _build_put_operations(to_upsert, [])
        assert ops == [
            PutOp(
                namespace=("subagents",),
                key="subagent:x",
                value={"description": "sub desc", "tool_hash": "h"},
                index=["description"],
            )
        ]

    def test_delete_operation_has_none_value(self):
        to_delete = [("ns::old_tool", "ns")]
        ops = _build_put_operations([], to_delete)
        assert ops == [PutOp(namespace=("ns",), key="old_tool", value=None)]

    def test_composite_key_without_separator(self):
        to_upsert = [("bare_key", {"hash": "h", "namespace": "x", "description": "d"})]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].key == "bare_key"

    def test_upsert_key_with_multiple_separators(self):
        tool = SimpleNamespace(description="desc")
        to_upsert = [("a::b::c", {"hash": "h", "namespace": "a", "tool": tool})]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].key == "b::c"

    def test_delete_key_with_multiple_separators(self):
        to_delete = [("a::b::c", "a")]
        ops = _build_put_operations([], to_delete)
        assert ops[0].key == "b::c"


# ---------------------------------------------------------------------------
# _execute_batch_operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteBatchOperations:
    async def test_noop_on_empty_ops(self):
        store = AsyncMock()
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            await _execute_batch_operations(store, [])
        store.abatch.assert_not_awaited()
        mock_log.info.assert_not_called()

    async def test_calls_abatch_in_batches_with_exact_slices(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(120)]
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            await _execute_batch_operations(store, ops, batch_size=50)
        assert store.abatch.await_count == 3
        assert store.abatch.await_args_list == [
            ((ops[0:50],),),
            ((ops[50:100],),),
            ((ops[100:120],),),
        ]
        for i, batch_index in enumerate((1, 2, 3), start=1):
            call = mock_log.info.call_args_list[i - 1]
            assert MSG["processed_batch"] in call.args[0]
            assert call.kwargs == {"batch_index": batch_index, "batch_total": 3}
        final = mock_log.info.call_args_list[-1]
        assert MSG["updated_store"] in final.args[0]
        assert final.kwargs == {"total_ops": 120}

    async def test_batch_total_for_exact_multiple(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(100)]
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            await _execute_batch_operations(store, ops, batch_size=50)
        call = mock_log.info.call_args_list[0]
        assert call.kwargs == {"batch_index": 1, "batch_total": 2}

    async def test_batch_total_rounds_up(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(101)]
        with patch("app.db.chroma.chroma_tools_store.log") as mock_log:
            await _execute_batch_operations(store, ops, batch_size=50)
        call = mock_log.info.call_args_list[0]
        assert call.kwargs == {"batch_index": 1, "batch_total": 3}

    async def test_default_batch_size_splits_101_ops_into_3(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(101)]
        await _execute_batch_operations(store, ops)
        assert store.abatch.await_count == 3


# ---------------------------------------------------------------------------
# index_tools_to_store
# ---------------------------------------------------------------------------


def _tools_signature_hash(tools_with_space) -> str:
    tools_signature = "|".join(
        f"{t.name}:{getattr(t, 'description', '')[:200]}" for t, _ in tools_with_space
    )
    return hashlib.sha256(tools_signature.encode()).hexdigest()[:16]


def _mock_store(collection: AsyncMock) -> AsyncMock:
    store = AsyncMock()
    store._get_collection = AsyncMock(return_value=collection)
    return store


@pytest.mark.asyncio
class TestIndexToolsToStore:
    async def test_noop_on_empty_list(self):
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([])
        mock_get.assert_not_awaited()
        call = _log_call(mock_log, "warning", "EMPTY tools_with_space")
        assert call.args[0] == MSG["index_empty"]
        assert call.kwargs == {}

    async def test_rejects_mixed_namespaces(self):
        tool_a = SimpleNamespace(name="ta", description="da")
        tool_b = SimpleNamespace(name="tb", description="db")
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool_a, "a"), (tool_b, "b")])
        mock_get.assert_not_awaited()
        call = _log_call(mock_log, "error", "mixed namespaces")
        assert call.args[0] == MSG["index_mixed"]
        assert call.kwargs == {"namespaces": ["a", "b"]}

    async def test_rejects_namespace_containing_separator(self):
        tool = SimpleNamespace(name="t", description="d")
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, "bad::ns")])
        mock_get.assert_not_awaited()
        call = _log_call(mock_log, "error", "invalid namespace")
        assert call.kwargs == {"namespace": "bad::ns"}

    async def test_rejects_empty_namespace(self):
        tool = SimpleNamespace(name="t", description="d")
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, "")])
        mock_get.assert_not_awaited()
        call = _log_call(mock_log, "error", "invalid namespace")
        assert call.kwargs == {"namespace": ""}

    async def test_rejects_namespace_longer_than_512(self):
        tool = SimpleNamespace(name="t", description="d")
        namespace = "x" * 513
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, namespace)])
        mock_get.assert_not_awaited()
        call = _log_call(mock_log, "error", "invalid namespace")
        assert call.kwargs == {"namespace": namespace}

    async def test_accepts_namespace_of_exactly_512(self):
        tool = SimpleNamespace(name="t", description="d")
        namespace = "x" * 512
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            await index_tools_to_store([(tool, namespace)])
        mock_get.assert_awaited_once_with(f"chroma:indexed:{namespace}")
        call = _log_call(mock_log, "warning", "provider returned None")
        assert call.kwargs == {"namespace": namespace, "input_count": 1}

    async def test_cache_hit_skips_processing(self):
        tool = SimpleNamespace(name="t", description="d")
        expected_hash = _tools_signature_hash([(tool, "ns")])
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, "ns")])
        mock_get.assert_awaited_once_with("chroma:indexed:ns")
        mock_providers.aget.assert_not_called()
        call = _log_call(mock_log, "info", "cache HIT")
        assert call.kwargs == {"namespace": "ns", "tools_hash": expected_hash, "input_count": 1}

    async def test_cache_hash_joins_multiple_tools(self):
        tool_a = SimpleNamespace(name="ta", description="da")
        tool_b = SimpleNamespace(name="tb", description="db")
        expected_hash = _tools_signature_hash([(tool_a, "ns"), (tool_b, "ns")])
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool_a, "ns"), (tool_b, "ns")])
        mock_get.assert_awaited_once_with("chroma:indexed:ns")
        mock_providers.aget.assert_not_called()
        call = _log_call(mock_log, "info", "cache HIT")
        assert call.kwargs["tools_hash"] == expected_hash
        assert call.kwargs["input_count"] == 2

    async def test_cache_hash_truncates_description_to_200(self):
        tool = SimpleNamespace(name="t", description="d" * 300)
        expected_hash = _tools_signature_hash([(tool, "ns")])
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, "ns")])
        mock_get.assert_awaited_once_with("chroma:indexed:ns")
        call = _log_call(mock_log, "info", "cache HIT")
        assert call.kwargs["tools_hash"] == expected_hash

    async def test_cache_hash_defaults_missing_description(self):
        tool = SimpleNamespace(name="t")
        expected_hash = _tools_signature_hash([(tool, "ns")])
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ) as mock_get,
            patch("app.db.chroma.chroma_tools_store.providers"),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            await index_tools_to_store([(tool, "ns")])
        mock_get.assert_awaited_once_with("chroma:indexed:ns")
        call = _log_call(mock_log, "info", "cache HIT")
        assert call.kwargs["tools_hash"] == expected_hash

    async def test_skips_when_store_unavailable(self):
        tool = SimpleNamespace(name="t", description="d")
        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock),
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            await index_tools_to_store([(tool, "ns")])
        mock_providers.aget.assert_awaited_once_with("chroma_tools_store")
        call = _log_call(mock_log, "warning", "provider returned None")
        assert call.args[0] == MSG["index_provider_none"]
        assert call.kwargs == {"namespace": "ns", "input_count": 1}
        called = _log_call(mock_log, "info", "index_tools_to_store called")
        assert called.kwargs == {"namespace": "ns", "input_count": 1}
        assert _log_call(mock_log, "set", "upsert").kwargs == {
            "vector": {"operation": "upsert", "collection": "langgraph_tools_store"}
        }

    async def test_no_diff_sets_cache(self):
        tool = SimpleNamespace(name="t", description="d")
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {
            "ids": ["ns::t"],
            "metadatas": [{"tool_hash": "samehash", "namespace": "ns"}],
        }
        mock_store = _mock_store(mock_collection)
        expected_hash = _tools_signature_hash([(tool, "ns")])

        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock
            ) as mock_set_cache,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=MagicMock,
                return_value="samehash",
            ) as mock_hash,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        mock_collection.get.assert_awaited_once_with(
            include=["metadatas"], where={"namespace": {"$eq": "ns"}}
        )
        mock_hash.assert_called_once_with(tool)
        mock_store.abatch.assert_not_awaited()
        mock_set_cache.assert_awaited_once_with("chroma:indexed:ns", expected_hash, ttl=86400)
        built = _log_call(mock_log, "info", "built current_tools")
        assert built.kwargs == {
            "namespace": "ns",
            "current_tools_count": 1,
            "input_count": 1,
        }
        fetched = _log_call(mock_log, "info", "fetched existing docs")
        assert fetched.kwargs == {"existing_tools_count": 1, "namespace": "ns"}
        call = _log_call(mock_log, "info", "up-to-date")
        assert call.kwargs == {"namespace": "ns", "current_tools_count": 1}
        set_ns = _log_call(mock_log, "set_ns", "embedded_count")
        assert set_ns.args == ("vector",)
        assert set_ns.kwargs == {"embedded_count": 0}

    async def test_diff_executes_operations(self):
        tool = SimpleNamespace(name="t", description="d")
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_store = _mock_store(mock_collection)
        expected_hash = _tools_signature_hash([(tool, "ns")])
        expected_put_op = PutOp(
            namespace=("ns",),
            key="t",
            value={"description": "d", "tool_hash": "newhash"},
            index=["description"],
        )

        with (
            patch("app.db.chroma.chroma_tools_store.get_cache", new_callable=AsyncMock),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock
            ) as mock_set_cache,
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
            patch(
                "app.db.chroma.chroma_tools_store._compute_tool_hash",
                new_callable=MagicMock,
                return_value="newhash",
            ) as mock_hash,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        mock_hash.assert_called_once_with(tool)
        mock_store.abatch.assert_awaited_once_with([expected_put_op])
        mock_set_cache.assert_awaited_once_with("chroma:indexed:ns", expected_hash, ttl=86400)
        call = _log_call(mock_log, "info", "Updating namespace")
        assert call.kwargs == {
            "namespace": "ns",
            "tools_to_upsert_count": 1,
            "tools_to_delete_count": 0,
        }
        set_ns = _log_call(mock_log, "set_ns", "embedded_count")
        assert set_ns.args == ("vector",)
        assert set_ns.kwargs == {"embedded_count": 1}
        assert _log_call(mock_log, "info", "completed").kwargs == {"namespace": "ns"}


# ---------------------------------------------------------------------------
# delete_tools_by_namespace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteToolsByNamespace:
    async def test_returns_zero_when_store_unavailable(self):
        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock),
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            count = await delete_tools_by_namespace("ns")
        assert count == 0
        mock_providers.aget.assert_awaited_once_with("chroma_tools_store")
        call = _log_call(mock_log, "warning", "not available")
        assert call.args[0] == MSG["delete_unavailable"]
        assert _log_call(mock_log, "set", "delete").kwargs == {
            "vector": {"operation": "delete", "collection": "langgraph_tools_store"}
        }

    async def test_deletes_matching_tools(self):
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": ["ns::a", "ns::b"]}
        mock_store = _mock_store(mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ) as mock_del,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 2
        mock_collection.get.assert_awaited_once_with(where={"namespace": {"$eq": "ns"}}, include=[])
        mock_collection.delete.assert_awaited_once_with(ids=["ns::a", "ns::b"])
        mock_del.assert_awaited_once_with("chroma:indexed:ns")
        call = _log_call(mock_log, "info", "Deleted tools from namespace")
        assert call.kwargs == {"ids_to_delete_count": 2, "namespace": "ns"}
        set_ns = _log_call(mock_log, "set_ns", "result_count")
        assert set_ns.args == ("vector",)
        assert set_ns.kwargs == {"result_count": 2}

    async def test_no_matching_tools(self):
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": []}
        mock_store = _mock_store(mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ) as mock_del,
            patch("app.db.chroma.chroma_tools_store.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 0
        mock_collection.delete.assert_not_awaited()
        mock_del.assert_awaited_once_with("chroma:indexed:ns")
        set_ns = _log_call(mock_log, "set_ns", "result_count")
        assert set_ns.args == ("vector",)
        assert set_ns.kwargs == {"result_count": 0}

    async def test_missing_ids_key_counts_zero(self):
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {}
        mock_store = _mock_store(mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock
            ) as mock_del,
            patch("app.db.chroma.chroma_tools_store.log"),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 0
        mock_collection.delete.assert_not_awaited()
        mock_del.assert_awaited_once_with("chroma:indexed:ns")
