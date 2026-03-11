"""Integration tests for ChromaStore using an ephemeral in-memory ChromaDB client.

These tests exercise the ChromaStore wrapper (app.db.chroma.chroma_store) and
the tool-indexing helpers (app.db.chroma.chroma_tools_store) without hitting a
real ChromaDB server.  chromadb.EphemeralClient() provides full in-process
coverage at zero infrastructure cost.

Key production modules under test
----------------------------------
- app.db.chroma.chroma_store.ChromaStore
- app.db.chroma.chroma_tools_store._compute_tool_diff
- app.db.chroma.chroma_tools_store._build_put_operations
- app.db.chroma.chroma_tools_store._get_existing_tools_from_chroma
- app.db.chroma.chroma_tools_store.delete_tools_by_namespace
"""

import pickle
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import chromadb
import pytest
from langgraph.store.base import GetOp, PutOp, SearchOp

from app.db.chroma.chroma_store import ChromaStore
from app.db.chroma.chroma_tools_store import (
    _build_put_operations,
    _compute_tool_diff,
    _get_existing_tools_from_chroma,
    delete_tools_by_namespace,
)


# ---------------------------------------------------------------------------
# Async wrapper for synchronous EphemeralClient
# chromadb.AsyncEphemeralClient does not exist in chromadb 1.x – this wrapper
# exposes the same async interface that ChromaStore expects by delegating to the
# synchronous EphemeralClient under the hood.
# ---------------------------------------------------------------------------


class _AsyncCollectionWrapper:
    """Thin async wrapper around a synchronous chromadb Collection."""

    def __init__(self, sync_col):
        self._sync = sync_col
        self.name = sync_col.name

    async def upsert(self, *args, **kwargs):
        return self._sync.upsert(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return self._sync.get(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        return self._sync.delete(*args, **kwargs)

    async def query(self, *args, **kwargs):
        return self._sync.query(*args, **kwargs)

    async def count(self, *args, **kwargs):
        return self._sync.count(*args, **kwargs)


class _AsyncEphemeralWrapper:
    """Async interface backed by a synchronous chromadb.EphemeralClient.

    ChromaStore requires an AsyncClientAPI; this wrapper satisfies that contract
    without needing a real async HTTP server.
    """

    def __init__(self):
        self._sync = chromadb.EphemeralClient()

    async def list_collections(self):
        return self._sync.list_collections()

    async def create_collection(self, name, metadata=None, **kwargs):
        col = self._sync.create_collection(name, metadata=metadata, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def get_collection(self, name, **kwargs):
        col = self._sync.get_collection(name, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def get_or_create_collection(self, name, metadata=None, **kwargs):
        col = self._sync.get_or_create_collection(name, metadata=metadata, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def delete_collection(self, name):
        return self._sync.delete_collection(name)

    async def reset(self):
        return self._sync.reset()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ephemeral_client():
    """Return a fresh async-wrapped ephemeral ChromaDB client per test."""
    client = _AsyncEphemeralWrapper()
    yield client
    # Clean up – list and delete every collection created during the test
    collections = client._sync.list_collections()
    for col in collections:
        client._sync.delete_collection(col.name)


@pytest.fixture
async def chroma_store(ephemeral_client):
    """Return a ChromaStore backed by the ephemeral client, no embeddings."""
    store = ChromaStore(
        client=ephemeral_client,
        collection_name="test_store",
        index=None,  # No embeddings needed for basic CRUD tests
    )
    return store


@pytest.fixture
async def populated_store(chroma_store):
    """Return a ChromaStore pre-populated with three items."""
    ops = [
        PutOp(
            namespace=("tools", "general"),
            key="web_search",
            value={"description": "Search the web", "tool_hash": "hash_ws"},
        ),
        PutOp(
            namespace=("tools", "general"),
            key="calculator",
            value={"description": "Arithmetic calculations", "tool_hash": "hash_calc"},
        ),
        PutOp(
            namespace=("tools", "gmail"),
            key="send_email",
            value={"description": "Send an email via Gmail", "tool_hash": "hash_se"},
        ),
    ]
    await chroma_store.abatch(ops)
    return chroma_store


# ---------------------------------------------------------------------------
# ChromaStore – basic CRUD via abatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChromaStoreCRUD:
    """Test ChromaStore put / get / delete via abatch."""

    async def test_put_and_get_item(self, chroma_store):
        """PutOp should store a value that can be retrieved with GetOp."""
        await chroma_store.abatch(
            [
                PutOp(
                    namespace=("ns",),
                    key="key1",
                    value={"description": "hello", "tool_hash": "abc"},
                )
            ]
        )

        results = await chroma_store.abatch(
            [GetOp(namespace=("ns",), key="key1")]
        )

        assert len(results) == 1
        item = results[0]
        assert item is not None
        assert item.key == "key1"
        assert item.namespace == ("ns",)
        assert item.value["description"] == "hello"

    async def test_get_missing_key_returns_none(self, chroma_store):
        """GetOp for a key that was never stored should return None."""
        results = await chroma_store.abatch(
            [GetOp(namespace=("ns",), key="does_not_exist")]
        )
        assert results[0] is None

    async def test_put_none_deletes_item(self, populated_store):
        """PutOp with value=None should delete the item."""
        # Confirm item exists
        results = await populated_store.abatch(
            [GetOp(namespace=("tools", "general"), key="calculator")]
        )
        assert results[0] is not None

        # Delete via PutOp(value=None)
        await populated_store.abatch(
            [
                PutOp(
                    namespace=("tools", "general"),
                    key="calculator",
                    value=None,
                )
            ]
        )

        results = await populated_store.abatch(
            [GetOp(namespace=("tools", "general"), key="calculator")]
        )
        assert results[0] is None

    async def test_upsert_overwrites_existing(self, chroma_store):
        """Second PutOp for the same key should overwrite the value."""
        ns = ("ns",)
        key = "tool_a"
        await chroma_store.abatch(
            [PutOp(namespace=ns, key=key, value={"description": "v1", "tool_hash": "h1"})]
        )
        await chroma_store.abatch(
            [PutOp(namespace=ns, key=key, value={"description": "v2", "tool_hash": "h2"})]
        )

        results = await chroma_store.abatch([GetOp(namespace=ns, key=key)])
        assert results[0].value["description"] == "v2"

    async def test_multiple_namespaces_are_isolated(self, populated_store):
        """Items in different namespaces should not interfere with each other."""
        result_general = await populated_store.abatch(
            [GetOp(namespace=("tools", "general"), key="web_search")]
        )
        result_gmail = await populated_store.abatch(
            [GetOp(namespace=("tools", "gmail"), key="web_search")]
        )

        assert result_general[0] is not None
        assert result_gmail[0] is None  # not in gmail namespace

    async def test_batch_mixed_ops(self, chroma_store):
        """abatch should handle multiple operations in a single call."""
        ops = [
            PutOp(namespace=("ns",), key="a", value={"x": 1, "tool_hash": "h_a"}),
            PutOp(namespace=("ns",), key="b", value={"x": 2, "tool_hash": "h_b"}),
        ]
        await chroma_store.abatch(ops)

        get_results = await chroma_store.abatch(
            [
                GetOp(namespace=("ns",), key="a"),
                GetOp(namespace=("ns",), key="b"),
            ]
        )
        assert get_results[0].value["x"] == 1
        assert get_results[1].value["x"] == 2


# ---------------------------------------------------------------------------
# ChromaStore – namespace helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChromaStoreNamespaceHelpers:
    """Test internal namespace <-> ID conversion helpers."""

    async def test_namespace_to_id_roundtrip(self, chroma_store):
        """_namespace_to_id and _id_to_namespace_key should be inverses."""
        namespace = ("tools", "gmail")
        key = "send_email"
        doc_id = chroma_store._namespace_to_id(namespace, key)
        back_ns, back_key = chroma_store._id_to_namespace_key(doc_id)
        assert back_ns == namespace
        assert back_key == key

    async def test_empty_namespace_uses_default(self, chroma_store):
        """Empty namespace tuple should be stored/retrieved without error."""
        doc_id = chroma_store._namespace_to_id((), "orphan_key")
        ns, key = chroma_store._id_to_namespace_key(doc_id)
        assert key == "orphan_key"

    async def test_matches_namespace_prefix_exact(self, chroma_store):
        """Exact namespace should match its own prefix."""
        assert chroma_store._matches_namespace_prefix(("a", "b"), ("a", "b"))

    async def test_matches_namespace_prefix_partial(self, chroma_store):
        """A longer namespace should match a shorter prefix."""
        assert chroma_store._matches_namespace_prefix(("a", "b", "c"), ("a", "b"))

    async def test_does_not_match_wrong_prefix(self, chroma_store):
        """A namespace should NOT match a prefix it does not start with."""
        assert not chroma_store._matches_namespace_prefix(("x", "y"), ("a", "b"))


# ---------------------------------------------------------------------------
# ChromaStore – search (no embeddings)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChromaStoreSearch:
    """Test SearchOp without vector embeddings (filter-only path)."""

    async def test_search_returns_items_in_namespace(self, populated_store):
        """SearchOp with namespace_prefix should return items in that namespace."""
        results = await populated_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("tools", "general"),
                    query=None,
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert isinstance(items, list)
        keys = {item.key for item in items}
        assert "web_search" in keys
        assert "calculator" in keys
        # gmail namespace item should NOT appear
        assert "send_email" not in keys

    async def test_search_empty_namespace_returns_empty(self, chroma_store):
        """SearchOp on an empty collection should return an empty list."""
        results = await chroma_store.abatch(
            [SearchOp(namespace_prefix=("empty",), query=None, limit=10, offset=0)]
        )
        assert results[0] == []

    async def test_search_limit_is_respected(self, populated_store):
        """SearchOp limit should cap the number of returned items."""
        results = await populated_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("tools", "general"),
                    query=None,
                    limit=1,
                    offset=0,
                )
            ]
        )
        assert len(results[0]) <= 1


# ---------------------------------------------------------------------------
# Tool diff helpers (pure logic, no ChromaDB needed)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestComputeToolDiff:
    """Test _compute_tool_diff for upsert / delete detection."""

    def _make_mock_tool(self, name: str, description: str = "desc"):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        return tool

    async def test_new_tool_is_marked_for_upsert(self):
        """A tool not in existing_tools should appear in tools_to_upsert."""
        mock_tool = self._make_mock_tool("new_tool")
        current = {
            "general::new_tool": {
                "hash": "newhash",
                "namespace": "general",
                "tool": mock_tool,
            }
        }
        existing: dict = {}

        to_upsert, to_delete = _compute_tool_diff(current, existing)

        assert len(to_upsert) == 1
        assert to_upsert[0][0] == "general::new_tool"
        assert len(to_delete) == 0

    async def test_unchanged_tool_not_in_upsert(self):
        """A tool whose hash matches should NOT appear in tools_to_upsert."""
        mock_tool = self._make_mock_tool("stable_tool")
        current = {
            "general::stable_tool": {
                "hash": "stablehash",
                "namespace": "general",
                "tool": mock_tool,
            }
        }
        existing = {
            "general::stable_tool": {"hash": "stablehash", "namespace": "general"}
        }

        to_upsert, to_delete = _compute_tool_diff(current, existing)

        assert len(to_upsert) == 0
        assert len(to_delete) == 0

    async def test_modified_tool_is_marked_for_upsert(self):
        """A tool whose hash changed should appear in tools_to_upsert."""
        mock_tool = self._make_mock_tool("changed_tool")
        current = {
            "general::changed_tool": {
                "hash": "newhash",
                "namespace": "general",
                "tool": mock_tool,
            }
        }
        existing = {
            "general::changed_tool": {"hash": "oldhash", "namespace": "general"}
        }

        to_upsert, to_delete = _compute_tool_diff(current, existing)

        assert len(to_upsert) == 1

    async def test_deleted_tool_is_marked_for_delete(self):
        """A tool in existing but absent from current should appear in tools_to_delete."""
        current: dict = {}
        existing = {
            "general::old_tool": {"hash": "oldhash", "namespace": "general"}
        }

        to_upsert, to_delete = _compute_tool_diff(current, existing)

        assert len(to_delete) == 1
        assert to_delete[0][0] == "general::old_tool"
        assert to_delete[0][1] == "general"

    async def test_mixed_changes(self):
        """Combination of new, unchanged, modified, and deleted tools."""
        mock_new = self._make_mock_tool("new_tool")
        mock_stable = self._make_mock_tool("stable_tool")
        mock_changed = self._make_mock_tool("changed_tool")

        current = {
            "ns::new_tool": {"hash": "h_new", "namespace": "ns", "tool": mock_new},
            "ns::stable_tool": {"hash": "h_stable", "namespace": "ns", "tool": mock_stable},
            "ns::changed_tool": {"hash": "h_changed_new", "namespace": "ns", "tool": mock_changed},
        }
        existing = {
            "ns::stable_tool": {"hash": "h_stable", "namespace": "ns"},
            "ns::changed_tool": {"hash": "h_changed_old", "namespace": "ns"},
            "ns::deleted_tool": {"hash": "h_deleted", "namespace": "ns"},
        }

        to_upsert, to_delete = _compute_tool_diff(current, existing)

        upsert_keys = {k for k, _ in to_upsert}
        delete_keys = {k for k, _ in to_delete}

        assert "ns::new_tool" in upsert_keys
        assert "ns::changed_tool" in upsert_keys
        assert "ns::stable_tool" not in upsert_keys
        assert "ns::deleted_tool" in delete_keys


# ---------------------------------------------------------------------------
# _build_put_operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildPutOperations:
    """Test _build_put_operations produces well-formed PutOp lists."""

    def _make_mock_tool(self, name: str, description: str = "A tool"):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        return tool

    async def test_upsert_op_has_correct_namespace_and_key(self):
        """Upsert PutOp should use the namespace from tool_data and key from composite."""
        mock_tool = self._make_mock_tool("send_email", "Send an email")
        tools_to_upsert = [
            (
                "gmail::send_email",
                {"hash": "h1", "namespace": "gmail", "tool": mock_tool},
            )
        ]
        put_ops = _build_put_operations(tools_to_upsert, [])

        assert len(put_ops) == 1
        op = put_ops[0]
        assert isinstance(op, PutOp)
        assert op.namespace == ("gmail",)
        assert op.key == "send_email"
        assert op.value is not None
        assert op.value["description"] == "Send an email"

    async def test_delete_op_has_value_none(self):
        """Delete PutOp should have value=None."""
        tools_to_delete = [("general::old_tool", "general")]
        put_ops = _build_put_operations([], tools_to_delete)

        assert len(put_ops) == 1
        op = put_ops[0]
        assert op.value is None
        assert op.key == "old_tool"
        assert op.namespace == ("general",)

    async def test_subagent_tool_uses_description_field(self):
        """Subagent tools (no 'tool' key) should use 'description' field directly."""
        tools_to_upsert = [
            (
                "subagents::subagent:gmail",
                {
                    "hash": "h_sub",
                    "namespace": "subagents",
                    "description": "Gmail subagent description",
                },
            )
        ]
        put_ops = _build_put_operations(tools_to_upsert, [])

        assert len(put_ops) == 1
        op = put_ops[0]
        assert op.value["description"] == "Gmail subagent description"

    async def test_empty_inputs_return_empty_list(self):
        """No upserts and no deletes should return an empty list."""
        put_ops = _build_put_operations([], [])
        assert put_ops == []

    async def test_mixed_upserts_and_deletes(self):
        """Both upserts and deletes should appear in the output list."""
        mock_tool = self._make_mock_tool("web_search", "Search the web")
        tools_to_upsert = [
            ("general::web_search", {"hash": "h_ws", "namespace": "general", "tool": mock_tool})
        ]
        tools_to_delete = [("general::old_tool", "general")]

        put_ops = _build_put_operations(tools_to_upsert, tools_to_delete)

        assert len(put_ops) == 2
        values = [op.value for op in put_ops]
        assert None in values  # delete op
        assert any(v is not None and "description" in v for v in values)  # upsert op


# ---------------------------------------------------------------------------
# _get_existing_tools_from_chroma
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetExistingToolsFromChroma:
    """Test _get_existing_tools_from_chroma with a live ephemeral collection."""

    @pytest.fixture
    async def collection_with_tools(self, ephemeral_client):
        """Create a collection and insert two tools manually."""
        col = await ephemeral_client.create_collection(
            "test_tools", metadata={"hnsw:space": "cosine"}
        )
        await col.upsert(
            ids=["general::web_search"],
            documents=["dummy"],
            metadatas=[{"namespace": "general", "tool_hash": "hash_ws"}],
        )
        await col.upsert(
            ids=["gmail::send_email"],
            documents=["dummy"],
            metadatas=[{"namespace": "gmail", "tool_hash": "hash_se"}],
        )
        return col

    async def test_returns_all_tools_when_no_namespace_filter(
        self, collection_with_tools
    ):
        """Passing namespaces=None should return all tools."""
        result = await _get_existing_tools_from_chroma(
            collection_with_tools, namespaces=None
        )
        assert "general::web_search" in result
        assert "gmail::send_email" in result

    async def test_namespace_filter_returns_only_matching(
        self, collection_with_tools
    ):
        """Filtering by namespace='general' should only return general tools."""
        result = await _get_existing_tools_from_chroma(
            collection_with_tools, namespaces={"general"}
        )
        assert "general::web_search" in result
        assert "gmail::send_email" not in result

    async def test_empty_namespace_set_returns_empty(self, collection_with_tools):
        """An empty namespaces set should return an empty dict immediately."""
        result = await _get_existing_tools_from_chroma(
            collection_with_tools, namespaces=set()
        )
        assert result == {}

    async def test_tool_hash_is_preserved(self, collection_with_tools):
        """tool_hash in ChromaDB metadata should be included in return value."""
        result = await _get_existing_tools_from_chroma(
            collection_with_tools, namespaces={"general"}
        )
        assert result["general::web_search"]["hash"] == "hash_ws"


# ---------------------------------------------------------------------------
# delete_tools_by_namespace (mocked providers)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteToolsByNamespace:
    """Test delete_tools_by_namespace with mocked lazy provider and Redis cache."""

    async def test_deletes_tools_in_namespace(self, ephemeral_client):
        """delete_tools_by_namespace should remove items and return count."""
        # Build a real store but wire it into the mocked provider
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="tools_col",
        )
        # Seed with two tools in 'myns' and one in another namespace
        collection = await store._get_collection()
        await collection.upsert(
            ids=["myns::tool_a", "myns::tool_b", "other::tool_c"],
            documents=["d", "d", "d"],
            metadatas=[
                {"namespace": "myns", "tool_hash": "h1"},
                {"namespace": "myns", "tool_hash": "h2"},
                {"namespace": "other", "tool_hash": "h3"},
            ],
        )

        with (
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new_callable=AsyncMock,
                return_value=store,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache",
                new_callable=AsyncMock,
            ) as mock_del_cache,
        ):
            deleted_count = await delete_tools_by_namespace("myns")

        assert deleted_count == 2
        mock_del_cache.assert_called_once_with("chroma:indexed:myns")

        # Verify that 'other::tool_c' is still present
        remaining = await collection.get(include=[])
        assert "other::tool_c" in remaining["ids"]
        assert "myns::tool_a" not in remaining["ids"]
        assert "myns::tool_b" not in remaining["ids"]

    async def test_returns_zero_when_namespace_empty(self, ephemeral_client):
        """delete_tools_by_namespace returns 0 when namespace has no tools."""
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="empty_col",
        )
        await store._get_collection()  # create collection

        with (
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new_callable=AsyncMock,
                return_value=store,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.delete_cache",
                new_callable=AsyncMock,
            ),
        ):
            deleted_count = await delete_tools_by_namespace("ghost_ns")

        assert deleted_count == 0

    async def test_returns_zero_when_store_unavailable(self):
        """delete_tools_by_namespace returns 0 when provider returns None."""
        with patch(
            "app.db.chroma.chroma_tools_store.providers.aget",
            new_callable=AsyncMock,
            return_value=None,
        ):
            deleted_count = await delete_tools_by_namespace("any_ns")

        assert deleted_count == 0


# ---------------------------------------------------------------------------
# Error paths – pickle deserialization failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPickleDeserializationFailure:
    """Verify that corrupted documents are handled gracefully, not propagated."""

    async def test_get_item_with_corrupted_document_returns_none(
        self, ephemeral_client
    ):
        """_get_item must return None when the stored document cannot be unpickled.

        The production code wraps the entire _get_item body in a broad
        except-and-return-None block, so any pickle error should produce a
        safe None result rather than leaking an internal exception.
        """
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="corrupt_test",
            index=None,
        )
        collection = await store._get_collection()

        # Insert a document whose body is not valid pickle bytes.
        corrupt_bytes = b"\x80\x99CORRUPT_DATA_NOT_VALID_PICKLE\xff"
        corrupt_doc = corrupt_bytes.decode("latin1")
        await collection.upsert(
            ids=["ns::corrupt_key"],
            documents=[corrupt_doc],
            metadatas=[{"namespace": "ns"}],
        )

        # GetOp must not raise; it should silently return None.
        results = await store.abatch(
            [GetOp(namespace=("ns",), key="corrupt_key")]
        )

        assert results[0] is None, (
            "Expected None for a corrupt document, got a result instead."
        )

    async def test_search_skips_corrupted_documents(self, ephemeral_client):
        """_filter_items must skip documents that fail pickle deserialization.

        When a collection contains one valid and one corrupt document, a
        SearchOp with a filter should only return the valid document and must
        not raise an exception.
        """
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="corrupt_search_test",
            index=None,
        )
        collection = await store._get_collection()

        # Insert one valid document and one corrupt document.
        valid_value = {"category": "tools", "tool_hash": "h_valid"}
        valid_doc = pickle.dumps(valid_value).decode("latin1")
        corrupt_doc = b"\x80\x99CORRUPT\xff".decode("latin1")

        await collection.upsert(
            ids=["ns::valid_doc", "ns::corrupt_doc"],
            documents=[valid_doc, corrupt_doc],
            metadatas=[
                {"namespace": "ns"},
                {"namespace": "ns"},
            ],
        )

        # SearchOp with a filter that matches the valid document.
        results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("ns",),
                    query=None,
                    limit=10,
                    offset=0,
                    filter={"category": "tools"},
                )
            ]
        )

        items = results[0]
        assert isinstance(items, list)
        keys = {item.key for item in items}
        # The valid document should be returned.
        assert "valid_doc" in keys
        # The corrupt document should have been silently skipped.
        assert "corrupt_doc" not in keys


# ---------------------------------------------------------------------------
# Filter operators: $gt, $lt, $eq – unit-level (_apply_operator / _check_filter)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFilterOperators:
    """Verify $gt, $lt, and $eq filter operators in ChromaStore helper methods.

    The _apply_operator and _check_filter methods implement the filter DSL used
    when a SearchOp carries a filter dict.  These tests exercise each operator
    at the method level to ensure the comparison logic is correct, and then
    exercise the full SearchOp path for filters that are supported end-to-end.

    Note on nested numeric operators ($gt/$lt via field sub-dict):
    _check_filter guards sub-dict filter recursion with
    ``if not isinstance(item_value, dict): return False``, which means that a
    filter such as ``{"score": {"$gt": 0.7}}`` is **not** evaluated when
    ``score`` is a scalar.  The tests below document that known limitation by
    asserting the current behaviour rather than an idealised one.  The
    operators *do* work correctly when called directly on _apply_operator.
    """

    # ------------------------------------------------------------------
    # _apply_operator – direct unit tests
    # ------------------------------------------------------------------

    def test_apply_operator_gt_true(self, chroma_store):
        """_apply_operator should return True when value > threshold."""
        assert chroma_store._apply_operator(0.9, "$gt", 0.7) is True

    def test_apply_operator_gt_false(self, chroma_store):
        """_apply_operator should return False when value <= threshold."""
        assert chroma_store._apply_operator(0.5, "$gt", 0.7) is False

    def test_apply_operator_lt_true(self, chroma_store):
        """_apply_operator should return True when value < threshold."""
        assert chroma_store._apply_operator(0.5, "$lt", 0.7) is True

    def test_apply_operator_lt_false(self, chroma_store):
        """_apply_operator should return False when value >= threshold."""
        assert chroma_store._apply_operator(0.9, "$lt", 0.7) is False

    def test_apply_operator_gte_boundary(self, chroma_store):
        """_apply_operator $gte should return True on exact equality."""
        assert chroma_store._apply_operator(0.7, "$gte", 0.7) is True

    def test_apply_operator_lte_boundary(self, chroma_store):
        """_apply_operator $lte should return True on exact equality."""
        assert chroma_store._apply_operator(0.7, "$lte", 0.7) is True

    def test_apply_operator_eq_true(self, chroma_store):
        """_apply_operator $eq should return True for equal values."""
        assert chroma_store._apply_operator("fruit", "$eq", "fruit") is True

    def test_apply_operator_eq_false(self, chroma_store):
        """_apply_operator $eq should return False for unequal values."""
        assert chroma_store._apply_operator("vegetable", "$eq", "fruit") is False

    def test_apply_operator_ne_true(self, chroma_store):
        """_apply_operator $ne should return True when values differ."""
        assert chroma_store._apply_operator("vegetable", "$ne", "fruit") is True

    def test_apply_operator_unsupported_raises(self, chroma_store):
        """_apply_operator should raise ValueError for an unknown operator."""
        with pytest.raises(ValueError, match="Unsupported operator"):
            chroma_store._apply_operator("x", "$unknown", "y")

    # ------------------------------------------------------------------
    # _check_filter – top-level operator and direct equality
    # ------------------------------------------------------------------

    def test_check_filter_direct_equality_match(self, chroma_store):
        """Flat equality filter should match when field value equals filter value."""
        value = {"category": "fruit"}
        assert chroma_store._check_filter(value, {"category": "fruit"}) is True

    def test_check_filter_direct_equality_no_match(self, chroma_store):
        """Flat equality filter should not match when values differ."""
        value = {"category": "vegetable"}
        assert chroma_store._check_filter(value, {"category": "fruit"}) is False

    def test_check_filter_top_level_gt_operator(self, chroma_store):
        """Top-level $gt applied to a numeric value (not nested in a field)."""
        # When the filter key starts with '$' the operator is applied to `value`
        # directly via _apply_operator.  A dict value resolves to 0 inside
        # _apply_operator, so this documents that top-level numeric operators on
        # dict values always return False.
        value = {"score": 0.9}
        assert chroma_store._check_filter(value, {"$gt": 0.7}) is False

    def test_check_filter_nested_operator_on_scalar_returns_false(self, chroma_store):
        """Field-level operator dict on a scalar field is not evaluated (known limitation).

        _check_filter returns False when it encounters a filter_value that is a
        dict but the corresponding item_value is not a dict.  This means that
        ``{"score": {"$gt": 0.7}}`` will never match when ``score`` is a float.
        """
        value = {"score": 0.9, "tool_hash": "h"}
        result = chroma_store._check_filter(value, {"score": {"$gt": 0.7}})
        # The current implementation returns False here – document that behaviour.
        assert result is False

    # ------------------------------------------------------------------
    # SearchOp integration – equality filter ($eq via direct value match)
    # ------------------------------------------------------------------

    async def test_filter_eq_operator(self, ephemeral_client):
        """Equality filter in SearchOp should return only the matching document."""
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="category_store",
            index=None,
        )
        ops = [
            PutOp(
                namespace=("items",),
                key="alpha",
                value={"category": "fruit", "tool_hash": "h_a"},
            ),
            PutOp(
                namespace=("items",),
                key="beta",
                value={"category": "vegetable", "tool_hash": "h_b"},
            ),
        ]
        await store.abatch(ops)

        results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("items",),
                    query=None,
                    limit=10,
                    offset=0,
                    filter={"category": "fruit"},
                )
            ]
        )

        items = results[0]
        keys = {item.key for item in items}
        assert "alpha" in keys, "Expected 'alpha' (category=fruit) to be returned."
        assert "beta" not in keys, (
            "Expected 'beta' (category=vegetable) to be excluded."
        )

    async def test_filter_gt_lt_via_searchop_documents_current_behaviour(
        self, ephemeral_client
    ):
        """SearchOp with $gt/$lt on a scalar field returns empty (known limitation).

        Because _check_filter returns False for ``{"score": {"$gt": 0.7}}`` when
        score is a scalar, no documents pass the filter.  This test documents
        the current (limited) behaviour so a future fix will immediately surface
        the improvement.
        """
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="scored_store_doc",
            index=None,
        )
        await store.abatch(
            [
                PutOp(
                    namespace=("metrics",),
                    key="high_score",
                    value={"score": 0.9, "tool_hash": "h_high"},
                ),
                PutOp(
                    namespace=("metrics",),
                    key="low_score",
                    value={"score": 0.5, "tool_hash": "h_low"},
                ),
            ]
        )

        gt_results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("metrics",),
                    query=None,
                    limit=10,
                    offset=0,
                    filter={"score": {"$gt": 0.7}},
                )
            ]
        )
        lt_results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("metrics",),
                    query=None,
                    limit=10,
                    offset=0,
                    filter={"score": {"$lt": 0.7}},
                )
            ]
        )

        # Current behaviour: the nested operator dict causes the scalar field
        # check to short-circuit to False, so no documents match either filter.
        assert gt_results[0] == [], (
            "Nested $gt on scalar field currently returns no results (known limitation)."
        )
        assert lt_results[0] == [], (
            "Nested $lt on scalar field currently returns no results (known limitation)."
        )


# ---------------------------------------------------------------------------
# Edge case: search returns empty list on no match
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchEdgeCases:
    """Edge cases for SearchOp."""

    async def test_search_returns_empty_on_no_match(self, chroma_store):
        """SearchOp with a filter that matches nothing should return an empty list."""
        await chroma_store.abatch(
            [
                PutOp(
                    namespace=("ns",),
                    key="only_doc",
                    value={"category": "alpha", "tool_hash": "h1"},
                )
            ]
        )

        results = await chroma_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("ns",),
                    query=None,
                    limit=10,
                    offset=0,
                    filter={"category": "nonexistent_category"},
                )
            ]
        )

        assert results[0] == [], (
            "Expected empty list when filter matches no documents."
        )

    async def test_search_returns_empty_on_empty_namespace(self, chroma_store):
        """SearchOp on a namespace with no documents should return an empty list."""
        results = await chroma_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("totally_empty_namespace",),
                    query=None,
                    limit=10,
                    offset=0,
                )
            ]
        )

        assert results[0] == [], (
            "Expected empty list when namespace has no documents."
        )


# ---------------------------------------------------------------------------
# Delete removes document
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteBehavior:
    """Verify that deleting a document removes it from search results."""

    async def test_delete_removes_document_from_search(self, chroma_store):
        """After deleting a document, it should not appear in subsequent searches."""
        ns = ("del_ns",)
        key = "to_delete"

        # Store the document.
        await chroma_store.abatch(
            [
                PutOp(
                    namespace=ns,
                    key=key,
                    value={"description": "temporary doc", "tool_hash": "h_td"},
                )
            ]
        )

        # Confirm it exists via GetOp.
        get_result = await chroma_store.abatch([GetOp(namespace=ns, key=key)])
        assert get_result[0] is not None, "Document should exist before deletion."

        # Delete it via PutOp(value=None).
        await chroma_store.abatch(
            [PutOp(namespace=ns, key=key, value=None)]
        )

        # It must not appear in a subsequent SearchOp.
        search_results = await chroma_store.abatch(
            [
                SearchOp(
                    namespace_prefix=ns,
                    query=None,
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = search_results[0]
        keys = {item.key for item in items}
        assert key not in keys, (
            "Deleted document should not appear in search results."
        )

    async def test_delete_nonexistent_document_does_not_raise(self, chroma_store):
        """Deleting a key that does not exist should not raise an exception."""
        try:
            await chroma_store.abatch(
                [
                    PutOp(
                        namespace=("ns",),
                        key="ghost_key",
                        value=None,
                    )
                ]
            )
        except Exception as exc:
            pytest.fail(
                f"Deleting a nonexistent document raised an unexpected exception: {exc}"
            )
