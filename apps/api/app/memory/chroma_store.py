"""ChromaDB vector store for the memory engine.

Owns the two memory collections (``gaia_memories`` for atomic facts,
``gaia_memory_episodes`` for daily-journal summaries). Embeddings are always
computed by ``app.memory.embeddings`` and passed explicitly — ChromaDB never
embeds anything itself.
"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, cast

from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.api.types import EmbeddingFunction, Metadata

from app.constants.memory import (
    CHROMA_CONVERSATION_CHUNKS_COLLECTION,
    CHROMA_MEMORIES_COLLECTION,
    CHROMA_MEMORY_EPISODES_COLLECTION,
    EMBEDDING_DIM,
)
from app.db.chroma.chromadb import ChromaClient


class _NoOpEmbeddingFunction(EmbeddingFunction):  # type: ignore[type-arg]
    """Prevents ChromaDB from loading its default ONNX model.

    Embeddings are always passed explicitly to upsert/query, so the
    collection-level embedding function is never used for real. Defined
    privately here (rather than imported) because the existing equivalent in
    ``app.db.chroma.chroma_store`` is module-private to the LangGraph store.
    """

    def __init__(self) -> None:
        pass

    def __call__(self, input: list[str]) -> Any:
        return [[0.0] * EMBEDDING_DIM for _ in input]


_NOOP_EF = _NoOpEmbeddingFunction()

# Collections are cached per event loop: an asyncio.Lock (and Chroma's async
# client) binds to the loop that first uses it, so sharing one cache/lock
# across loops raises "bound to a different event loop" in any context that
# runs multiple loops (test workers, scripts, background runners).
_loop_collections: dict[int, dict[str, AsyncCollection]] = {}
_loop_locks: dict[int, asyncio.Lock] = {}


def _loop_state() -> tuple[dict[str, AsyncCollection], asyncio.Lock]:
    """The collection cache + creation lock for the running event loop."""
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _loop_locks:
        _loop_locks[loop_id] = asyncio.Lock()
        _loop_collections[loop_id] = {}
    return _loop_collections[loop_id], _loop_locks[loop_id]


class MemoryVectorMetadata(TypedDict):
    """Metadata stored alongside each memory vector, used for filtering."""

    user_id: str
    kind: str
    category_path: str
    is_latest: bool
    is_forgotten: bool


class MemoryVectorItem(TypedDict):
    """One memory fact ready for vector upsert."""

    id: str
    embedding: list[float]
    document: str
    metadata: MemoryVectorMetadata


class EpisodeVectorMetadata(TypedDict):
    """Metadata stored alongside each episode-summary vector."""

    user_id: str
    date: str  # ISO date (YYYY-MM-DD)


class EpisodeVectorItem(TypedDict):
    """One daily-episode summary ready for vector upsert."""

    id: str
    embedding: list[float]
    document: str
    metadata: EpisodeVectorMetadata


class ConversationChunkMetadata(TypedDict):
    """Metadata stored alongside each raw conversation chunk vector."""

    user_id: str
    date: str  # ISO date (YYYY-MM-DD)


class ConversationChunkItem(TypedDict):
    """One verbatim conversation chunk ready for vector upsert."""

    id: str
    embedding: list[float]
    document: str
    metadata: ConversationChunkMetadata


def _as_metadata(metadata: Mapping[str, object]) -> Metadata:
    """Convert a metadata TypedDict to Chroma's Metadata mapping.

    The cast is safe — both TypedDicts only contain str/bool values — but
    mypy cannot prove it because TypedDict values widen to ``object``.
    """
    return cast(Metadata, dict(metadata))


async def _get_collection(name: str) -> AsyncCollection:
    """Get (and cache) a memory collection, creating it if missing."""
    _collections, _collections_lock = _loop_state()
    if name in _collections:
        return _collections[name]

    async with _collections_lock:
        if name in _collections:
            return _collections[name]

        client = await ChromaClient.get_client()
        existing = [collection.name for collection in await client.list_collections()]
        if name not in existing:
            collection = await client.create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=_NOOP_EF,
            )
        else:
            try:
                collection = await client.get_collection(name=name, embedding_function=_NOOP_EF)
            except ValueError:
                # ChromaDB 1.x rejects a new embedding function when one is
                # already persisted in the collection config; embeddings are
                # passed explicitly anyway, so plain get is safe.
                collection = await client.get_collection(name=name)

        _collections[name] = collection
        return collection


async def _clamp_n_results(collection: AsyncCollection, n: int) -> int:
    """Clamp a requested result count to what the collection actually holds.

    ChromaDB raises when ``n_results`` exceeds the number of stored vectors —
    the common case for a brand-new user whose collection has fewer than the
    requested candidate count. Clamping (and returning 0 for an empty
    collection) keeps recall and reconciliation working from the first turn.
    """
    count = await collection.count()
    return min(n, count)


async def ensure_collections() -> None:
    """Create the memory collections if they don't exist yet."""
    await _get_collection(CHROMA_MEMORIES_COLLECTION)
    await _get_collection(CHROMA_MEMORY_EPISODES_COLLECTION)
    await _get_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION)


async def upsert_memories(items: list[MemoryVectorItem]) -> None:
    """Upsert memory vectors with their filterable metadata."""
    if not items:
        return
    collection = await _get_collection(CHROMA_MEMORIES_COLLECTION)
    embeddings: list[Sequence[float] | Sequence[int]] = [item["embedding"] for item in items]
    await collection.upsert(
        ids=[item["id"] for item in items],
        embeddings=embeddings,
        documents=[item["document"] for item in items],
        metadatas=[_as_metadata(item["metadata"]) for item in items],
    )


async def query_similar(
    user_id: str,
    embedding: list[float],
    n: int,
    only_latest: bool = True,
) -> list[tuple[str, float]]:
    """Return up to ``n`` (memory_id, cosine_similarity) for a user, best first.

    Forgotten memories are always excluded; ``only_latest`` additionally
    restricts to the head of each supersession chain.
    """
    collection = await _get_collection(CHROMA_MEMORIES_COLLECTION)
    n_results = await _clamp_n_results(collection, n)
    if n_results == 0:
        return []

    conditions: list[dict[str, Any]] = [
        {"user_id": user_id},
        {"is_forgotten": False},
    ]
    if only_latest:
        conditions.append({"is_latest": True})

    query_embeddings: list[Sequence[float] | Sequence[int]] = [embedding]
    result = await collection.query(
        query_embeddings=query_embeddings,
        n_results=n_results,
        where={"$and": conditions},
        include=["distances"],
    )
    ids = result["ids"][0]
    distances = (result.get("distances") or [[]])[0]
    # Cosine distance -> similarity.
    return [(memory_id, 1.0 - distance) for memory_id, distance in zip(ids, distances)]


async def set_memory_flags(
    memory_id: str,
    *,
    is_latest: bool | None = None,
    is_forgotten: bool | None = None,
) -> None:
    """Update lineage/forgetting flags on a memory vector's metadata."""
    if is_latest is None and is_forgotten is None:
        return
    collection = await _get_collection(CHROMA_MEMORIES_COLLECTION)
    existing = await collection.get(ids=[memory_id], include=["metadatas"])
    metadatas = existing.get("metadatas") or []
    if not existing["ids"] or not metadatas:
        return

    metadata = dict(metadatas[0])
    if is_latest is not None:
        metadata["is_latest"] = is_latest
    if is_forgotten is not None:
        metadata["is_forgotten"] = is_forgotten
    await collection.update(ids=[memory_id], metadatas=[metadata])


async def delete_ids(ids: list[str]) -> None:
    """Hard-delete memory vectors by id."""
    if not ids:
        return
    collection = await _get_collection(CHROMA_MEMORIES_COLLECTION)
    await collection.delete(ids=ids)


async def delete_user(user_id: str) -> None:
    """Hard-delete all of a user's vectors from every collection (full wipe)."""
    for name in (
        CHROMA_MEMORIES_COLLECTION,
        CHROMA_MEMORY_EPISODES_COLLECTION,
        CHROMA_CONVERSATION_CHUNKS_COLLECTION,
    ):
        collection = await _get_collection(name)
        await collection.delete(where={"user_id": user_id})


async def upsert_conversation_chunks(items: list[ConversationChunkItem]) -> None:
    """Upsert raw conversation chunk vectors (verbatim retention tier)."""
    if not items:
        return
    collection = await _get_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION)
    embeddings: list[Sequence[float] | Sequence[int]] = [item["embedding"] for item in items]
    await collection.upsert(
        ids=[item["id"] for item in items],
        embeddings=embeddings,
        documents=[item["document"] for item in items],
        metadatas=[_as_metadata(item["metadata"]) for item in items],
    )


async def query_conversation_chunks(
    user_id: str,
    embedding: list[float],
    n: int,
) -> list[tuple[str, str, float]]:
    """Return up to ``n`` (date, chunk_text, similarity) for a user, best first."""
    collection = await _get_collection(CHROMA_CONVERSATION_CHUNKS_COLLECTION)
    n_results = await _clamp_n_results(collection, n)
    if n_results == 0:
        return []
    query_embeddings: list[Sequence[float] | Sequence[int]] = [embedding]
    result = await collection.query(
        query_embeddings=query_embeddings,
        n_results=n_results,
        where={"user_id": user_id},
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        (str(metadata.get("date", "")), document, 1.0 - distance)
        for document, metadata, distance in zip(documents, metadatas, distances)
    ]


async def upsert_episode(item: EpisodeVectorItem) -> None:
    """Upsert a daily-episode summary vector."""
    collection = await _get_collection(CHROMA_MEMORY_EPISODES_COLLECTION)
    embeddings: list[Sequence[float] | Sequence[int]] = [item["embedding"]]
    await collection.upsert(
        ids=[item["id"]],
        embeddings=embeddings,
        documents=[item["document"]],
        metadatas=[_as_metadata(item["metadata"])],
    )


async def query_episodes(
    user_id: str,
    embedding: list[float],
    n: int,
) -> list[tuple[str, float]]:
    """Return up to ``n`` (episode_id, cosine_similarity) for a user, best first."""
    collection = await _get_collection(CHROMA_MEMORY_EPISODES_COLLECTION)
    n_results = await _clamp_n_results(collection, n)
    if n_results == 0:
        return []

    query_embeddings: list[Sequence[float] | Sequence[int]] = [embedding]
    result = await collection.query(
        query_embeddings=query_embeddings,
        n_results=n_results,
        where={"user_id": user_id},
        include=["distances"],
    )
    ids = result["ids"][0]
    distances = (result.get("distances") or [[]])[0]
    return [(episode_id, 1.0 - distance) for episode_id, distance in zip(ids, distances)]
