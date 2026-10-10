"""
Service for managing GAIA self-knowledge in ChromaDB.

The corpus is tiny and production never writes it, so search_knowledge serves
from an in-memory snapshot: it loads the corpus once, then ranks locally by
cosine similarity. A turn pays one query embedding instead of a Chroma round
trip plus a corpus re-embed.

add_knowledge_batch and clear_knowledge drop the snapshot, so a write in this
process is visible on the next search. The offline populate script is a separate
process, so its writes are picked up at the next TTL refresh
(GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS); the TTL is the cross-process bound.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import math
from time import monotonic
from typing import Any, cast
import weakref

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field, field_validator

from app.constants.chroma import GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS
from app.core.lazy_loader import providers
from app.db.chroma.chromadb import ChromaClient
from shared.py.wide_events import log


class KnowledgeItem(BaseModel):
    """Schema for a single knowledge item."""

    content: str = Field(..., min_length=1, description="Knowledge content to store")
    metadata: dict[str, Any] | None = Field(default_factory=dict, description="Optional metadata")

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError("Content cannot be empty or whitespace only")
        return v.strip()


@dataclass
class KnowledgeResult:
    """Result from a knowledge search."""

    content: str
    relevance_score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _CorpusDoc:
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _Snapshot:
    docs: tuple[_CorpusDoc, ...]
    #: One unit-length vector per doc (index-aligned with ``docs``), so a dot
    #: product with a unit-length query is the cosine similarity.
    unit_vectors: tuple[tuple[float, ...], ...]


def _normalized(vector: Sequence[float]) -> tuple[float, ...]:
    """Return a unit-length copy of vector; the zero vector is returned unchanged."""
    norm = math.sqrt(sum(component * component for component in vector))
    if norm <= 0.0:
        return tuple(vector)
    return tuple(component / norm for component in vector)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    """Dot product of two equal-length vectors."""
    return sum(a * b for a, b in zip(left, right))


#: Load locks per event loop, since an asyncio.Lock binds to the loop that first
#: awaits it and this service is a process singleton. Keyed weakly by the loop
#: object: keying by id(loop) collides once a dead loop's id is reused.
_load_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _load_lock() -> asyncio.Lock:
    """Return the reload lock for the running event loop."""
    loop = asyncio.get_running_loop()
    lock = _load_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _load_locks[loop] = lock
    return lock


class GaiaKnowledgeService:
    """Service for managing GAIA self-knowledge in ChromaDB."""

    def __init__(self) -> None:
        self.collection_name = "gaia_knowledge"
        self._snapshot: _Snapshot | None = None
        self._loaded_at = 0.0

    async def search_knowledge(self, query: str, limit: int = 5) -> list[KnowledgeResult]:
        """Search the GAIA knowledge base using semantic similarity."""
        log.set(
            component="gaia_knowledge_service",
            operation="search_knowledge",
            query_preview=query[:50],
            limit=limit,
        )
        try:
            snapshot = await self._snapshot_or_reload()
            if snapshot is None or not snapshot.docs:
                return []

            query_unit = await self._embed_query(query)
            scores = [_dot(query_unit, doc_vector) for doc_vector in snapshot.unit_vectors]
            order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
            results = [
                KnowledgeResult(
                    content=snapshot.docs[index].content,
                    # Chroma's cosine space reports distance (1 - similarity);
                    # keep that scale so callers comparing scores still make sense.
                    relevance_score=1.0 - scores[index],
                    metadata=snapshot.docs[index].metadata,
                )
                for index in order[:limit]
            ]

            log.info("Found knowledge results for query", result_count=len(results))
            return results

        except Exception as e:
            log.error("Error searching GAIA knowledge", error=str(e), error_type=type(e).__name__)
            return []

    async def add_knowledge_batch(self, items: list[KnowledgeItem]) -> int:
        """Add multiple knowledge items in batch. Returns the number added."""
        log.set(
            component="gaia_knowledge_service",
            operation="add_knowledge_batch",
            item_count=len(items),
        )
        if not items:
            log.warning("add_knowledge_batch called with empty items list")
            return 0

        try:
            client = await ChromaClient.get_langchain_client(
                collection_name=self.collection_name, create_if_not_exists=True
            )

            # Extract texts and metadatas from validated Pydantic models
            texts = [item.content for item in items]
            metadatas = [item.metadata or {} for item in items]

            # Add documents in batch
            await client.aadd_texts(texts=texts, metadatas=metadatas)

            self._invalidate()
            log.info("Added knowledge items to ChromaDB", items_count=len(items))
            return len(items)

        except Exception as e:
            log.error(
                "Error adding knowledge batch",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            return 0

    async def clear_knowledge(self) -> bool:
        """Clear all knowledge from the collection (use with caution)."""
        try:
            # Get the async client to delete collection
            async_client = await ChromaClient.get_client()

            # Delete and recreate collection
            await async_client.delete_collection(name=self.collection_name)
            log.info("Cleared knowledge collection", collection_name=self.collection_name)

            # Recreate empty collection
            await async_client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            log.info("Recreated empty collection", collection_name=self.collection_name)

            self._invalidate()
            return True

        except Exception as e:
            log.error("Error clearing knowledge", error=str(e), error_type=type(e).__name__)
            return False

    def _invalidate(self) -> None:
        """Drop the snapshot so the next search reloads the current corpus."""
        self._snapshot = None
        self._loaded_at = 0.0

    def _fresh(self) -> bool:
        return (
            self._snapshot is not None
            and (monotonic() - self._loaded_at) < GAIA_KNOWLEDGE_SNAPSHOT_TTL_SECONDS
        )

    async def _snapshot_or_reload(self) -> _Snapshot | None:
        """Return the current snapshot, reloading when missing or past its TTL.

        A reload that fails while a snapshot is held keeps serving the last good
        corpus and backs off until the next TTL — a corpus is enrichment, and a
        refresh blip must not blank a section.
        """
        if self._fresh():
            return self._snapshot
        async with _load_lock():
            if self._fresh():
                return self._snapshot
            previous = self._snapshot
            try:
                snapshot = await self._load_snapshot()
            except Exception as e:
                if previous is None:
                    raise
                log.warning(
                    "gaia_knowledge snapshot refresh failed; serving the previous corpus",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                self._loaded_at = monotonic()
                return previous
            self._snapshot = snapshot
            self._loaded_at = monotonic()
            return snapshot

    async def _load_snapshot(self) -> _Snapshot:
        client = await ChromaClient.get_client()
        collection = await client.get_or_create_collection(name=self.collection_name)
        result = await collection.get(include=["documents", "metadatas"])
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        if not documents:
            return _Snapshot(docs=(), unit_vectors=())

        embeddings = cast(Embeddings, await providers.aget("google_embeddings"))
        vectors = await embeddings.aembed_documents(list(documents))

        docs: list[_CorpusDoc] = []
        unit_vectors: list[tuple[float, ...]] = []
        for index, content in enumerate(documents):
            if not content:
                continue
            docs.append(
                _CorpusDoc(
                    content=content,
                    metadata=dict(metadatas[index] if index < len(metadatas) else {}),
                )
            )
            unit_vectors.append(_normalized(list(vectors[index])))
        return _Snapshot(docs=tuple(docs), unit_vectors=tuple(unit_vectors))

    async def _embed_query(self, query: str) -> tuple[float, ...]:
        embeddings = cast(Embeddings, await providers.aget("google_embeddings"))
        vector = list(await embeddings.aembed_query(query))
        return _normalized(vector)


# Singleton instance
gaia_knowledge_service = GaiaKnowledgeService()
