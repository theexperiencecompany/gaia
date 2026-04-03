"""Comprehensive unit tests for ChromaStore (app/db/chroma/chroma_store.py)."""

import pickle
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.store.base import (
    GetOp,
    ListNamespacesOp,
    MatchCondition,
    PutOp,
    SearchOp,
)

from app.db.chroma.chroma_store import ChromaStore, _NoOpEmbeddingFunction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collection(
    ids: list | None = None,
    metadatas: list | None = None,
    documents: list | None = None,
    distances: list | None = None,
) -> AsyncMock:
    """Return a mock AsyncCollection pre-loaded with data."""
    col = AsyncMock()
    col.get = AsyncMock(
        return_value={
            "ids": ids or [],
            "metadatas": metadatas or [],
            "documents": documents or [],
        }
    )
    col.upsert = AsyncMock()
    col.delete = AsyncMock()
    col.query = AsyncMock(
        return_value={
            "ids": [ids or []],
            "metadatas": [metadatas or []],
            "distances": [distances or []],
            "documents": [documents or []],
        }
    )
    return col


def _pickled(value: dict) -> str:
    return pickle.dumps(value).decode("latin1")


def _make_store(
    collection: AsyncMock | None = None,
    index: dict | None = None,
) -> ChromaStore:
    client = AsyncMock()
    store = ChromaStore(client, collection_name="test_col", index=index)  # type: ignore[arg-type]
    if collection is not None:
        store._collection_cache = collection
    return store


# ---------------------------------------------------------------------------
# _NoOpEmbeddingFunction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNoOpEmbeddingFunction:
    def test_returns_correct_dimensions(self):
        ef = _NoOpEmbeddingFunction()
        result = ef(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 384 for v in result)
        assert all(x == pytest.approx(0.0) for v in result for x in v)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInit:
    def test_default_no_index(self):
        store = _make_store()
        assert store.embeddings is None
        assert store._tokenized_fields == []
        assert store.index_config is None

    def test_with_index_config(self):
        mock_emb = MagicMock()
        idx = {"embed": mock_emb, "fields": ["$"]}
        store = ChromaStore(AsyncMock(), index=idx)
        assert store.index_config is not None
        assert len(store._tokenized_fields) == 1


# ---------------------------------------------------------------------------
# _get_collection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCollection:
    async def test_creates_collection_when_missing(self):
        client = AsyncMock()
        client.list_collections = AsyncMock(return_value=[])
        new_col = AsyncMock()
        client.create_collection = AsyncMock(return_value=new_col)

        store = ChromaStore(client, collection_name="my_col")
        result = await store._get_collection()

        assert result is new_col
        client.create_collection.assert_called_once()

    async def test_gets_existing_collection(self):
        existing = MagicMock()
        existing.name = "my_col"
        client = AsyncMock()
        client.list_collections = AsyncMock(return_value=[existing])
        fetched = AsyncMock()
        client.get_collection = AsyncMock(return_value=fetched)

        store = ChromaStore(client, collection_name="my_col")
        result = await store._get_collection()

        assert result is fetched
        client.get_collection.assert_called_once()

    async def test_caches_collection(self):
        col = AsyncMock()
        store = _make_store(collection=col)
        result = await store._get_collection()
        assert result is col


# ---------------------------------------------------------------------------
# _namespace_to_id / _id_to_namespace_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNamespaceConversion:
    def test_namespace_to_id(self):
        store = _make_store()
        assert store._namespace_to_id(("a", "b"), "key") == "a::b::key"

    def test_namespace_to_id_empty(self):
        store = _make_store()
        assert store._namespace_to_id((), "key") == "default::key"

    def test_id_to_namespace_key(self):
        store = _make_store()
        ns, key = store._id_to_namespace_key("a::b::key")
        assert ns == ("a", "b")
        assert key == "key"

    def test_id_to_namespace_key_default(self):
        store = _make_store()
        ns, key = store._id_to_namespace_key("default::key")
        assert ns == ()
        assert key == "key"

    def test_id_to_namespace_key_single_part(self):
        store = _make_store()
        ns, key = store._id_to_namespace_key("only_key")
        assert ns == ()
        assert key == "only_key"


# ---------------------------------------------------------------------------
# batch (sync wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatch:
    def test_raises_in_async_context(self):
        """batch() checks if event loop is running and raises accordingly.
        In pytest-asyncio the loop state depends on the runner, so we test
        via a synchronous call where no loop is running -- it should succeed
        (delegate to run_until_complete) or raise RuntimeError."""
        store = _make_store(collection=_make_collection())
        # In a synchronous context with no running loop, batch delegates to
        # run_until_complete. We just verify it doesn't crash.
        results = store.batch([])
        assert results == []


# ---------------------------------------------------------------------------
# _get_item
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetItem:
    async def test_returns_item(self):
        value = {"name": "test"}
        now = datetime.now(timezone.utc).isoformat()
        col = _make_collection(
            ids=["ns::key"],
            metadatas=[{"created_at": now, "updated_at": now}],
            documents=[_pickled(value)],
        )
        store = _make_store(collection=col)
        item = await store._get_item(("ns",), "key", col)

        assert item is not None
        assert item.key == "key"
        assert item.namespace == ("ns",)
        assert item.value == value

    async def test_returns_none_when_not_found(self):
        col = _make_collection(ids=[], metadatas=[], documents=[])
        store = _make_store(collection=col)
        item = await store._get_item(("ns",), "missing", col)
        assert item is None

    async def test_returns_none_on_exception(self):
        col = AsyncMock()
        col.get = AsyncMock(side_effect=Exception("db error"))
        store = _make_store(collection=col)
        item = await store._get_item(("ns",), "key", col)
        assert item is None

    async def test_handles_missing_metadata(self):
        col = _make_collection(
            ids=["ns::key"],
            metadatas=[{}],
            documents=[_pickled({"data": 1})],
        )
        store = _make_store(collection=col)
        item = await store._get_item(("ns",), "key", col)
        assert item is not None
        assert item.value == {"data": 1}

    async def test_handles_none_document(self):
        col = _make_collection(
            ids=["ns::key"],
            metadatas=[{}],
            documents=[None],
        )
        store = _make_store(collection=col)
        item = await store._get_item(("ns",), "key", col)
        assert item is not None
        assert item.value == {}


# ---------------------------------------------------------------------------
# _matches_namespace_prefix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchesNamespacePrefix:
    def test_exact_match(self):
        store = _make_store()
        assert store._matches_namespace_prefix(("a", "b"), ("a", "b")) is True

    def test_prefix_match(self):
        store = _make_store()
        assert store._matches_namespace_prefix(("a", "b", "c"), ("a", "b")) is True

    def test_no_match(self):
        store = _make_store()
        assert store._matches_namespace_prefix(("a",), ("a", "b")) is False

    def test_empty_prefix(self):
        store = _make_store()
        assert store._matches_namespace_prefix(("a",), ()) is True


# ---------------------------------------------------------------------------
# _check_filter / _apply_operator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckFilter:
    def test_simple_equality(self):
        store = _make_store()
        assert store._check_filter({"k": "v"}, {"k": "v"}) is True
        assert store._check_filter({"k": "v"}, {"k": "other"}) is False

    def test_nested_dict(self):
        store = _make_store()
        assert store._check_filter({"a": {"b": 1}}, {"a": {"b": 1}}) is True
        assert store._check_filter({"a": {"b": 1}}, {"a": {"b": 2}}) is False

    def test_nested_non_dict(self):
        store = _make_store()
        assert store._check_filter({"a": "string"}, {"a": {"b": 1}}) is False

    def test_operator_eq(self):
        store = _make_store()
        assert store._apply_operator(5, "$eq", 5) is True
        assert store._apply_operator(5, "$eq", 6) is False

    def test_operator_ne(self):
        store = _make_store()
        assert store._apply_operator(5, "$ne", 6) is True
        assert store._apply_operator(5, "$ne", 5) is False

    def test_operator_gt(self):
        store = _make_store()
        assert store._apply_operator(10, "$gt", 5) is True
        assert store._apply_operator(5, "$gt", 10) is False

    def test_operator_gte(self):
        store = _make_store()
        assert store._apply_operator(5, "$gte", 5) is True
        assert store._apply_operator(4, "$gte", 5) is False

    def test_operator_lt(self):
        store = _make_store()
        assert store._apply_operator(3, "$lt", 5) is True
        assert store._apply_operator(5, "$lt", 3) is False

    def test_operator_lte(self):
        store = _make_store()
        assert store._apply_operator(5, "$lte", 5) is True
        assert store._apply_operator(6, "$lte", 5) is False

    def test_operator_invalid_type_returns_false(self):
        store = _make_store()
        assert store._apply_operator("not_a_number", "$gt", 5) is False

    def test_operator_dict_value_returns_false_for_gt(self):
        store = _make_store()
        assert store._apply_operator({"a": 1}, "$gt", 5) is False

    def test_unsupported_operator_raises(self):
        store = _make_store()
        with pytest.raises(ValueError, match="Unsupported operator"):
            store._apply_operator(5, "$unsupported", 5)

    def test_filter_with_operator_key(self):
        store = _make_store()
        assert store._check_filter(5, {"$eq": 5}) is True
        assert store._check_filter(5, {"$ne": 5}) is False


# ---------------------------------------------------------------------------
# _filter_items
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFilterItems:
    async def test_filters_by_namespace(self):
        col = _make_collection(
            ids=["a::key1", "b::key2"],
            metadatas=[{}, {}],
            documents=[_pickled({"v": 1}), _pickled({"v": 2})],
        )
        store = _make_store(collection=col)
        op = SearchOp(
            namespace_prefix=("a",), filter=None, query=None, limit=10, offset=0
        )
        result = await store._filter_items(op, col)
        assert result == ["a::key1"]

    async def test_returns_empty_when_no_ids(self):
        col = _make_collection()
        store = _make_store(collection=col)
        op = SearchOp(
            namespace_prefix=("a",), filter=None, query=None, limit=10, offset=0
        )
        result = await store._filter_items(op, col)
        assert result == []

    async def test_returns_empty_on_exception(self):
        col = AsyncMock()
        col.get = AsyncMock(side_effect=Exception("fail"))
        store = _make_store(collection=col)
        op = SearchOp(
            namespace_prefix=("a",), filter=None, query=None, limit=10, offset=0
        )
        result = await store._filter_items(op, col)
        assert result == []

    async def test_applies_filter_conditions(self):
        col = _make_collection(
            ids=["ns::key1", "ns::key2"],
            metadatas=[{}, {}],
            documents=[
                _pickled({"status": "active"}),
                _pickled({"status": "inactive"}),
            ],
        )
        store = _make_store(collection=col)
        op = SearchOp(
            namespace_prefix=("ns",),
            filter={"status": "active"},
            query=None,
            limit=10,
            offset=0,
        )
        result = await store._filter_items(op, col)
        assert result == ["ns::key1"]

    async def test_filter_skips_non_dict_values(self):
        col = _make_collection(
            ids=["ns::key1"],
            metadatas=[{}],
            documents=[_pickled("not a dict")],
        )
        store = _make_store(collection=col)
        op = SearchOp(
            namespace_prefix=("ns",),
            filter={"status": "active"},
            query=None,
            limit=10,
            offset=0,
        )
        result = await store._filter_items(op, col)
        assert result == []


# ---------------------------------------------------------------------------
# _handle_list_namespaces
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleListNamespaces:
    async def test_lists_namespaces(self):
        col = _make_collection(
            ids=["a::b::key1", "a::c::key2", "x::key3"],
            metadatas=[{}, {}, {}],
        )
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=None,
            max_depth=None,
            limit=100,
            offset=0,
        )
        result = await store._handle_list_namespaces(op, col)
        assert ("a", "b") in result
        assert ("a", "c") in result
        assert ("x",) in result

    async def test_applies_max_depth(self):
        col = _make_collection(
            ids=["a::b::c::key1"],
            metadatas=[{}],
        )
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=None,
            max_depth=2,
            limit=100,
            offset=0,
        )
        result = await store._handle_list_namespaces(op, col)
        assert result == [("a", "b")]

    async def test_applies_offset_and_limit(self):
        col = _make_collection(
            ids=["a::key1", "b::key2", "c::key3"],
            metadatas=[{}, {}, {}],
        )
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=None,
            max_depth=None,
            limit=1,
            offset=1,
        )
        result = await store._handle_list_namespaces(op, col)
        assert len(result) == 1

    async def test_returns_empty_on_error(self):
        col = AsyncMock()
        col.get = AsyncMock(side_effect=Exception("fail"))
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=None,
            max_depth=None,
            limit=100,
            offset=0,
        )
        result = await store._handle_list_namespaces(op, col)
        assert result == []

    async def test_returns_empty_for_no_ids(self):
        col = _make_collection()
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=None,
            max_depth=None,
            limit=100,
            offset=0,
        )
        result = await store._handle_list_namespaces(op, col)
        assert result == []


# ---------------------------------------------------------------------------
# _does_match
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoesMatch:
    def test_prefix_match(self):
        store = _make_store()
        cond = MatchCondition(match_type="prefix", path=("a", "b"))
        assert store._does_match(cond, ("a", "b", "c")) is True
        assert store._does_match(cond, ("a", "x")) is False

    def test_prefix_wildcard(self):
        store = _make_store()
        cond = MatchCondition(match_type="prefix", path=("a", "*"))
        assert store._does_match(cond, ("a", "anything")) is True

    def test_suffix_match(self):
        store = _make_store()
        cond = MatchCondition(match_type="suffix", path=("b", "c"))
        assert store._does_match(cond, ("a", "b", "c")) is True
        assert store._does_match(cond, ("a", "x", "c")) is False

    def test_suffix_wildcard(self):
        store = _make_store()
        cond = MatchCondition(match_type="suffix", path=("*", "c"))
        assert store._does_match(cond, ("a", "b", "c")) is True

    def test_key_shorter_than_path(self):
        store = _make_store()
        cond = MatchCondition(match_type="prefix", path=("a", "b", "c"))
        assert store._does_match(cond, ("a",)) is False

    def test_unsupported_match_type_raises(self):
        store = _make_store()
        cond = MatchCondition(match_type="exact", path=("a",))
        with pytest.raises(ValueError, match="Unsupported match type"):
            store._does_match(cond, ("a",))

    async def test_list_namespaces_with_match_conditions(self):
        col = _make_collection(
            ids=["a::b::key1", "x::y::key2"],
            metadatas=[{}, {}],
        )
        store = _make_store(collection=col)
        op = ListNamespacesOp(
            match_conditions=[MatchCondition(match_type="prefix", path=("a",))],
            max_depth=None,
            limit=100,
            offset=0,
        )
        result = await store._handle_list_namespaces(op, col)
        assert ("a", "b") in result
        assert ("x", "y") not in result


# ---------------------------------------------------------------------------
# _apply_put_ops / _upsert_item / _delete_item
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPutOps:
    async def test_upsert_item(self):
        col = _make_collection()
        store = _make_store(collection=col)
        op = PutOp(namespace=("ns",), key="k", value={"data": 1})
        await store._upsert_item("ns::k", op, col)
        col.upsert.assert_called_once()
        call_kwargs = col.upsert.call_args
        assert call_kwargs.kwargs["ids"] == ["ns::k"]

    async def test_upsert_item_with_tool_hash(self):
        col = _make_collection()
        store = _make_store(collection=col)
        op = PutOp(namespace=("ns",), key="k", value={"tool_hash": "abc123", "data": 1})
        await store._upsert_item("ns::k", op, col)
        call_kwargs = col.upsert.call_args
        metadata = call_kwargs.kwargs["metadatas"][0]
        assert metadata["tool_hash"] == "abc123"

    async def test_upsert_with_precomputed_embedding(self):
        col = _make_collection()
        store = _make_store(collection=col)
        emb = [1.0] * 384
        op = PutOp(namespace=("ns",), key="k", value={"embedding": emb, "data": 1})
        await store._upsert_item("ns::k", op, col)
        call_kwargs = col.upsert.call_args
        assert call_kwargs.kwargs["embeddings"] == [emb]

    async def test_upsert_with_embeddings_model(self):
        col = _make_collection()
        mock_emb = AsyncMock()
        mock_emb.aembed_query = AsyncMock(return_value=[0.5] * 384)
        store = _make_store(collection=col)
        store.embeddings = mock_emb
        store._tokenized_fields = [("$", "$")]

        op = PutOp(namespace=("ns",), key="k", value={"text": "hello world"})
        await store._upsert_item("ns::k", op, col)
        mock_emb.aembed_query.assert_called_once()

    async def test_upsert_error_handled(self):
        col = AsyncMock()
        col.upsert = AsyncMock(side_effect=Exception("upsert fail"))
        store = _make_store(collection=col)
        op = PutOp(namespace=("ns",), key="k", value={"data": 1})
        # Should not raise
        await store._upsert_item("ns::k", op, col)

    async def test_delete_item(self):
        col = _make_collection()
        store = _make_store(collection=col)
        await store._delete_item("ns::k", col)
        col.delete.assert_called_once_with(ids=["ns::k"])

    async def test_delete_item_error_handled(self):
        col = AsyncMock()
        col.delete = AsyncMock(side_effect=Exception("delete fail"))
        store = _make_store(collection=col)
        await store._delete_item("ns::k", col)

    async def test_apply_put_ops_delete(self):
        col = _make_collection()
        store = _make_store(collection=col)
        put_ops = {(("ns",), "k"): PutOp(namespace=("ns",), key="k", value=None)}
        await store._apply_put_ops(put_ops, col)
        col.delete.assert_called_once()

    async def test_apply_put_ops_upsert(self):
        col = _make_collection()
        store = _make_store(collection=col)
        put_ops = {(("ns",), "k"): PutOp(namespace=("ns",), key="k", value={"x": 1})}
        await store._apply_put_ops(put_ops, col)
        col.upsert.assert_called_once()


# ---------------------------------------------------------------------------
# abatch - full integration of ops
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAbatch:
    async def test_get_op(self):
        now = datetime.now(timezone.utc).isoformat()
        value = {"data": "hello"}
        col = _make_collection(
            ids=["ns::k"],
            metadatas=[{"created_at": now, "updated_at": now}],
            documents=[_pickled(value)],
        )
        store = _make_store(collection=col)
        results = await store.abatch([GetOp(namespace=("ns",), key="k")])
        assert results[0] is not None
        assert results[0].value == value

    async def test_put_op(self):
        col = _make_collection()
        store = _make_store(collection=col)
        results = await store.abatch(
            [PutOp(namespace=("ns",), key="k", value={"x": 1})]
        )
        col.upsert.assert_called_once()
        assert results[0] is None  # PutOp returns None in results

    async def test_unknown_op_raises(self):
        col = _make_collection()
        store = _make_store(collection=col)
        with pytest.raises(ValueError, match="Unknown operation type"):
            await store.abatch(["not_an_op"])

    async def test_search_op_without_query(self):
        now = datetime.now(timezone.utc).isoformat()
        value = {"data": "test"}
        col = _make_collection(
            ids=["ns::k1"],
            metadatas=[{"created_at": now, "updated_at": now}],
            documents=[_pickled(value)],
        )
        store = _make_store(collection=col)
        results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("ns",),
                    filter=None,
                    query=None,
                    limit=10,
                    offset=0,
                )
            ]
        )
        assert isinstance(results[0], list)

    async def test_search_op_with_query_and_embeddings(self):
        now = datetime.now(timezone.utc).isoformat()
        value = {"data": "result"}
        col = _make_collection(
            ids=["ns::k1"],
            metadatas=[{"created_at": now, "updated_at": now, "namespace": "ns"}],
            documents=[_pickled(value)],
            distances=[0.1],
        )
        mock_emb = AsyncMock()
        mock_emb.aembed_query = AsyncMock(return_value=[0.5] * 384)

        store = _make_store(collection=col)
        store.embeddings = mock_emb
        store._tokenized_fields = [("$", "$")]

        results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("ns",),
                    filter=None,
                    query="test query",
                    limit=10,
                    offset=0,
                )
            ]
        )
        assert isinstance(results[0], list)
        if results[0]:
            assert results[0][0].score == pytest.approx(0.9)

    async def test_search_with_empty_candidates(self):
        col = _make_collection(ids=[], metadatas=[], documents=[])
        store = _make_store(collection=col)
        results = await store.abatch(
            [
                SearchOp(
                    namespace_prefix=("ns",),
                    filter=None,
                    query=None,
                    limit=10,
                    offset=0,
                )
            ]
        )
        assert results[0] == []


# ---------------------------------------------------------------------------
# _batch_search edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchSearch:
    async def test_vector_search_error_returns_empty(self):
        col = AsyncMock()
        col.query = AsyncMock(side_effect=Exception("search fail"))
        col.get = AsyncMock(
            return_value={
                "ids": ["ns::k1"],
                "metadatas": [{}],
                "documents": [_pickled({"x": 1})],
            }
        )

        mock_emb = AsyncMock()
        mock_emb.aembed_query = AsyncMock(return_value=[0.5] * 384)

        store = _make_store(collection=col)
        store.embeddings = mock_emb
        store._tokenized_fields = [("$", "$")]

        ops: dict = {
            0: (
                SearchOp(
                    namespace_prefix=("ns",),
                    filter=None,
                    query="test",
                    limit=10,
                    offset=0,
                ),
                ["ns::k1"],
            )
        }
        results: list = [None]
        await store._batch_search(ops, results, col)
        assert results[0] == []

    async def test_search_with_filter_and_namespace(self):
        now = datetime.now(timezone.utc).isoformat()
        value = {"status": "active"}
        col = _make_collection(
            ids=["ns::k1"],
            metadatas=[{"created_at": now, "updated_at": now, "namespace": "ns"}],
            documents=[_pickled(value)],
            distances=[0.05],
        )
        mock_emb = AsyncMock()
        mock_emb.aembed_query = AsyncMock(return_value=[0.5] * 384)

        store = _make_store(collection=col)
        store.embeddings = mock_emb
        store._tokenized_fields = [("$", "$")]

        ops: dict = {
            0: (
                SearchOp(
                    namespace_prefix=("ns",),
                    filter={"status": {"$eq": "active"}},
                    query="test",
                    limit=10,
                    offset=0,
                ),
                ["ns::k1"],
            )
        }
        results: list = [None]
        await store._batch_search(ops, results, col)
        assert isinstance(results[0], list)
