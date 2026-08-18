"""Tests for app/db/chroma/chroma_store.py — the filter-operator dispatch, the
ChromaDB where-clause the vector search builds, and the upsert metadata.

Hermetic counterpart to tests/integration/db/test_chroma_store.py, which drives
the same store against a real (or ephemeral) ChromaDB: these exercise the pure
translation steps with a stub collection, no server and no pickle round-trip.
"""

from unittest.mock import AsyncMock, MagicMock

from langgraph.store.base import GetOp, PutOp, SearchOp
import pytest

from app.db.chroma.chroma_store import ChromaStore


def _store() -> ChromaStore:
    return ChromaStore(client=MagicMock(), collection_name="unit_store")


def _collection(query_result: dict[str, object] | None = None) -> MagicMock:
    """A stub AsyncCollection recording the calls the store makes on it."""
    collection = MagicMock()
    collection.query = AsyncMock(
        return_value=query_result
        or {"ids": [[]], "metadatas": [[]], "distances": [[]], "documents": [[]]}
    )
    collection.get = AsyncMock(return_value={"ids": [], "metadatas": [], "documents": []})
    collection.upsert = AsyncMock()
    collection.delete = AsyncMock()
    return collection


class TestCheckFilter:
    """A top-level ``$``-key routes to the operator, everything else compares."""

    def test_a_satisfied_operator_key_passes_the_filter(self) -> None:
        assert _store()._check_filter({"a": 1}, {"$eq": {"a": 1}}) is True

    def test_an_unsatisfied_operator_key_fails_the_filter(self) -> None:
        assert _store()._check_filter({"a": 1}, {"$eq": {"a": 2}}) is False

    def test_a_negated_operator_is_read_as_written(self) -> None:
        """``$ne`` must not be inverted on its way through the dispatch."""
        assert _store()._check_filter({"a": 1}, {"$ne": {"a": 2}}) is True
        assert _store()._check_filter({"a": 1}, {"$ne": {"a": 1}}) is False

    def test_an_unsupported_operator_is_rejected_loudly(self) -> None:
        with pytest.raises(ValueError, match=r"Unsupported operator: \$regex"):
            _store()._check_filter({"a": 1}, {"$regex": "x"})

    def test_a_plain_key_compares_the_item_value(self) -> None:
        store = _store()
        assert store._check_filter({"a": 1, "b": 2}, {"a": 1}) is True
        assert store._check_filter({"a": 1}, {"a": 2}) is False


class TestBatchSearchWhereClause:
    """What the namespace prefix and the op filter become in ChromaDB's `where`."""

    @staticmethod
    async def _where(op: SearchOp) -> object:
        store = _store()
        store.embeddings = MagicMock(aembed_query=AsyncMock(return_value=[0.1, 0.2]))
        collection = _collection()

        await store._batch_search({0: (op, ["ns::k"])}, [None], collection)

        return collection.query.await_args.kwargs["where"]

    async def test_a_namespace_prefix_becomes_an_equality_on_the_joined_path(self) -> None:
        """The prefix tuple is joined with the same ``::`` separator the ids use."""
        where = await self._where(SearchOp(namespace_prefix=("memories", "u1"), query="hi"))

        assert where == {"namespace": {"$eq": "memories::u1"}}

    async def test_a_prefix_and_a_filter_are_conjoined(self) -> None:
        """Both must hold — the namespace guard is never traded for the filter."""
        where = await self._where(
            SearchOp(namespace_prefix=("memories",), filter={"kind": "note"}, query="hi")
        )

        assert where == {"$and": [{"namespace": {"$eq": "memories"}}, {"kind": "note"}]}

    async def test_a_filter_without_a_prefix_is_passed_through_alone(self) -> None:
        where = await self._where(
            SearchOp(namespace_prefix=(), filter={"kind": "note"}, query="hi")
        )

        assert where == {"kind": "note"}

    async def test_no_prefix_and_no_filter_leaves_the_query_unfiltered(self) -> None:
        where = await self._where(SearchOp(namespace_prefix=(), query="hi"))

        assert where is None

    async def test_the_page_is_fetched_deep_enough_to_reach_the_offset(self) -> None:
        """Pagination slices locally, so the query must span offset + limit."""
        store = _store()
        store.embeddings = MagicMock(aembed_query=AsyncMock(return_value=[0.1]))
        collection = _collection()

        await store._batch_search(
            {0: (SearchOp(namespace_prefix=(), limit=5, offset=10, query="hi"), ["ns::k"])},
            [None],
            collection,
        )

        assert collection.query.await_args.kwargs["n_results"] == 15

    async def test_a_search_with_no_candidates_never_queries(self) -> None:
        store = _store()
        collection = _collection()
        results: list[object] = [None]

        await store._batch_search({0: (SearchOp(namespace_prefix=()), [])}, results, collection)

        assert results == [[]]
        collection.query.assert_not_awaited()


class TestUpsertItem:
    async def test_a_string_tool_hash_reaches_chroma_metadata(self) -> None:
        """``_compute_tool_hash`` is the only producer and it returns a str."""
        collection = _collection()
        op = PutOp(namespace=("tools", "gmail"), key="send", value={"tool_hash": "abc123"})

        await _store()._upsert_item("tools::gmail::send", op, collection)

        metadata = collection.upsert.await_args.kwargs["metadatas"][0]
        assert metadata["tool_hash"] == "abc123"
        assert metadata["namespace"] == "tools::gmail"

    async def test_a_non_string_tool_hash_is_not_written_through(self) -> None:
        """Chroma metadata is str-valued here; a mistyped hash degrades to empty
        rather than being handed to the SDK as a number."""
        collection = _collection()
        op = PutOp(namespace=("tools",), key="send", value={"tool_hash": 12345})

        await _store()._upsert_item("tools::send", op, collection)

        assert collection.upsert.await_args.kwargs["metadatas"][0]["tool_hash"] == ""

    async def test_a_value_without_a_tool_hash_carries_no_such_key(self) -> None:
        collection = _collection()
        op = PutOp(namespace=("tools",), key="send", value={"name": "send"})

        await _store()._upsert_item("tools::send", op, collection)

        assert "tool_hash" not in collection.upsert.await_args.kwargs["metadatas"][0]


class TestPrepareOps:
    async def test_every_op_gets_its_own_result_slot(self) -> None:
        """Results are positional — one slot per op, in the order submitted."""
        store = _store()
        collection = _collection()
        ops = [
            GetOp(namespace=("a",), key="k1"),
            PutOp(namespace=("a",), key="k2", value={"x": 1}),
            SearchOp(namespace_prefix=("a",)),
        ]

        results, put_ops, search_ops, search_error = await store._prepare_ops(ops, collection)

        assert len(results) == len(ops)
        assert list(put_ops) == [(("a",), "k2")]
        assert list(search_ops) == [2]
        assert search_error is None

    async def test_an_unknown_op_type_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown operation type"):
            await _store()._prepare_ops([object()], _collection())  # type: ignore[list-item]
