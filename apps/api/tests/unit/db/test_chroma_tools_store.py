"""Tests for app.db.chroma.chroma_tools_store."""

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.store.base import PutOp
import pytest

from app.constants.chroma import (
    TOOLS_INDEX_CACHE_TTL_SECONDS,
    TOOLS_SEED_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    TOOLS_SEED_LOCK_KEY_PREFIX,
    TOOLS_SEED_LOCK_LEASE_SECONDS,
    TOOLS_SEED_LOCK_MAX_HOLD_SECONDS,
    TOOLS_SEED_LOCK_RENEW_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.chroma import chroma_tools_store
from app.db.chroma.chroma_store import ChromaBatchWriteError
from app.db.chroma.chroma_tools_store import (
    _build_put_operations,
    _compute_tool_diff,
    _compute_tool_hash,
    _get_current_tools_with_hashes,
    _get_existing_tools_from_chroma,
    _get_subagent_tools,
    _tools_seed_lock,
    delete_tools_by_namespace,
    index_tools_to_store,
    initialize_chroma_tools_store,
)
from app.models.mcp_config import SubAgentConfig
from app.models.subagent_models import Subagent
from app.utils.redis_lock import DistributedLock
from shared.py.wide_events import log
from tests.helpers import captured_wide_event


@pytest.fixture(autouse=True)
def seed_lock_keys():
    """Run the seed lock's guarded work directly, so these tests stay hermetic.

    Yields the list of lock keys the seeding ran under, so a test can prove
    the work was serialized under the right namespace key.
    """
    seen: list[str] = []

    async def _run(self, work):
        seen.append(self._key)
        await work()

    with patch.object(DistributedLock, "run_idempotent", _run):
        yield seen


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
            result = _compute_tool_hash(tool)
        expected_content = "A tool::def my_tool(): pass"
        assert result == hashlib.sha256(expected_content.encode()).hexdigest()

    async def test_hash_falls_back_to_name_and_description(self):
        tool = SimpleNamespace(name="broken_tool", description="desc")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            side_effect=OSError("no source"),
        ):
            result = _compute_tool_hash(tool)
        expected = hashlib.sha256(b"broken_tool::desc").hexdigest()
        assert result == expected

    async def test_hash_falls_back_on_type_error(self):
        tool = SimpleNamespace(name="t", description="d")
        with patch(
            "app.db.chroma.chroma_tools_store.inspect.getsource",
            side_effect=TypeError,
        ):
            result = _compute_tool_hash(tool)
        assert result == hashlib.sha256(b"t::d").hexdigest()


# ---------------------------------------------------------------------------
# _get_subagent_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentTools:
    async def test_skips_provider_integrations(self):
        cfg = SubAgentConfig(
            has_subagent=True,
            agent_name="gmail_agent",
            tool_space="gmail_space",
            domain="email",
            use_cases="send, read",
            capabilities="full CRUD",
            system_prompt="You are gmail.",
        )
        subagent = Subagent(
            id="gmail",
            name="Gmail",
            provider="gmail",
            managed_by="composio",
            config=cfg,
            short_name="gmail",
        )
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(subagent,),
        ):
            result = _get_subagent_tools()

        # Provider integrations surface as their own tools, never as
        # subagent pointers — nothing is indexed for them.
        assert result == {}

    async def test_indexes_mcp_integrations(self):
        cfg = SubAgentConfig(
            has_subagent=True,
            agent_name="notes_agent",
            tool_space="notes_space",
            domain="notes",
            use_cases="read, write",
            capabilities="full CRUD",
            system_prompt="You are notes.",
        )
        subagent = Subagent(
            id="notes",
            name="Notes",
            provider="notes",
            managed_by="mcp",
            config=cfg,
            short_name="notes",
        )
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(subagent,),
        ):
            result = _get_subagent_tools()

        assert "subagents::subagent:notes" in result
        entry = result["subagents::subagent:notes"]
        assert entry["namespace"] == "subagents"
        assert "Notes" in entry["description"]
        assert entry["source"] == "mcp"
        assert entry["name"] == "Notes"
        assert entry["integration_id"] == "notes"

    async def test_a_provider_integration_does_not_stop_later_mcp_ones_indexing(self):
        cfg = SubAgentConfig(
            has_subagent=True,
            agent_name="agent",
            tool_space="space",
            domain="d",
            use_cases="u",
            capabilities="c",
            system_prompt="p",
        )
        provider = Subagent(
            id="gmail", name="Gmail", provider="gmail", managed_by="composio", config=cfg
        )
        mcp = Subagent(id="notes", name="Notes", provider="notes", managed_by="mcp", config=cfg)
        with patch(
            "app.db.chroma.chroma_tools_store.all_subagents",
            return_value=(provider, mcp),
        ):
            result = _get_subagent_tools()

        assert list(result) == ["subagents::subagent:notes"]

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
            ),
            patch(
                "app.db.chroma.chroma_tools_store._get_subagent_tools",
                new_callable=MagicMock,
                return_value={"subagents::subagent:x": {"hash": "h", "namespace": "subagents"}},
            ),
        ):
            result = _get_current_tools_with_hashes(registry)

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

    async def test_an_entry_without_a_stored_hash_reads_as_an_empty_hash(self):
        """An empty hash never matches a current one, so the tool is re-indexed rather than kept."""
        collection = AsyncMock()
        collection.get.return_value = {"ids": ["ns::tool"], "metadatas": [{"namespace": "ns"}]}
        result = await _get_existing_tools_from_chroma(collection)
        assert result == {"ns::tool": {"hash": "", "namespace": "ns"}}

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

    @pytest.mark.regression
    def test_custom_mcp_subagent_is_never_deleted_on_reseed(self):
        """Regression: seed deleted device MCP subagents, wiping the executor's handoff target on restart."""
        current: dict[str, dict] = {
            "subagents::subagent:todos": {"hash": "h"},  # a builtin the seed manages
        }
        existing = {
            "subagents::subagent:todos": {"hash": "h", "namespace": "subagents"},
            # a device MCP subagent keyed by integration_id (UUID), not "subagent:"
            "subagents::9531fa23-5120-458c-9d7c-8af9127be70e": {
                "hash": "hx",
                "namespace": "subagents",
            },
        }
        _upsert, delete = _compute_tool_diff(current, existing)
        deleted_keys = {key for key, _ns in delete}
        assert "subagents::9531fa23-5120-458c-9d7c-8af9127be70e" not in deleted_keys

    def test_builtin_subagent_absent_from_current_is_still_deleted(self):
        current: dict[str, dict] = {}
        existing = {
            "subagents::subagent:retired": {"hash": "h", "namespace": "subagents"},
        }
        _upsert, delete = _compute_tool_diff(current, existing)
        assert ("subagents::subagent:retired", "subagents") in delete

    def test_reseed_prunes_stale_builtin_while_keeping_the_device_subagent(self):
        # The device subagent is FIRST and the stale builtin SECOND on purpose:
        # skipping the device one must `continue` (keep scanning), not `break`
        # (which would leave the later stale builtin un-pruned).
        current: dict[str, dict] = {}
        existing = {
            "subagents::aedc0ba0-b3b6-4783-8035-d25e94c291db": {
                "hash": "hx",
                "namespace": "subagents",
            },
            "subagents::subagent:retired": {"hash": "h", "namespace": "subagents"},
        }
        _upsert, delete = _compute_tool_diff(current, existing)
        deleted_keys = {key for key, _ns in delete}
        assert deleted_keys == {"subagents::subagent:retired"}


class TestIsDynamicSubagent:
    """A dynamic MCP subagent lives in the subagents namespace keyed by integration_id, not subagent:<id>."""

    def test_device_subagent_keyed_by_integration_id_is_dynamic(self):
        assert (
            chroma_tools_store._is_dynamic_subagent(
                "subagents::aedc0ba0-b3b6-4783-8035-d25e94c291db", "subagents"
            )
            is True
        )

    def test_builtin_subagent_is_not_dynamic(self):
        assert (
            chroma_tools_store._is_dynamic_subagent("subagents::subagent:todos", "subagents")
            is False
        )

    def test_only_the_key_after_the_first_separator_is_examined(self):
        # split(maxsplit=1): a "subagent:" builtin whose own id contains "::" is
        # still a builtin. A higher maxsplit would look at the tail ("tail") and
        # wrongly call it dynamic.
        assert (
            chroma_tools_store._is_dynamic_subagent("subagents::subagent:weird::tail", "subagents")
            is False
        )

    def test_non_subagents_namespace_is_never_dynamic(self):
        assert chroma_tools_store._is_dynamic_subagent("gmail::search_threads", "gmail") is False

    def test_builtin_prefix_must_match_from_the_start(self):
        # A key that merely contains "subagent:" later is still dynamic.
        assert (
            chroma_tools_store._is_dynamic_subagent("subagents::mcp-subagent:foo", "subagents")
            is True
        )


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
        assert ops[0].value == {"description": "sub desc", "tool_hash": "h"}
        assert ops[0].index == ["description"]

    def test_upsert_subagent_tool_persists_pointer_fields(self):
        """Source/name/integration_id must reach the PutOp value: retrieval tells static ("mcp") from custom ("custom") pointers by them."""
        to_upsert = [
            (
                "subagents::subagent:notes",
                {
                    "hash": "h",
                    "namespace": "subagents",
                    "description": "sub desc",
                    "source": "mcp",
                    "name": "Notes",
                    "integration_id": "notes",
                },
            )
        ]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].value["source"] == "mcp"
        assert ops[0].value["name"] == "Notes"
        assert ops[0].value["integration_id"] == "notes"

    def test_upsert_regular_tool_carries_no_pointer_fields(self):
        tool = SimpleNamespace(description="desc")
        to_upsert = [("ns::my_tool", {"hash": "h", "namespace": "ns", "tool": tool})]
        ops = _build_put_operations(to_upsert, [])
        assert "source" not in ops[0].value

    def test_delete_operation_has_none_value(self):
        to_delete = [("ns::old_tool", "ns")]
        ops = _build_put_operations([], to_delete)
        assert ops == [PutOp(namespace=("ns",), key="old_tool", value=None)]

    def test_only_the_first_separator_splits_the_composite_key(self):
        to_delete = [("ns::tool::v2", "ns")]
        ops = _build_put_operations([], to_delete)
        assert ops[0].key == "tool::v2"

    def test_composite_key_without_separator(self):
        to_upsert = [("bare_key", {"hash": "h", "namespace": "x", "description": "d"})]
        ops = _build_put_operations(to_upsert, [])
        assert ops[0].key == "bare_key"


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

    async def test_cache_hit_with_an_empty_store_reindexes_anyway(self):
        """Redis says indexed, Chroma holds none; trusting the hash alone left the namespace empty and discovery silently returned nothing."""
        tool = SimpleNamespace(name="t", description="d")
        tools_signature = "t:d"
        expected_hash = hashlib.sha256(tools_signature.encode()).hexdigest()[:16]

        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ),
            patch("app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock),
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch(
                "app.db.chroma.index_warmup.execute_batch_operations",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        # Reached the write path instead of returning at the guard.
        mock_execute.assert_awaited_once()

    async def test_failed_batch_write_does_not_cache_the_namespace_hash(self):
        """Regression: a partial write must not cache the namespace hash as a success."""
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
                "app.db.chroma.index_warmup.execute_batch_operations",
                new_callable=AsyncMock,
                side_effect=ChromaBatchWriteError("1 of 1 ChromaDB writes failed"),
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        mock_set_cache.assert_not_awaited()

    async def test_successful_batch_write_caches_the_namespace_hash(self):
        """The other half of the contract: a clean write still caches."""
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
                "app.db.chroma.index_warmup.execute_batch_operations",
                new_callable=AsyncMock,
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        mock_set_cache.assert_awaited_once()

    async def test_warmup_is_labelled_with_the_namespace_being_indexed(self):
        """A degraded-catalog log has to name which namespace lost its tools."""
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
            patch("app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock),
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.index_warmup.log") as mock_log,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            await index_tools_to_store([(tool, "ns")])

        assert mock_log.info.call_args.kwargs["label"] == "index_tools_to_store[ns]"

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
                new_callable=MagicMock,
                return_value="samehash",
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            # Existing store already holds the exact current tool (same composite
            # key AND hash), so the diff is empty — no write, but the marker is
            # stamped with the tools signature + TTL.
            mock_collection.get.return_value = {
                "ids": ["ns::t"],
                "metadatas": [{"tool_hash": "samehash", "namespace": "ns"}],
            }
            async with captured_wide_event() as event:
                await index_tools_to_store([(tool, "ns")])
            assert event["vector"]["embedded_count"] == 0
            expected_hash = hashlib.sha256(b"t:d").hexdigest()[:16]
            mock_set_cache.assert_awaited_once_with(
                "chroma:indexed:ns", expected_hash, ttl=TOOLS_INDEX_CACHE_TTL_SECONDS
            )

    async def test_diff_executes_operations(self, seed_lock_keys):
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
                new_callable=MagicMock,
                return_value="newhash",
            ),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            async with captured_wide_event() as event:
                await index_tools_to_store([(tool, "ns")])
            mock_store.abatch.assert_awaited()
            assert event["vector"]["embedded_count"] == 1
            assert seed_lock_keys == ["lock:chroma:tools-seed:ns"]
            expected_hash = hashlib.sha256(b"t:d").hexdigest()[:16]
            mock_set_cache.assert_awaited_once_with(
                "chroma:indexed:ns", expected_hash, ttl=TOOLS_INDEX_CACHE_TTL_SECONDS
            )


# index_tools_to_store — the verified cache guard. The Redis hash only proves
# a past process believed it indexed this namespace; trusting it alone made a
# wiped ChromaDB permanent, so these assert on the wide event's `warnings[]`.

_NAMESPACE = "gmail"
_TOOL = SimpleNamespace(name="t", description="d")
_TOOLS_HASH = hashlib.sha256(b"t:d").hexdigest()[:16]


def _store_holding(*doc_hashes: str) -> AsyncMock:
    """Return a Chroma store whose namespace holds one indexed doc per given tool hash."""
    collection = AsyncMock()
    collection.get.return_value = {
        "ids": [f"{_NAMESPACE}::t{i}" for i in range(len(doc_hashes))],
        "metadatas": [{"tool_hash": h, "namespace": _NAMESPACE} for h in doc_hashes],
    }
    store = AsyncMock()
    store._get_collection = AsyncMock(return_value=collection)
    return store


@contextmanager
def _indexing(store: AsyncMock, cached_hash: str | None) -> Iterator[SimpleNamespace]:
    """Run index_tools_to_store against store with Redis reporting cached_hash."""
    with (
        patch(
            "app.db.chroma.chroma_tools_store.get_cache",
            new_callable=AsyncMock,
            return_value=cached_hash,
        ) as get_cache,
        patch("app.db.chroma.chroma_tools_store.set_cache", new_callable=AsyncMock) as set_cache,
        patch("app.db.chroma.chroma_tools_store.providers") as providers,
        patch(
            "app.db.chroma.index_warmup.execute_batch_operations",
            new_callable=AsyncMock,
        ) as execute,
    ):
        providers.aget = AsyncMock(return_value=store)
        yield SimpleNamespace(get_cache=get_cache, set_cache=set_cache, execute=execute)


def _wiped_store_warnings() -> list[dict]:
    return [w for w in log.get().get("warnings", []) if "ChromaDB holds 0 docs" in w["msg"]]


@pytest.mark.asyncio
class TestVerifiedCacheGuard:
    @pytest.fixture(autouse=True)
    def _fresh_wide_event(self) -> None:
        # Outside a boundary every wide-event write lands in a throwaway state,
        # so `warnings[]` would read empty no matter what the code logged.
        log.reset()

    async def test_the_cache_is_read_once_under_the_namespace_key(self):
        # The key IS the namespace isolation: one shared key would let a
        # freshly-indexed namespace suppress the reindex of a different one.
        with _indexing(_store_holding("h"), _TOOLS_HASH) as mocks:
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        mocks.get_cache.assert_awaited_once_with(f"chroma:indexed:{_NAMESPACE}")

    async def test_a_verified_hit_writes_nothing_at_all(self):
        # The store holds a doc whose hash differs from the incoming tool, so a
        # run that reaches the diff WOULD write. Reaching it is the failure.
        with _indexing(_store_holding("stale-hash"), _TOOLS_HASH) as mocks:
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        mocks.execute.assert_not_awaited()
        mocks.set_cache.assert_not_awaited()

    async def test_a_wiped_store_is_announced_with_the_namespace_it_lost(self):
        # This warning is the ONLY trace the wipe ever happened — without the
        # namespace and the count, an operator cannot tell which integration
        # went dark or how much it lost.
        with _indexing(_store_holding(), _TOOLS_HASH):
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        assert len(_wiped_store_warnings()) == 1
        warning = _wiped_store_warnings()[0]
        assert warning["msg"] == (
            f"{LogTag.CHROMA} index_tools_to_store: Redis says namespace is indexed "
            "but ChromaDB holds 0 docs — store was wiped behind the cache; reindexing"
        )
        assert warning["namespace"] == _NAMESPACE
        assert warning["input_count"] == 1

    async def test_a_first_time_index_seeds_then_writes_the_namespace_marker(self):
        # Cache miss + empty store is simply a namespace nobody has indexed yet:
        # embed the one tool and stamp the marker so the next run can short-circuit.
        # Crying wipe here would train operators to ignore the one real alarm.
        with _indexing(_store_holding(), None) as mocks:
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        mocks.execute.assert_awaited_once()
        assert _wiped_store_warnings() == []
        assert log.get()["vector"]["embedded_count"] == 1
        mocks.set_cache.assert_awaited_once_with(
            f"chroma:indexed:{_NAMESPACE}", _TOOLS_HASH, ttl=TOOLS_INDEX_CACHE_TTL_SECONDS
        )

    async def test_existing_docs_are_read_scoped_to_the_namespace(self):
        # Both the fast-path read and the in-lease re-read must filter to this
        # namespace — reading all namespaces would diff against other providers'
        # tools and delete them.
        collection = AsyncMock()
        store = AsyncMock()
        store._get_collection = AsyncMock(return_value=collection)
        with (
            _indexing(store, None),
            patch(
                "app.db.chroma.chroma_tools_store._get_existing_tools_from_chroma",
                new=AsyncMock(return_value={}),
            ) as get_existing,
        ):
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        assert get_existing.await_count >= 2
        for call in get_existing.await_args_list:
            assert call.args == (collection, {_NAMESPACE})

    async def test_a_delete_only_diff_still_writes(self):
        # The current tool matches an existing doc (no upsert), but a stale doc
        # must be deleted: the "no changes" short-circuit must not swallow a
        # delete-only diff.
        collection = AsyncMock()
        store = AsyncMock()
        store._get_collection = AsyncMock(return_value=collection)
        existing = {
            f"{_NAMESPACE}::t": {"hash": _compute_tool_hash(_TOOL), "namespace": _NAMESPACE},
            f"{_NAMESPACE}::stale": {"hash": "gone", "namespace": _NAMESPACE},
        }
        with (
            _indexing(store, None) as mocks,
            patch(
                "app.db.chroma.chroma_tools_store._get_existing_tools_from_chroma",
                new=AsyncMock(return_value=existing),
            ),
        ):
            await index_tools_to_store([(_TOOL, _NAMESPACE)])

        mocks.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_tools_by_namespace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteToolsByNamespace:
    async def test_returns_zero_when_store_unavailable(self):
        with patch("app.db.chroma.chroma_tools_store.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)
            with patch("app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock):
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
        # Only this namespace's ids are fetched — the filter is what scopes the delete.
        mock_collection.get.assert_awaited_once_with(where={"namespace": {"$eq": "ns"}}, include=[])
        mock_collection.delete.assert_awaited_once_with(ids=["ns::a", "ns::b"])
        mock_del.assert_awaited_once_with("chroma:indexed:ns")

    async def test_no_matching_tools(self):
        mock_store = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.get.return_value = {"ids": []}
        mock_store._get_collection = AsyncMock(return_value=mock_collection)

        with (
            patch("app.db.chroma.chroma_tools_store.providers") as mock_providers,
            patch("app.db.chroma.chroma_tools_store.delete_cache", new_callable=AsyncMock),
        ):
            mock_providers.aget = AsyncMock(return_value=mock_store)
            count = await delete_tools_by_namespace("ns")

        assert count == 0
        mock_collection.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# _tools_seed_lock
# ---------------------------------------------------------------------------


class TestToolsSeedLock:
    def test_builds_the_lock_with_the_namespace_key_and_tuned_timing(self):
        lock = _tools_seed_lock("myns")
        assert lock._key == f"{TOOLS_SEED_LOCK_KEY_PREFIX}myns"
        assert lock._lease_seconds == TOOLS_SEED_LOCK_LEASE_SECONDS
        assert lock._acquire_timeout_seconds == TOOLS_SEED_LOCK_ACQUIRE_TIMEOUT_SECONDS
        assert lock._renew_seconds == TOOLS_SEED_LOCK_RENEW_SECONDS
        assert lock._max_hold_seconds == TOOLS_SEED_LOCK_MAX_HOLD_SECONDS


# ---------------------------------------------------------------------------
# initialize_chroma_tools_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInitializeChromaToolsStore:
    @staticmethod
    @contextmanager
    def _patched(*, embeddings, current, existing):
        collection = AsyncMock()
        mock_store = AsyncMock()
        mock_store._get_collection = AsyncMock(return_value=collection)
        registry = MagicMock()
        with (
            patch(
                "app.db.chroma.chroma_tools_store.get_tool_registry",
                new=AsyncMock(return_value=registry),
            ),
            patch("app.db.chroma.chroma_tools_store.ChromaClient.get_client", new=AsyncMock()),
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new=AsyncMock(return_value=embeddings),
            ),
            patch("app.db.chroma.chroma_tools_store.ChromaStore", return_value=mock_store),
            patch(
                "app.db.chroma.chroma_tools_store._get_current_tools_with_hashes",
                return_value=current,
            ) as current_mock,
            patch(
                "app.db.chroma.chroma_tools_store._get_existing_tools_from_chroma",
                new=AsyncMock(return_value=existing),
            ) as existing_mock,
            patch(
                "app.db.chroma.index_warmup.execute_batch_operations", new=AsyncMock()
            ) as execute,
        ):
            yield SimpleNamespace(
                store=mock_store,
                collection=collection,
                registry=registry,
                current_mock=current_mock,
                existing_mock=existing_mock,
                execute=execute,
            )

    @staticmethod
    async def _run():
        # The factory is @lazy_provider-wrapped; loader_func is the real body.
        loader = initialize_chroma_tools_store()
        return await loader.loader_func()

    @staticmethod
    def _current(hash_: str) -> dict:
        return {
            "general::t": {
                "hash": hash_,
                "namespace": "general",
                "tool": SimpleNamespace(name="t", description="d"),
            }
        }

    async def test_raises_when_embeddings_unavailable(self):
        with (
            patch("app.db.chroma.chroma_tools_store.get_tool_registry", new=AsyncMock()),
            patch("app.db.chroma.chroma_tools_store.ChromaClient.get_client", new=AsyncMock()),
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new=AsyncMock(return_value=None),
            ),
        ):
            with pytest.raises(RuntimeError) as exc:
                await self._run()
        assert str(exc.value) == "Embeddings not available"

    async def test_seeds_and_returns_store_when_diff_exists(self, seed_lock_keys):
        with self._patched(embeddings=object(), current=self._current("h1"), existing={}) as p:
            async with captured_wide_event() as event:
                result = await self._run()
        assert result is p.store
        # Diffs the current tools (from the registry) against what the managed
        # namespaces already hold in the real collection, then upserts into the store.
        p.current_mock.assert_called_once_with(p.registry)
        p.existing_mock.assert_awaited_once_with(p.collection, {"general"})
        p.execute.assert_awaited_once()
        # Executed against the real store with the built put-ops (one upsert),
        # labelled so a degraded-catalog log names the boot seed it came from.
        assert p.execute.await_args.kwargs["label"] == "tools_store_seed"
        store_arg, put_ops = p.execute.await_args.args
        assert store_arg is p.store
        assert len(put_ops) == 1
        assert seed_lock_keys == ["lock:chroma:tools-seed:builtin"]
        assert event["vector"] == {
            "operation": "upsert",
            "collection": "langgraph_tools_store",
            "embedded_count": 1,
        }

    async def test_no_diff_does_not_touch_the_store(self):
        existing = {"general::t": {"hash": "h1", "namespace": "general"}}
        with self._patched(
            embeddings=object(), current=self._current("h1"), existing=existing
        ) as p:
            async with captured_wide_event() as event:
                result = await self._run()
        assert result is p.store
        p.execute.assert_not_awaited()
        assert event["vector"]["embedded_count"] == 0
