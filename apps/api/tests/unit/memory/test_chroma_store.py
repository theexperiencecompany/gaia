"""Unit tests for app.memory.chroma_store — the memory vector-store layer.

The only external seams are ``ChromaClient.get_client`` and the
``AsyncCollection`` objects it returns; both are mocked. Everything in
``chroma_store`` itself — collection caching, the create/get/fallback
decision, result clamping, metadata merging, and every query/upsert/delete
argument — runs for real.

Collections are cached per event loop, so the module-level loop state is
cleared before and after every test.
"""

import asyncio
from collections.abc import Iterator
from datetime import date as date_type
import threading
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.memory import (
    CHROMA_CONVERSATION_CHUNKS_COLLECTION,
    CHROMA_MEMORIES_COLLECTION,
    CHROMA_MEMORY_EPISODES_COLLECTION,
)
from app.db.chroma.chromadb import ChromaClient
from app.db.chroma.noop_embedding import NoOpEmbeddingFunction
from app.memory import chroma_store
from app.memory.chroma_store import (
    ConversationChunkItem,
    EpisodeVectorItem,
    MemoryVectorItem,
)

USER_ID = "user-1"
MID = "mem-1"


class ChromaEnv(NamedTuple):
    client: AsyncMock
    collections: dict[str, AsyncMock]


@pytest.fixture(autouse=True)
def _clear_loop_state() -> Iterator[None]:
    chroma_store._loop_collections.clear()
    chroma_store._loop_locks.clear()
    yield
    chroma_store._loop_collections.clear()
    chroma_store._loop_locks.clear()


@pytest.fixture
def chroma() -> ChromaEnv:
    collections: dict[str, AsyncMock] = {}
    client = AsyncMock()
    client.list_collections.return_value = []

    def _create(**kwargs: Any) -> AsyncMock:
        name = kwargs["name"]
        collection = AsyncMock()
        collection.count.return_value = 0
        collections[name] = collection
        return collection

    client.create_collection.side_effect = _create
    with patch.object(ChromaClient, "get_client", new=AsyncMock(return_value=client)):
        yield ChromaEnv(client, collections)


async def _primed_collection(name: str, chroma: ChromaEnv) -> AsyncMock:
    """Run the real cache-miss path once so later calls hit the cache."""
    collection = await chroma_store._get_collection(name)
    assert chroma.collections[name] is collection
    return collection


def _memory_item(
    id: str, embedding: list[float], document: str, *, is_latest: bool = True
) -> MemoryVectorItem:
    return {
        "id": id,
        "embedding": embedding,
        "document": document,
        "metadata": {
            "user_id": USER_ID,
            "kind": "fact",
            "category_path": "general",
            "is_latest": is_latest,
            "is_forgotten": False,
        },
    }


# ---------------------------------------------------------------------------
# Module-level helpers


async def test_loop_state_same_loop_returns_same_state() -> None:
    first = chroma_store._loop_state()
    second = chroma_store._loop_state()
    assert first[0] is second[0]
    assert first[1] is second[1]


async def test_loop_state_isolated_across_loops() -> None:
    async def probe() -> tuple[dict[str, Any], asyncio.Lock]:
        return chroma_store._loop_state()

    outer = chroma_store._loop_state()
    results: list[tuple[dict[str, Any], asyncio.Lock]] = []

    def _run_in_fresh_loop() -> None:
        inner_loop = asyncio.new_event_loop()
        try:
            results.append(inner_loop.run_until_complete(probe()))
        finally:
            inner_loop.close()

    thread = threading.Thread(target=_run_in_fresh_loop)
    thread.start()
    thread.join()
    inner = results[0]

    assert inner[0] is not outer[0]
    assert inner[1] is not outer[1]
    again = chroma_store._loop_state()
    assert again[0] is outer[0]
    assert again[1] is outer[1]


def test_as_metadata_returns_plain_dict_copy() -> None:
    source: dict[str, object] = {"user_id": USER_ID, "is_latest": True}
    result = chroma_store._as_metadata(source)
    assert result == source
    assert result is not source


# ---------------------------------------------------------------------------
# _get_collection


async def test_get_collection_creates_when_missing(chroma: ChromaEnv) -> None:
    collection = await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)

    create_call = chroma.client.create_collection.await_args
    assert create_call is not None
    assert create_call.kwargs["name"] == CHROMA_MEMORIES_COLLECTION
    assert create_call.kwargs["metadata"] == {"hnsw:space": "cosine"}
    assert isinstance(create_call.kwargs["embedding_function"], NoOpEmbeddingFunction)
    chroma.client.get_collection.assert_not_awaited()
    assert chroma.collections[CHROMA_MEMORIES_COLLECTION] is collection


async def test_get_collection_caches_after_create(chroma: ChromaEnv) -> None:
    first = await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)
    second = await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)

    assert first is second
    assert chroma.client.list_collections.await_count == 1
    assert chroma.client.create_collection.await_count == 1
    chroma.client.get_collection.assert_not_awaited()


async def test_get_collection_gets_when_exists(chroma: ChromaEnv) -> None:
    existing = AsyncMock()
    chroma.client.list_collections.return_value = [SimpleNamespace(name=CHROMA_MEMORIES_COLLECTION)]
    chroma.client.get_collection.return_value = existing

    collection = await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)

    assert collection is existing
    get_call = chroma.client.get_collection.await_args
    assert get_call is not None
    assert get_call.kwargs["name"] == CHROMA_MEMORIES_COLLECTION
    assert isinstance(get_call.kwargs["embedding_function"], NoOpEmbeddingFunction)
    chroma.client.create_collection.assert_not_awaited()


async def test_get_collection_falls_back_when_embedding_function_rejected(
    chroma: ChromaEnv,
) -> None:
    existing = AsyncMock()
    chroma.client.list_collections.return_value = [SimpleNamespace(name=CHROMA_MEMORIES_COLLECTION)]
    chroma.client.get_collection.side_effect = [ValueError("new ef rejected"), existing]

    collection = await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)

    assert collection is existing
    assert chroma.client.get_collection.await_count == 2
    fallback_call = chroma.client.get_collection.await_args
    assert fallback_call is not None
    assert fallback_call.kwargs == {"name": CHROMA_MEMORIES_COLLECTION}


async def test_get_collection_propagates_non_valueerror(chroma: ChromaEnv) -> None:
    chroma.client.list_collections.return_value = [SimpleNamespace(name=CHROMA_MEMORIES_COLLECTION)]
    chroma.client.get_collection.side_effect = RuntimeError("chroma down")

    with pytest.raises(RuntimeError, match="chroma down"):
        await chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION)


async def test_get_collection_creates_once_under_concurrency(chroma: ChromaEnv) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_list_collections() -> list[Any]:
        entered.set()
        await release.wait()
        return []

    chroma.client.list_collections.side_effect = slow_list_collections

    tasks = [
        asyncio.create_task(chroma_store._get_collection(CHROMA_MEMORIES_COLLECTION))
        for _ in range(2)
    ]
    await entered.wait()
    release.set()
    first, second = await asyncio.gather(*tasks)

    assert first is second
    assert chroma.client.create_collection.await_count == 1


# ---------------------------------------------------------------------------
# _clamp_n_results


async def test_clamp_n_results_returns_min(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.count.return_value = 5

    assert await chroma_store._clamp_n_results(collection, 3) == 3
    assert await chroma_store._clamp_n_results(collection, 10) == 5
    collection.count.return_value = 7
    assert await chroma_store._clamp_n_results(collection, 9) == 7
    assert await chroma_store._clamp_n_results(collection, 5) == 5
    assert collection.count.await_count == 4


# ---------------------------------------------------------------------------
# upsert_memories


async def test_upsert_memories_empty_is_noop(chroma: ChromaEnv) -> None:
    await chroma_store.upsert_memories([])

    chroma.client.list_collections.assert_not_awaited()


async def test_upsert_memories_exact_args(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    items = [
        _memory_item("m1", [0.1, 0.2], "first fact"),
        _memory_item("m2", [0.3, 0.4], "second fact", is_latest=False),
    ]

    await chroma_store.upsert_memories(items)

    collection.upsert.assert_awaited_once_with(
        ids=["m1", "m2"],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
        documents=["first fact", "second fact"],
        metadatas=[
            {
                "user_id": USER_ID,
                "kind": "fact",
                "category_path": "general",
                "is_latest": True,
                "is_forgotten": False,
            },
            {
                "user_id": USER_ID,
                "kind": "fact",
                "category_path": "general",
                "is_latest": False,
                "is_forgotten": False,
            },
        ],
    )


# ---------------------------------------------------------------------------
# query_similar


async def test_query_similar_empty_collection_returns_no_results(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)

    result = await chroma_store.query_similar(USER_ID, [0.1], 5)

    assert result == []
    collection.query.assert_not_awaited()


async def test_query_similar_exact_query_and_mapping(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.count.return_value = 5
    collection.query.return_value = {
        "ids": [["m1", "m2"]],
        "distances": [[0.1, 0.25]],
    }

    result = await chroma_store.query_similar(USER_ID, [0.9, 0.8], 3)

    assert result == [("m1", 0.9), ("m2", 0.75)]
    collection.query.assert_awaited_once_with(
        query_embeddings=[[0.9, 0.8]],
        n_results=3,
        where={
            "$and": [
                {"user_id": USER_ID},
                {"is_forgotten": False},
                {"is_latest": True},
            ]
        },
        include=["distances"],
    )


async def test_query_similar_without_latest_filter(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.count.return_value = 1
    collection.query.return_value = {"ids": [["m1"]], "distances": [[0.0]]}

    await chroma_store.query_similar(USER_ID, [0.1], 1, only_latest=False)

    collection.query.assert_awaited_once_with(
        query_embeddings=[[0.1]],
        n_results=1,
        where={"$and": [{"user_id": USER_ID}, {"is_forgotten": False}]},
        include=["distances"],
    )


async def test_query_similar_clamps_n_to_collection_count(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.count.return_value = 2
    collection.query.return_value = {"ids": [[]], "distances": [[]]}

    await chroma_store.query_similar(USER_ID, [0.1], 10)

    assert collection.query.await_args is not None
    assert collection.query.await_args.kwargs["n_results"] == 2


async def test_query_similar_missing_distances_returns_no_results(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.count.return_value = 2
    collection.query.return_value = {"ids": [["m1", "m2"]]}

    result = await chroma_store.query_similar(USER_ID, [0.1], 2)

    assert result == []


# ---------------------------------------------------------------------------
# set_memory_flags


async def test_set_memory_flags_noop_when_no_flags(chroma: ChromaEnv) -> None:
    await chroma_store.set_memory_flags(MID)

    chroma.client.list_collections.assert_not_awaited()


async def test_set_memory_flags_noop_when_vector_missing(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.get.return_value = {"ids": [], "metadatas": []}

    await chroma_store.set_memory_flags(MID, is_latest=False)

    collection.update.assert_not_awaited()


async def test_set_memory_flags_noop_when_metadatas_missing(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.get.return_value = {"ids": [MID], "metadatas": None}

    await chroma_store.set_memory_flags(MID, is_latest=False)

    collection.update.assert_not_awaited()


async def test_set_memory_flags_updates_only_latest(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    existing_metadata = {
        "user_id": USER_ID,
        "is_latest": True,
        "is_forgotten": False,
    }
    collection.get.return_value = {"ids": [MID], "metadatas": [existing_metadata]}

    await chroma_store.set_memory_flags(MID, is_latest=False)

    collection.get.assert_awaited_once_with(ids=[MID], include=["metadatas"])
    collection.update.assert_awaited_once_with(
        ids=[MID],
        metadatas=[
            {
                "user_id": USER_ID,
                "is_latest": False,
                "is_forgotten": False,
            }
        ],
    )
    assert existing_metadata["is_latest"] is True


async def test_set_memory_flags_updates_only_forgotten(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.get.return_value = {
        "ids": [MID],
        "metadatas": [{"user_id": USER_ID, "is_latest": True, "is_forgotten": False}],
    }

    await chroma_store.set_memory_flags(MID, is_forgotten=True)

    collection.update.assert_awaited_once_with(
        ids=[MID],
        metadatas=[{"user_id": USER_ID, "is_latest": True, "is_forgotten": True}],
    )


async def test_set_memory_flags_updates_both(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)
    collection.get.return_value = {
        "ids": [MID],
        "metadatas": [{"user_id": USER_ID, "is_latest": True, "is_forgotten": False}],
    }

    await chroma_store.set_memory_flags(MID, is_latest=False, is_forgotten=True)

    collection.update.assert_awaited_once_with(
        ids=[MID],
        metadatas=[{"user_id": USER_ID, "is_latest": False, "is_forgotten": True}],
    )


# ---------------------------------------------------------------------------
# delete_ids


async def test_delete_ids_empty_is_noop(chroma: ChromaEnv) -> None:
    await chroma_store.delete_ids([])

    chroma.client.list_collections.assert_not_awaited()


async def test_delete_ids_exact(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORIES_COLLECTION, chroma)

    await chroma_store.delete_ids(["m1", "m2"])

    collection.delete.assert_awaited_once_with(ids=["m1", "m2"])


# ---------------------------------------------------------------------------
# delete_user


async def test_delete_user_wipes_every_collection(chroma: ChromaEnv) -> None:
    await chroma_store.delete_user(USER_ID)

    assert set(chroma.collections) == {
        CHROMA_MEMORIES_COLLECTION,
        CHROMA_MEMORY_EPISODES_COLLECTION,
        CHROMA_CONVERSATION_CHUNKS_COLLECTION,
    }
    for collection in chroma.collections.values():
        collection.delete.assert_awaited_once_with(where={"user_id": USER_ID})


# ---------------------------------------------------------------------------
# upsert_conversation_chunks


async def test_upsert_conversation_chunks_empty_is_noop(chroma: ChromaEnv) -> None:
    await chroma_store.upsert_conversation_chunks([])

    chroma.client.list_collections.assert_not_awaited()


async def test_upsert_conversation_chunks_exact_args(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)
    items: list[ConversationChunkItem] = [
        {
            "id": "c1",
            "embedding": [0.5],
            "document": "verbatim turn",
            "metadata": {"user_id": USER_ID, "date": "2026-01-01"},
        }
    ]

    await chroma_store.upsert_conversation_chunks(items)

    collection.upsert.assert_awaited_once_with(
        ids=["c1"],
        embeddings=[[0.5]],
        documents=["verbatim turn"],
        metadatas=[{"user_id": USER_ID, "date": "2026-01-01"}],
    )


# ---------------------------------------------------------------------------
# query_conversation_chunks


async def test_query_conversation_chunks_empty_collection_returns_no_results(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)

    result = await chroma_store.query_conversation_chunks(USER_ID, [0.1], 5)

    assert result == []
    collection.query.assert_not_awaited()


async def test_query_conversation_chunks_exact_query_and_mapping(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)
    collection.count.return_value = 3
    collection.query.return_value = {
        "ids": [["c1", "c2"]],
        "documents": [["hello", "world"]],
        "metadatas": [[{"date": "2026-01-01"}, {"date": "2026-01-02"}]],
        "distances": [[0.2, 0.5]],
    }

    result = await chroma_store.query_conversation_chunks(USER_ID, [0.1], 2)

    assert result == [
        ("2026-01-01", "hello", 0.8),
        ("2026-01-02", "world", 0.5),
    ]
    collection.query.assert_awaited_once_with(
        query_embeddings=[[0.1]],
        n_results=2,
        where={"user_id": USER_ID},
        include=["documents", "metadatas", "distances"],
    )


async def test_query_conversation_chunks_coerces_date_to_iso_string(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)
    collection.count.return_value = 1
    collection.query.return_value = {
        "ids": [["c1"]],
        "documents": [["chunk"]],
        "metadatas": [[{"date": date_type(2026, 1, 3)}]],
        "distances": [[0.0]],
    }

    result = await chroma_store.query_conversation_chunks(USER_ID, [0.1], 1)

    assert result == [("2026-01-03", "chunk", 1.0)]


async def test_query_conversation_chunks_missing_date_defaults_empty(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)
    collection.count.return_value = 1
    collection.query.return_value = {
        "ids": [["c1"]],
        "documents": [["chunk"]],
        "metadatas": [[{}]],
        "distances": [[0.1]],
    }

    result = await chroma_store.query_conversation_chunks(USER_ID, [0.1], 1)

    assert result == [("", "chunk", 0.9)]


async def test_query_conversation_chunks_missing_sections_returns_no_results(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION, chroma)
    collection.count.return_value = 1
    collection.query.return_value = {"ids": [["c1"]]}

    result = await chroma_store.query_conversation_chunks(USER_ID, [0.1], 1)

    assert result == []


# ---------------------------------------------------------------------------
# upsert_episode


async def test_upsert_episode_exact_args(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORY_EPISODES_COLLECTION, chroma)
    item: EpisodeVectorItem = {
        "id": "e1",
        "embedding": [0.7],
        "document": "daily summary",
        "metadata": {"user_id": USER_ID, "date": "2026-01-01"},
    }

    await chroma_store.upsert_episode(item)

    collection.upsert.assert_awaited_once_with(
        ids=["e1"],
        embeddings=[[0.7]],
        documents=["daily summary"],
        metadatas=[{"user_id": USER_ID, "date": "2026-01-01"}],
    )


# ---------------------------------------------------------------------------
# query_episodes


async def test_query_episodes_empty_collection_returns_no_results(
    chroma: ChromaEnv,
) -> None:
    collection = await _primed_collection(CHROMA_MEMORY_EPISODES_COLLECTION, chroma)

    result = await chroma_store.query_episodes(USER_ID, [0.1], 5)

    assert result == []
    collection.query.assert_not_awaited()


async def test_query_episodes_exact_query_and_mapping(chroma: ChromaEnv) -> None:
    collection = await _primed_collection(CHROMA_MEMORY_EPISODES_COLLECTION, chroma)
    collection.count.return_value = 4
    collection.query.return_value = {
        "ids": [["e1", "e2"]],
        "distances": [[0.4, 0.25]],
    }

    result = await chroma_store.query_episodes(USER_ID, [0.1], 2)

    assert result == [("e1", 0.6), ("e2", 0.75)]
    collection.query.assert_awaited_once_with(
        query_embeddings=[[0.1]],
        n_results=2,
        where={"user_id": USER_ID},
        include=["distances"],
    )
