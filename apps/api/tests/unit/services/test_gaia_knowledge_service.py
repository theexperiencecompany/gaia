"""Unit tests for gaia_knowledge_service (GAIA self-knowledge in ChromaDB).

Search serves from an in-memory snapshot of a corpus production never writes, so
these tests cover the local cosine ranking, the snapshot lifecycle (load, TTL,
failed refresh, invalidation), and the loading seams — from the vector math up.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from pydantic import ValidationError
import pytest

from app.constants.chroma import GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS
from app.services import gaia_knowledge_service as mod
from app.services.gaia_knowledge_service import (
    GaiaKnowledgeService,
    KnowledgeItem,
    _dot,
    _load_lock,
    _normalized,
    _Snapshot,
    gaia_knowledge_service,
)
from tests.helpers import captured_wide_event

_MOD = "app.services.gaia_knowledge_service"

#: A timestamp no uptime can make look fresh (expiry is `monotonic() - loaded <
#: TTL`, and monotonic() is system uptime, so `0.0` would read as fresh on a host
#: up less than the TTL).
_LONG_AGO = -1e9


@pytest.fixture
def chroma():
    """The raw Chroma client + the langchain client ``add_knowledge_batch`` uses."""
    collection = MagicMock()
    collection.get = AsyncMock(return_value={"documents": [], "metadatas": []})
    client = MagicMock()
    client.get_or_create_collection = AsyncMock(return_value=collection)
    client.delete_collection = AsyncMock()
    client.create_collection = AsyncMock()
    langchain = MagicMock()
    langchain.aadd_texts = AsyncMock()
    with patch(f"{_MOD}.ChromaClient") as m_cls:
        m_cls.get_client = AsyncMock(return_value=client)
        m_cls.get_langchain_client = AsyncMock(return_value=langchain)
        yield SimpleNamespace(collection=collection, client=client, langchain=langchain)


@pytest.fixture
def embeddings():
    """The google_embeddings provider, returning whatever the test declares."""
    fake = SimpleNamespace(
        aembed_documents=AsyncMock(return_value=[]),
        aembed_query=AsyncMock(return_value=[1.0, 0.0]),
    )
    with patch(f"{_MOD}.providers") as providers:
        providers.aget = aget = AsyncMock(return_value=fake)
        yield SimpleNamespace(
            aget=aget,
            aembed_documents=fake.aembed_documents,
            aembed_query=fake.aembed_query,
        )


@pytest.fixture(autouse=True)
def clean_snapshot():
    """The service is a process singleton — never let a snapshot cross tests."""
    service = gaia_knowledge_service
    saved = (service._snapshot, service._loaded_at)
    service._snapshot = None
    service._loaded_at = _LONG_AGO
    yield
    service._snapshot, service._loaded_at = saved


def _corpus(
    chroma: SimpleNamespace,
    embeddings: SimpleNamespace,
    documents: list[str],
    doc_vectors: list[list[float]],
    *,
    query_vector: list[float] | None = None,
) -> None:
    """Declare the collection's documents and the vectors the embedder returns."""
    chroma.collection.get.return_value = {
        "documents": documents,
        "metadatas": [{"i": i} for i in range(len(documents))],
    }
    embeddings.aembed_documents.return_value = doc_vectors
    embeddings.aembed_query.return_value = query_vector or [1.0, 0.0]


class TestVectorMath:
    def test_normalized_scales_to_unit_length(self):
        assert _normalized([3.0, 4.0]) == (0.6, 0.8)

    def test_normalized_scales_a_short_vector_up(self):
        """A vector shorter than unit length must still be scaled up — the guard
        is "is this the zero vector", not "is this already small"."""
        assert _normalized([0.3, 0.4]) == (0.6, 0.8)

    def test_normalized_keeps_the_zero_vector(self):
        assert _normalized([0.0, 0.0]) == (0.0, 0.0)

    def test_dot_is_the_sum_of_component_products(self):
        assert _dot([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == 32.0

    def test_dot_of_orthogonal_vectors_is_zero(self):
        assert _dot([1.0, 0.0], [0.0, 1.0]) == 0.0


class TestLoadLock:
    def test_the_same_loop_reuses_its_lock(self):
        locks: list[asyncio.Lock] = []

        async def _grab() -> None:
            locks.append(_load_lock())
            locks.append(_load_lock())

        asyncio.run(_grab())

        assert isinstance(locks[0], asyncio.Lock)
        assert locks[0] is locks[1]

    def test_a_new_loop_gets_a_new_lock(self):
        """A short-lived loop's id is reused by the next one — keying on the id
        hands the second loop a lock bound to the dead first loop."""
        locks: list[asyncio.Lock] = []

        async def _grab() -> None:
            locks.append(_load_lock())

        asyncio.run(_grab())
        asyncio.run(_grab())

        assert locks[0] is not locks[1]


class TestInitialState:
    def test_a_new_service_starts_with_no_snapshot(self):
        service = GaiaKnowledgeService()

        assert service.collection_name == "gaia_knowledge"
        assert service._snapshot is None
        assert service._loaded_at == 0.0


class TestInvalidate:
    def test_invalidate_drops_the_snapshot_and_resets_the_clock(self):
        service = GaiaKnowledgeService()
        service._snapshot = MagicMock()
        service._loaded_at = 123.0

        service._invalidate()

        assert service._snapshot is None
        assert service._loaded_at == 0.0


class TestFreshness:
    def test_fresh_within_the_ttl(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mod, "monotonic", lambda: 1_000.0)
        service = GaiaKnowledgeService()
        service._snapshot = MagicMock()
        service._loaded_at = 1_000.0 - GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS / 2

        assert service._fresh() is True

    def test_not_fresh_at_exactly_the_ttl_boundary(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mod, "monotonic", lambda: 1_000.0)
        service = GaiaKnowledgeService()
        service._snapshot = MagicMock()
        service._loaded_at = 1_000.0 - GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS

        assert service._fresh() is False

    def test_not_fresh_without_a_snapshot(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(mod, "monotonic", lambda: 1_000.0)
        service = GaiaKnowledgeService()
        service._snapshot = None
        service._loaded_at = 1_000.0

        assert service._fresh() is False


class TestKnowledgeItemValidation:
    def test_accepts_non_empty_content(self):
        item = KnowledgeItem(content="GAIA can send emails")

        assert item.content == "GAIA can send emails"

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            KnowledgeItem(content="")

    def test_rejects_whitespace_only_content(self):
        with pytest.raises(ValidationError):
            KnowledgeItem(content="   \n\t  ")

    def test_strips_whitespace(self):
        item = KnowledgeItem(content="  padded  ")

        assert item.content == "padded"


class TestSearchKnowledge:
    async def test_ranks_by_local_cosine_similarity(self, chroma, embeddings):
        """Query [1,0] against an aligned doc ([1,0]) and an orthogonal one
        ([0,1]) — nearest first, cosine distance (1 - similarity) as the score."""
        _corpus(
            chroma,
            embeddings,
            ["Doc aligned", "Doc orthogonal"],
            [[1.0, 0.0], [0.0, 1.0]],
        )

        results = await gaia_knowledge_service.search_knowledge("q", limit=2)

        assert [r.content for r in results] == ["Doc aligned", "Doc orthogonal"]
        assert results[0].relevance_score == pytest.approx(0.0)
        assert results[0].metadata == {"i": 0}
        assert results[1].relevance_score == pytest.approx(1.0)
        assert results[1].metadata == {"i": 1}

    async def test_limit_caps_the_results(self, chroma, embeddings):
        _corpus(
            chroma,
            embeddings,
            ["a", "b", "c"],
            [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]],
        )

        results = await gaia_knowledge_service.search_knowledge("q", limit=2)

        assert [r.content for r in results] == ["a", "b"]

    async def test_the_load_reads_this_collections_documents(self, chroma, embeddings):
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])

        await gaia_knowledge_service.search_knowledge("q")

        chroma.client.get_or_create_collection.assert_awaited_once_with(name="gaia_knowledge")
        chroma.collection.get.assert_awaited_once_with(include=["documents", "metadatas"])

    async def test_it_embeds_the_query_and_the_corpus_via_google_embeddings(
        self, chroma, embeddings
    ):
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])

        await gaia_knowledge_service.search_knowledge("what can you do?")

        assert embeddings.aget.await_args_list == [
            call("google_embeddings"),
            call("google_embeddings"),
        ]
        embeddings.aembed_query.assert_awaited_once_with("what can you do?")

    async def test_blank_documents_are_skipped(self, chroma, embeddings):
        chroma.collection.get.return_value = {
            "documents": ["", "Doc"],
            "metadatas": [{}, {"i": 1}],
        }
        embeddings.aembed_documents.return_value = [[1.0, 0.0], [0.0, 1.0]]

        results = await gaia_knowledge_service.search_knowledge("q", limit=5)

        assert [r.content for r in results] == ["Doc"]
        assert results[0].metadata == {"i": 1}

    async def test_a_second_search_reuses_the_snapshot(self, chroma, embeddings):
        """The point of the snapshot: the per-turn cost is the query embedding
        alone — no Chroma read, no re-embedding of the corpus."""
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])

        first = await gaia_knowledge_service.search_knowledge("q", limit=5)
        second = await gaia_knowledge_service.search_knowledge("q", limit=5)

        assert first == second
        assert chroma.collection.get.await_count == 1
        assert embeddings.aembed_documents.await_count == 1
        assert embeddings.aembed_query.await_count == 2

    async def test_an_expired_snapshot_reloads(self, chroma, embeddings):
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])

        await gaia_knowledge_service.search_knowledge("q")
        gaia_knowledge_service._loaded_at = _LONG_AGO
        await gaia_knowledge_service.search_knowledge("q")

        assert chroma.collection.get.await_count == 2

    async def test_a_failed_refresh_serves_the_previous_snapshot(self, chroma, embeddings):
        """A corpus for a section is enrichment: a refresh blip must degrade to
        the last good snapshot, not to an empty knowledge block — and the blip
        must keep serving it on later turns, not just the failing one."""
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])
        first = await gaia_knowledge_service.search_knowledge("q")

        chroma.collection.get.side_effect = RuntimeError("chroma down")
        gaia_knowledge_service._loaded_at = _LONG_AGO
        async with captured_wide_event() as event:
            second = await gaia_knowledge_service.search_knowledge("q")
        third = await gaia_knowledge_service.search_knowledge("q")

        assert second == first
        assert third == first
        (warning,) = event["warnings"]
        assert warning["msg"] == (
            "gaia_knowledge snapshot refresh failed; serving the previous corpus"
        )
        assert warning["error"] == "chroma down"
        assert warning["error_type"] == "RuntimeError"

    async def test_an_empty_corpus_yields_no_results(self, chroma, embeddings):
        _corpus(chroma, embeddings, [], [])

        assert await gaia_knowledge_service.search_knowledge("anything") == []
        # No corpus means no ranking, so the query is never embedded.
        embeddings.aembed_query.assert_not_awaited()

    async def test_a_first_load_failure_degrades_to_empty(self, chroma, embeddings):
        chroma.collection.get.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.search_knowledge("anything") == []


class TestLoadSnapshot:
    async def test_an_empty_collection_yields_an_empty_snapshot(self, chroma, embeddings):
        chroma.collection.get.return_value = {"documents": [], "metadatas": []}

        snapshot = await gaia_knowledge_service._load_snapshot()

        assert snapshot == _Snapshot(docs=(), unit_vectors=())

    async def test_it_embeds_every_document(self, chroma, embeddings):
        _corpus(chroma, embeddings, ["a", "b"], [[1.0, 0.0], [0.0, 1.0]])

        await gaia_knowledge_service._load_snapshot()

        embeddings.aembed_documents.assert_awaited_once_with(["a", "b"])

    async def test_a_document_without_a_metadata_row_gets_empty_metadata(self, chroma, embeddings):
        """``metadatas`` can be shorter than ``documents``; the guard must not read
        one row past the end."""
        chroma.collection.get.return_value = {"documents": ["a", "b"], "metadatas": [{"i": 0}]}
        embeddings.aembed_documents.return_value = [[1.0, 0.0], [0.0, 1.0]]

        results = await gaia_knowledge_service.search_knowledge("q", limit=5)

        assert [(r.content, r.metadata) for r in results] == [("a", {"i": 0}), ("b", {})]


class TestSnapshotInvalidation:
    """The writers are the only way the corpus changes; each must drop the
    snapshot so the next search reflects it rather than serving an hour stale."""

    async def test_add_knowledge_batch_invalidates(self, chroma, embeddings):
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])
        await gaia_knowledge_service.search_knowledge("q")

        await gaia_knowledge_service.add_knowledge_batch([KnowledgeItem(content="New")])
        await gaia_knowledge_service.search_knowledge("q")

        assert chroma.collection.get.await_count == 2

    async def test_clear_knowledge_invalidates(self, chroma, embeddings):
        _corpus(chroma, embeddings, ["Doc"], [[1.0, 0.0]])
        await gaia_knowledge_service.search_knowledge("q")

        await gaia_knowledge_service.clear_knowledge()
        await gaia_knowledge_service.search_knowledge("q")

        assert chroma.collection.get.await_count == 2


class TestAddKnowledgeBatch:
    async def test_empty_batch_returns_zero_without_touching_chroma(self, chroma, embeddings):
        assert await gaia_knowledge_service.add_knowledge_batch([]) == 0
        chroma.langchain.aadd_texts.assert_not_awaited()

    async def test_adds_texts_and_metadatas(self, chroma, embeddings):
        items = [
            KnowledgeItem(content="A", metadata={"x": 1}),
            KnowledgeItem(content="B"),
        ]

        count = await gaia_knowledge_service.add_knowledge_batch(items)

        assert count == 2
        chroma.langchain.aadd_texts.assert_awaited_once()
        assert chroma.langchain.aadd_texts.await_args.kwargs["texts"] == ["A", "B"]
        assert chroma.langchain.aadd_texts.await_args.kwargs["metadatas"] == [{"x": 1}, {}]

    async def test_failure_degrades_to_zero(self, chroma, embeddings):
        chroma.langchain.aadd_texts.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.add_knowledge_batch([KnowledgeItem(content="A")]) == 0


class TestClearKnowledge:
    async def test_deletes_and_recreates_collection(self, chroma, embeddings):
        ok = await gaia_knowledge_service.clear_knowledge()

        assert ok is True
        chroma.client.delete_collection.assert_awaited_once_with(name="gaia_knowledge")
        chroma.client.create_collection.assert_awaited_once()
        assert chroma.client.create_collection.await_args.kwargs["name"] == "gaia_knowledge"
        assert chroma.client.create_collection.await_args.kwargs["metadata"] == {
            "hnsw:space": "cosine"
        }

    async def test_failure_degrades_to_false(self, chroma, embeddings):
        chroma.client.delete_collection.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.clear_knowledge() is False
