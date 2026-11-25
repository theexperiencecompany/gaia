"""ChromaStore.asearch on namespaces LangGraph's BaseStore would refuse.

An MCP server's tools are stored under its address (mcp.example.com/mcp), and
BaseStore.asearch rejects any label holding a period before the store sees it.
"""

from typing import cast

from chromadb.api import AsyncClientAPI
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.store.base import IndexConfig, PutOp
import pytest

from app.db.chroma.chroma_store import ChromaStore
from tests._harness.chroma_fakes import FakeChromaClient, FakeChromaCollection

MCP_NAMESPACE = ("mcp.example.com/mcp",)
EMBEDDING_DIMS = 8


def _store(collection: FakeChromaCollection, *, index: IndexConfig | None = None) -> ChromaStore:
    client = cast(AsyncClientAPI, FakeChromaClient(collection))
    return ChromaStore(client=client, collection_name="c", index=index)


@pytest.mark.unit
class TestAsearch:
    @pytest.mark.regression
    async def test_a_namespace_named_after_a_server_address_is_searchable(self) -> None:
        """Regression: tool search failed for every custom MCP, whose namespace is its dotted host."""
        collection = FakeChromaCollection()
        collection.add("mcp.example.com/mcp::whoop_sleep", {}, {"kind": "tool"})

        results = await _store(collection).asearch(MCP_NAMESPACE)

        assert [item.key for item in results] == ["whoop_sleep"]

    async def test_it_filters_and_pages(self) -> None:
        collection = FakeChromaCollection()
        collection.add("mcp.example.com/mcp::a", {}, {"kind": "mail"})
        collection.add("mcp.example.com/mcp::b", {}, {"kind": "calendar"})
        collection.add("mcp.example.com/mcp::c", {}, {"kind": "mail"})
        store = _store(collection)

        mail = await store.asearch(MCP_NAMESPACE, filter={"kind": "mail"})
        second = await store.asearch(MCP_NAMESPACE, limit=1, offset=1)

        assert [item.key for item in mail] == ["a", "c"]
        assert [item.key for item in second] == ["b"]

    async def test_it_returns_ten_items_unless_told_otherwise(self) -> None:
        collection = FakeChromaCollection()
        for n in range(11):
            collection.add(f"mcp.example.com/mcp::t{n:02}", {}, {"n": n})

        assert len(await _store(collection).asearch(MCP_NAMESPACE)) == 10

    async def test_it_ranks_by_the_query(self) -> None:
        index = IndexConfig(
            embed=DeterministicFakeEmbedding(size=EMBEDDING_DIMS),
            dims=EMBEDDING_DIMS,
            fields=["text"],
        )
        store = _store(FakeChromaCollection(), index=index)
        await store.abatch(
            [
                PutOp(namespace=MCP_NAMESPACE, key="sleep", value={"text": "sleep score"}),
                PutOp(namespace=MCP_NAMESPACE, key="strain", value={"text": "day strain"}),
            ]
        )

        results = await store.asearch(MCP_NAMESPACE, query="day strain", limit=1)

        assert [item.key for item in results] == ["strain"]
