"""Unit tests for ChromaStore, run against an in-memory stand-in for a Chroma collection.

The real in-process chromadb client cannot survive fork(), which every mutmut
mutant does, so the integration file (tests/integration/db/test_chroma_store.py)
keeps the real-client round trips and this file pins the store's own logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
import pickle  # nosec B403 - the fake stores exactly what ChromaStore pickled
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.embeddings import Embeddings
from langgraph.store.base import (
    GetOp,
    ListNamespacesOp,
    MatchCondition,
    PutOp,
    SearchOp,
)
import pytest

from app.constants.log_tags import LogTag
from app.db.chroma.chroma_store import ChromaBatchWriteError, ChromaStore, _stored_time
from tests._harness.chroma_fakes import (
    FakeChromaClient,
    FakeChromaCollection,
    pickled_document,
)

MODULE = "app.db.chroma.chroma_store"
STAMP = "2026-01-02T03:04:05+00:00"
LATER = "2026-02-03T04:05:06+00:00"


class _AxisEmbeddings(Embeddings):
    """Embed a text onto the axis of the first known word it contains."""

    AXES: ClassVar[dict[str, list[float]]] = {
        "mail": [1.0, 0.0, 0.0],
        "calendar": [0.0, 1.0, 0.0],
        "notes": [0.0, 0.0, 1.0],
    }

    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.seen.append(text)
        for word, axis in self.AXES.items():
            if word in text:
                return axis
        return [0.5, 0.5, 0.5]


def _store(*, index: bool = False, fields: list[str] | None = None) -> ChromaStore:
    collection = FakeChromaCollection()
    config = None
    if index:
        config = {"embed": _AxisEmbeddings(), "dims": 3}
        if fields is not None:
            config["fields"] = fields
    return ChromaStore(client=FakeChromaClient(collection), collection_name="c", index=config)


def _collection(store: ChromaStore) -> FakeChromaCollection:
    return store.client.collection


@pytest.mark.unit
class TestStoredTime:
    def test_an_iso_stamp_is_parsed(self) -> None:
        assert _stored_time(STAMP) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    @pytest.mark.parametrize("missing", [None, "", 7])
    def test_a_missing_or_foreign_stamp_reads_as_now(self, missing: object) -> None:
        before = datetime.now(UTC)
        stamp = _stored_time(missing)
        assert before <= stamp <= datetime.now(UTC)
        assert stamp.tzinfo is UTC


@pytest.mark.unit
class TestInit:
    def test_an_index_config_is_copied_and_its_fields_tokenized(self) -> None:
        embeddings = _AxisEmbeddings()
        config = {"embed": embeddings, "dims": 3, "fields": ["rich_description", "$"]}
        store = ChromaStore(client=MagicMock(), collection_name="c", index=config)

        assert store.index_config == config
        assert store.index_config is not config
        assert store.embeddings is embeddings
        assert store._tokenized_fields == [("rich_description", ["rich_description"]), ("$", "$")]

    def test_an_index_without_fields_embeds_the_whole_value(self) -> None:
        store = _store(index=True)
        assert store._tokenized_fields == [("$", "$")]

    def test_no_index_means_no_embeddings(self) -> None:
        store = _store()
        assert (store.index_config, store.embeddings, store._tokenized_fields) == (None, None, [])


@pytest.mark.unit
class TestGet:
    async def test_a_stored_item_reads_back_with_its_stamps(self) -> None:
        store = _store()
        _collection(store).add(
            "tools::web", {"created_at": STAMP, "updated_at": STAMP}, {"description": "d"}
        )

        (item,) = await store.abatch([GetOp(namespace=("tools",), key="web")])

        assert item.value == {"description": "d"}
        assert (item.namespace, item.key) == (("tools",), "web")
        assert item.created_at == item.updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert _collection(store).gets == [
            {"ids": ["tools::web"], "include": ["metadatas", "documents"]}
        ]

    async def test_a_row_without_a_document_reads_as_an_empty_value(self) -> None:
        store = _store()
        _collection(store).add("default::k", {})

        (item,) = await store.abatch([GetOp(namespace=(), key="k")])

        assert item.value == {}

    async def test_a_missing_key_is_none(self) -> None:
        store = _store()
        assert await store.abatch([GetOp(namespace=("tools",), key="nope")]) == [None]

    async def test_a_failed_read_is_logged_and_reads_as_none(self) -> None:
        store = _store()
        _collection(store).get = AsyncMock(side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.log") as log:
            result = await store.abatch([GetOp(namespace=("tools",), key="web")])

        assert result == [None]
        log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error getting item",
            doc_id="tools::web",
            error="down",
            error_type="ConnectionError",
        )


@pytest.mark.unit
class TestPut:
    async def test_metadata_carries_the_namespace_stamps_and_both_index_hashes(self) -> None:
        store = _store()
        await store.abatch(
            [
                PutOp(
                    namespace=("workflow_triggers",),
                    key="t",
                    value={"trigger_hash": "th", "tool_hash": "toh", "x": 1},
                ),
                PutOp(namespace=(), key="plain", value={"x": 2}),
            ]
        )

        _, metadata, document = _collection(store).rows["workflow_triggers::t"]
        assert metadata["namespace"] == "workflow_triggers"
        assert (metadata["tool_hash"], metadata["trigger_hash"]) == ("toh", "th")
        assert datetime.fromisoformat(metadata["created_at"]).tzinfo == UTC
        assert metadata["created_at"] == metadata["updated_at"]
        assert pickle.loads(document.encode("latin1")) == {  # nosec B301 - test round trip
            "trigger_hash": "th",
            "tool_hash": "toh",
            "x": 1,
        }
        _, plain_metadata, _ = _collection(store).rows["default::plain"]
        assert set(plain_metadata) == {"created_at", "updated_at", "namespace"}
        assert plain_metadata["namespace"] == "default"

    async def test_a_supplied_vector_is_stored_as_is(self) -> None:
        store = _store(index=True)
        await store.abatch(
            [PutOp(namespace=("n",), key="k", value={"text": "mail", "embedding": [0.1, 0.2]})]
        )

        assert _collection(store).rows["n::k"][0] == [0.1, 0.2]
        assert store.embeddings.seen == []

    async def test_the_indexed_fields_are_embedded_as_one_text(self) -> None:
        store = _store(index=True, fields=["title", "body"])
        await store.abatch(
            [PutOp(namespace=("n",), key="k", value={"title": "mail", "body": "inbox", "x": "no"})]
        )

        assert store.embeddings.seen == ["mail inbox"]
        assert _collection(store).rows["n::k"][0] == [1.0, 0.0, 0.0]

    async def test_a_put_names_its_own_fields_over_the_store_default(self) -> None:
        store = _store(index=True, fields=["title"])
        await store.abatch(
            [
                PutOp(
                    namespace=("n",),
                    key="k",
                    value={"title": "x", "body": "calendar"},
                    index=["body"],
                )
            ]
        )

        assert store.embeddings.seen == ["calendar"]

    async def test_a_value_with_no_embeddable_text_is_stored_without_a_vector(self) -> None:
        store = _store(index=True, fields=["title"])
        await store.abatch([PutOp(namespace=("n",), key="k", value={"body": "calendar"})])

        assert store.embeddings.seen == []
        assert _collection(store).rows["n::k"][0] is None

    async def test_index_false_skips_embedding(self) -> None:
        store = _store(index=True)
        await store.abatch([PutOp(namespace=("n",), key="k", value={"t": "mail"}, index=False)])

        assert store.embeddings.seen == []
        assert _collection(store).rows["n::k"][0] is None

    async def test_a_failed_embedding_fails_the_batch_and_says_where(self) -> None:
        store = _store(index=True, fields=["t"])
        store.embeddings.aembed_query = AsyncMock(side_effect=TimeoutError())

        with patch(f"{MODULE}.log") as log, pytest.raises(ChromaBatchWriteError):
            await store.abatch([PutOp(namespace=("n", "m"), key="k", value={"t": "mail"})])

        log.error.assert_any_call(
            f"{LogTag.CHROMA} _upsert_item embedding failed",
            doc_id="n::m::k",
            namespace="n::m",
            text_len=4,
            error_type="TimeoutError",
        )
        assert "n::m::k" not in _collection(store).rows

    async def test_a_none_value_deletes_the_row(self) -> None:
        store = _store()
        _collection(store).add("n::k", {}, {"x": 1})

        await store.abatch([PutOp(namespace=("n",), key="k", value=None)])

        assert _collection(store).rows == {}

    async def test_failed_writes_fail_the_batch_after_the_rest_land(self) -> None:
        store = _store()
        collection = _collection(store)
        collection.add("n::gone", {}, {"x": 1})
        collection.fail_upsert_for = {"n::bad"}
        collection.fail_delete_for = {"n::gone"}

        with patch(f"{MODULE}.log") as log, pytest.raises(ChromaBatchWriteError) as raised:
            await store.abatch(
                [
                    PutOp(namespace=("n",), key="ok", value={"x": 1}),
                    PutOp(namespace=("n",), key="bad", value={"x": 2}),
                    PutOp(namespace=("n",), key="gone", value=None),
                ]
            )

        assert str(raised.value) == "2 of 3 ChromaDB writes failed"
        assert isinstance(raised.value.__cause__, ConnectionError)
        assert "n::ok" in collection.rows
        log.error.assert_any_call(
            f"{LogTag.CHROMA} Error upserting item",
            doc_id="n::bad",
            namespace="n",
            error_type="ConnectionError",
        )
        log.error.assert_any_call(
            f"{LogTag.CHROMA} Error deleting item", doc_id="n::gone", error_type="ConnectionError"
        )
        log.error.assert_any_call(
            f"{LogTag.CHROMA} _apply_put_ops failure",
            doc_id="n::bad",
            error_type="ConnectionError",
        )
        log.error.assert_any_call(
            f"{LogTag.CHROMA} _apply_put_ops failure",
            doc_id="n::gone",
            error_type="ConnectionError",
        )

    async def test_at_most_three_failures_are_itemised(self) -> None:
        store = _store()
        _collection(store).fail_upsert_for = {f"n::{i}" for i in range(5)}

        with patch(f"{MODULE}.log") as log, pytest.raises(ChromaBatchWriteError) as raised:
            await store.abatch(
                [PutOp(namespace=("n",), key=str(i), value={"i": i}) for i in range(5)]
            )

        itemised = [
            c for c in log.error.call_args_list if c.args[0].endswith("_apply_put_ops failure")
        ]
        assert [c.kwargs["doc_id"] for c in itemised] == ["n::0", "n::1", "n::2"]
        assert str(raised.value) == "5 of 5 ChromaDB writes failed"


def _seed(store: ChromaStore) -> None:
    collection = _collection(store)
    collection.add("tools::a", {}, {"kind": "mail", "n": 3, "meta": {"tier": "pro"}})
    collection.add("tools::b", {}, {"kind": "calendar", "n": 7, "meta": {"tier": "free"}})
    collection.add("tools::c", {}, ["not", "a", "dict"])
    collection.add("other::d", {}, {"kind": "mail", "n": 1})
    collection.rows["tools::e"] = (None, {}, "not a pickle")


@pytest.mark.unit
class TestSearchWithoutAQuery:
    async def _keys(self, store: ChromaStore, **op: object) -> list[str]:
        (results,) = await store.abatch([SearchOp(namespace_prefix=("tools",), **op)])
        return [item.key for item in results]

    async def test_no_filter_returns_the_namespace_paged(self) -> None:
        store = _store()
        _seed(store)

        # e's document does not unpickle, so its read fails and it drops out of the page.
        assert await self._keys(store) == ["a", "b", "c"]
        assert await self._keys(store, limit=2, offset=1) == ["b", "c"]
        assert await self._keys(store, limit=1, offset=3) == []
        assert _collection(store).gets[0] == {"ids": None, "include": ["metadatas", "documents"]}

    async def test_a_field_filter_keeps_only_matching_dict_values(self) -> None:
        store = _store()
        _seed(store)

        assert await self._keys(store, filter={"kind": "mail"}) == ["a"]
        assert await self._keys(store, filter={"meta": {"tier": "free"}}) == ["b"]
        assert await self._keys(store, filter={"kind": {"tier": "free"}}) == []

    @pytest.mark.parametrize(
        ("value", "operator", "operand", "expected"),
        [
            (3, "$eq", 3, True),
            (3, "$eq", 4, False),
            (3, "$ne", 4, True),
            (3, "$ne", 3, False),
            (7, "$gt", 3, True),
            (3, "$gt", 3, False),
            (3, "$gte", 3, True),
            (2, "$gte", 3, False),
            (2, "$lt", 3, True),
            (3, "$lt", 3, False),
            (3, "$lte", 3, True),
            (4, "$lte", 3, False),
            ("2.5", "$gt", "2", True),
            ("abc", "$gt", 1, False),
            (None, "$lt", 1, False),
            (1, "$gt", "abc", False),
            ({"a": 1}, "$lt", 1, True),
            ({"a": 1}, "$gt", 0, False),
        ],
    )
    def test_operators_compare_numerically(
        self, value: object, operator: str, operand: object, expected: bool
    ) -> None:
        assert _store()._apply_operator(value, operator, operand) is expected

    async def test_a_top_level_operator_compares_the_whole_value(self) -> None:
        store = _store()
        _seed(store)

        whole_b = {"kind": "calendar", "n": 7, "meta": {"tier": "free"}}
        assert await self._keys(store, filter={"$eq": whole_b}) == ["b"]
        assert await self._keys(store, filter={"$ne": whole_b}) == ["a"]

    async def test_an_unknown_operator_fails_the_search_after_sibling_writes(self) -> None:
        store = _store()
        _seed(store)

        with (
            patch(f"{MODULE}.log") as log,
            pytest.raises(ValueError, match=r"Unsupported operator: \$in"),
        ):
            await store.abatch(
                [
                    SearchOp(namespace_prefix=("tools",), filter={"$in": [3]}),
                    PutOp(namespace=("tools",), key="z", value={"x": 1}),
                ]
            )

        assert "tools::z" in _collection(store).rows
        log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error filtering items", error_type="ValueError"
        )

    async def test_unreadable_rows_are_skipped_not_the_end_of_the_scan(self) -> None:
        store = _store()
        collection = _collection(store)
        collection.rows["tools::no_doc"] = (None, {}, None)
        collection.rows["tools::bad"] = (None, {}, "not a pickle")
        collection.add("tools::list", {}, ["x"])
        collection.add("tools::hit", {}, {"kind": "mail"})

        assert await self._keys(store, filter={"kind": "mail"}) == ["hit"]

    async def test_a_page_carries_each_items_value_and_stamps(self) -> None:
        store = _store()
        _collection(store).add(
            "tools::a", {"created_at": STAMP, "updated_at": LATER}, {"kind": "mail"}
        )

        (results,) = await store.abatch([SearchOp(namespace_prefix=("tools",))])

        assert [(r.key, r.value) for r in results] == [("a", {"kind": "mail"})]
        assert results[0].created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert results[0].updated_at == datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)

    async def test_an_empty_collection_or_namespace_finds_nothing(self) -> None:
        store = _store()
        assert await self._keys(store) == []
        _collection(store).add("other::x", {}, {"x": 1})
        assert await self._keys(store) == []
        assert await self._keys(store, filter={"x": 1}) == []


@pytest.mark.unit
class TestVectorSearch:
    async def _seeded(self) -> ChromaStore:
        store = _store(index=True, fields=["text"])
        await store.abatch(
            [
                PutOp(namespace=("tools",), key="m", value={"text": "mail", "tier": "pro"}),
                PutOp(namespace=("tools",), key="c", value={"text": "calendar", "tier": "free"}),
                PutOp(namespace=("tools",), key="n", value={"text": "notes", "tier": "pro"}),
                PutOp(namespace=("other",), key="o", value={"text": "mail", "tier": "pro"}),
            ]
        )
        for doc_id, (embedding, metadata, document) in _collection(store).rows.items():
            metadata["created_at"] = STAMP
            metadata["updated_at"] = LATER
            _collection(store).rows[doc_id] = (embedding, metadata, document)
        return store

    async def test_the_nearest_items_come_first_with_their_scores(self) -> None:
        store = await self._seeded()

        (results,) = await store.abatch(
            [SearchOp(namespace_prefix=("tools",), query="mail", limit=2)]
        )

        assert [(r.key, r.namespace) for r in results] == [("m", ("tools",)), ("c", ("tools",))]
        assert [r.score for r in results] == [pytest.approx(1.0), pytest.approx(0.0)]
        assert results[0].value == {"text": "mail", "tier": "pro"}
        assert results[0].created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert results[0].updated_at == datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
        assert _collection(store).queries[-1] == {
            "n_results": 2,
            "include": ["metadatas", "distances", "documents"],
            "where": {"namespace": {"$eq": "tools"}},
        }

    async def test_the_offset_pages_past_the_nearest(self) -> None:
        store = await self._seeded()

        (results,) = await store.abatch(
            [SearchOp(namespace_prefix=("tools",), query="mail", limit=1, offset=1)]
        )

        assert [r.key for r in results] == ["c"]
        assert _collection(store).queries[-1]["n_results"] == 2

    async def test_a_filter_is_combined_with_the_namespace(self) -> None:
        store = await self._seeded()

        await store.abatch(
            [SearchOp(namespace_prefix=("tools",), query="mail", filter={"tier": "pro"})]
        )

        assert _collection(store).queries[-1]["where"] == {
            "$and": [{"namespace": {"$eq": "tools"}}, {"tier": "pro"}]
        }

    async def test_a_filter_alone_is_the_whole_where(self) -> None:
        store = await self._seeded()
        _collection(store).get = AsyncMock(
            return_value={
                "ids": ["tools::m"],
                "metadatas": None,
                "documents": [pickled_document({"tier": "pro"})],
            }
        )

        await store.abatch([SearchOp(namespace_prefix=(), query="mail", filter={"tier": "pro"})])

        assert _collection(store).queries[-1]["where"] == {"tier": "pro"}

    async def test_no_hits_is_an_empty_page(self) -> None:
        store = _store(index=True)
        _collection(store).add("tools::x", {}, {"t": "mail"})

        (results,) = await store.abatch([SearchOp(namespace_prefix=("tools",), query="mail")])

        assert results == []

    async def test_a_hit_without_a_document_reads_as_an_empty_value(self) -> None:
        store = _store(index=True)
        _collection(store).rows["tools::x"] = ([1.0, 0.0, 0.0], {"namespace": "tools"}, None)

        (results,) = await store.abatch([SearchOp(namespace_prefix=("tools",), query="mail")])

        assert [(r.key, r.value) for r in results] == [("x", {})]

    async def test_a_nested_namespace_and_no_filter_shape_the_where(self) -> None:
        store = _store(index=True)
        _collection(store).rows["a::b::x"] = ([1.0, 0.0, 0.0], {"namespace": "a::b"}, None)

        await store.abatch([SearchOp(namespace_prefix=("a", "b"), query="mail")])
        await store.abatch([SearchOp(namespace_prefix=(), query="mail")])

        assert [q["where"] for q in _collection(store).queries] == [
            {"namespace": {"$eq": "a::b"}},
            None,
        ]

    @pytest.mark.parametrize(
        "partial",
        [
            {"ids": []},
            {"metadatas": None},
            {"distances": None},
            {"documents": None},
        ],
        ids=["no-ids", "no-metadatas", "no-distances", "no-documents"],
    )
    async def test_a_partial_query_result_never_crashes_the_search(
        self, partial: dict[str, object]
    ) -> None:
        store = _store(index=True)
        _collection(store).add("tools::x", {"namespace": "tools"}, {"t": 1})
        result = {
            "ids": [["tools::x"]],
            "metadatas": [[{"namespace": "tools"}]],
            "distances": [[0.25]],
            "documents": [[pickled_document({"t": 1})]],
            **partial,
        }
        _collection(store).query = AsyncMock(return_value=result)

        (results,) = await store.abatch([SearchOp(namespace_prefix=("tools",), query="mail")])

        if "documents" in partial:
            assert [(r.key, r.value, r.score) for r in results] == [("x", {}, 0.75)]
        else:
            assert results == []

    async def test_a_failed_query_fails_the_search(self) -> None:
        store = await self._seeded()
        _collection(store).query = AsyncMock(side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.log") as log, pytest.raises(ConnectionError):
            await store.abatch([SearchOp(namespace_prefix=("tools",), query="mail")])

        log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error in vector search", error_type="ConnectionError"
        )

    async def test_a_query_without_embeddings_pages_the_filtered_rows(self) -> None:
        store = _store()
        _seed(store)

        (results,) = await store.abatch(
            [SearchOp(namespace_prefix=("tools",), query="mail", filter={"kind": "calendar"})]
        )

        assert [r.key for r in results] == ["b"]
        assert results[0].score is None


@pytest.mark.unit
class TestListNamespaces:
    async def test_namespaces_are_matched_truncated_sorted_and_paged(self) -> None:
        store = _store()
        for doc_id in ("a::x::k1", "a::y::k2", "b::x::k3", "a::x::k4"):
            _collection(store).add(doc_id, {}, {"v": 1})

        (all_ns,) = await store.abatch([ListNamespacesOp(match_conditions=None, max_depth=None)])
        (prefixed,) = await store.abatch(
            [ListNamespacesOp(match_conditions=(MatchCondition("prefix", ("a", "*")),))]
        )
        (shallow,) = await store.abatch([ListNamespacesOp(max_depth=1, limit=1, offset=1)])

        assert all_ns == [("a", "x"), ("a", "y"), ("b", "x")]
        assert prefixed == [("a", "x"), ("a", "y")]
        assert shallow == [("b",)]
        assert _collection(store).gets[0] == {"ids": None, "include": ["metadatas"]}

    async def test_an_empty_collection_has_no_namespaces(self) -> None:
        assert await _store().abatch([ListNamespacesOp()]) == [[]]

    async def test_a_failed_listing_is_logged_and_reads_as_empty(self) -> None:
        store = _store()
        _collection(store).get = AsyncMock(side_effect=ConnectionError("down"))

        with patch(f"{MODULE}.log") as log:
            assert await store.abatch([ListNamespacesOp()]) == [[]]

        log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error listing namespaces", error="down", error_type="ConnectionError"
        )


@pytest.mark.unit
class TestBatch:
    async def test_results_come_back_in_op_order(self) -> None:
        store = _store()
        _collection(store).add("n::k", {}, {"x": 1})

        get, listed, put = await store.abatch(
            [
                GetOp(namespace=("n",), key="k"),
                ListNamespacesOp(),
                PutOp(namespace=("n",), key="new", value={"y": 2}),
            ]
        )

        assert get.value == {"x": 1}
        assert listed == [("n",)]
        assert put is None

    async def test_an_unknown_op_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown operation type"):
            await _store().abatch([object()])
